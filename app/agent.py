"""Orchestrator: clean -> resolve -> tier -> twins -> rank -> (recover) -> savings -> explain.

The pipeline order is fixed code. The LLM is used for three jobs only: cleaning merchant
names, choosing a recovery action, and writing explanations. Every LLM output is validated
and has a code fallback, and every step is logged to the trace.
"""

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app import merchants, rank, resolve, savings, tiers, twins
from app.config import Settings
from app.llm import LLM, LLMError
from app.models import CleanMerchant, Place, RankedTwin, Resolution, TraceEntry, Transaction, Twin
from app.qloo_client import QlooBudgetExceeded, QlooClient, QlooError

MAX_MERCHANTS = 15
MAX_QLOO_CALLS = 40
MAX_RECOVERY_ITERS = 3
MIN_PICKS = 2
EXTRA_SIGNALS = 2
MAX_SHARED_TAGS = 6

Action = Literal["broaden_signal", "relax_rating_floor", "widen_tags", "give_up"]
FALLBACK_ORDER: tuple[Action, ...] = ("broaden_signal", "relax_rating_floor", "give_up")
ACTION_HELP = {
    "broaden_signal": "add the user's next 2 most-visited places as extra taste signals",
    "relax_rating_floor": "lower the minimum rating by 0.2 (only once)",
    "widen_tags": "also allow bars (wine, cocktail, pubs)",
    "give_up": "stop; report fewer than 2 swaps for this merchant",
}
# Tag types that describe taste; generic ones ("Restaurant", "Place") say nothing in an explanation.
DESCRIPTIVE_TAG_TYPES = ("urn:tag:cuisine:", "urn:tag:genre:place:restaurant", "urn:tag:culinary_style:",
                         "urn:tag:ambience:", "urn:tag:offerings:", "urn:tag:category:place")
GENERIC_TAG_NAMES = {"restaurant", "place", "food", "bar"}
BRACKET_RE = re.compile(r"\[\[(.+?)\]\]")


class ActionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    reason: str


class WhyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pick_id: str
    why: str


@dataclass
class Merchant:
    """One real-world merchant: every raw string that cleaned to the same name and city."""
    cm: CleanMerchant
    raws: list[str]
    amounts: list[float]
    dates: list

    @property
    def visits(self) -> int:
        return len(self.amounts)

    @property
    def avg_bill(self) -> float:
        return round(mean(self.amounts), 2)


@dataclass
class SignalState:
    extras: list[str]
    relaxed_steps: int = 0
    tags: tuple[str, ...] = resolve.FOOD_TAGS
    decisions: list[dict] = field(default_factory=list)


class Agent:
    def __init__(self, settings: Settings, llm: LLM | None = None, client: QlooClient | None = None):
        self.llm = llm or LLM(settings)
        self.client = client or QlooClient(settings, max_calls=MAX_QLOO_CALLS)
        self.trace: list[TraceEntry] = []

    # --- trace helpers ------------------------------------------------------------------

    def _log(self, step: str, tool: str, status: str, target: str = "", ms: int = 0, detail: str = "") -> None:
        self.trace.append(TraceEntry(step=step, tool=tool, target=target, status=status, ms=ms, detail=detail[:300]))

    def _qloo(self, step: str, target: str, fn, *args):
        """Run a Qloo-backed call and trace it. Budget errors propagate so run() can stop cleanly."""
        start = time.perf_counter()
        try:
            result = fn(*args)
        except QlooBudgetExceeded:
            self._log(step, "qloo", "budget_exhausted", target, detail=f"{self.client.calls} calls used")
            raise
        except QlooError as exc:
            self._log(step, "qloo", "error", target, int((time.perf_counter() - start) * 1000), str(exc))
            raise
        ms = int((time.perf_counter() - start) * 1000)
        status = "cached" if self.client.last_cached else "ok"
        return result, ms, status

    # --- pipeline -----------------------------------------------------------------------

    def run(self, txns: list[Transaction]) -> dict:
        first, last = min(t.date for t in txns), max(t.date for t in txns)
        by_raw: dict[str, list[Transaction]] = defaultdict(list)
        for t in txns:
            by_raw[t.merchant].append(t)

        cleaned, clean_trace = merchants.clean(list(by_raw), {r: ts[0].city for r, ts in by_raw.items()}, self.llm)
        self.trace += clean_trace
        food, skipped = merchants.split_food(cleaned)
        group = self._group(food, by_raw)
        self._log("clean", "code", "ok", detail=f"{len(cleaned)} raw -> {len(group)} food merchants, {len(skipped)} skipped")

        ordered = sorted(group, key=lambda m: (-sum(m.amounts), m.cm.name))
        analysed, over_cap = ordered[:MAX_MERCHANTS], ordered[MAX_MERCHANTS:]
        needs_review = [self._review(m, f"not analysed: merchant cap of {MAX_MERCHANTS}") for m in over_cap]

        resolved: list[tuple[Merchant, Resolution]] = []
        budget_hit = False
        for m in analysed:
            try:
                res, ms, status = self._qloo("resolve", m.cm.name, resolve.resolve, m.cm, self.client)
            except QlooBudgetExceeded:
                budget_hit = True
                needs_review.append(self._review(m, "not analysed: Qloo call budget used up"))
                continue
            except QlooError as exc:
                needs_review.append(self._review(m, f"Qloo search failed: {exc}"))
                continue
            self._log("resolve", "qloo.search", status if res.status == "resolved" else "needs_review", m.cm.name, ms,
                      res.place.name if res.place else res.reason)
            if res.status == "resolved":
                resolved.append((m, res))
            else:
                needs_review.append(self._review(m, res.reason))

        amounts = {r.place.entity_id: m.amounts for m, r in resolved}
        known = tiers.known_amounts(amounts, {r.place.entity_id: r.place.price_level for _, r in resolved})
        by_visits = sorted(resolved, key=lambda mr: (-mr[0].visits, -sum(mr[0].amounts), mr[0].cm.name))
        visited_ids = {r.place.entity_id for _, r in resolved}
        names = {r.place.entity_id: r.place.name for _, r in resolved}

        swaps, already_budget = [], []
        for m, res in resolved:
            if budget_hit:
                needs_review.append(self._review(m, "not analysed: Qloo call budget used up"))
                continue
            origin = res.place
            tier = tiers.assign(origin.price_level, m.avg_bill, known)
            self._log("tier", "code", tier.source, m.cm.name, detail=f"tier {tier.tier}")
            if tier.tier <= 1:
                already_budget.append({"merchant": m.cm.name, "qloo_name": origin.name, "visits": m.visits,
                                       "avg_bill": m.avg_bill, "tier": tier.tier, "tier_source": tier.source})
                self._log("twins", "code", "skipped", m.cm.name, detail="tier 1: already budget-friendly, no call")
                continue
            others = [r.place.entity_id for _, r in by_visits if r.place.entity_id != origin.entity_id]
            state = SignalState(extras=others[:EXTRA_SIGNALS])
            try:
                result, picks = self._twins_and_rank(m, origin, tier.tier, state, visited_ids)
                if len(picks) < MIN_PICKS:
                    result, picks = self._recover(m, origin, tier.tier, state, others, visited_ids, result, picks)
            except QlooBudgetExceeded:
                budget_hit = True
                needs_review.append(self._review(m, "not analysed: Qloo call budget used up"))
                continue
            except QlooError as exc:
                needs_review.append(self._review(m, f"Qloo insights failed: {exc}"))
                continue

            saving = None
            if picks:
                saving = savings.estimate(tier.tier, picks[0].price_level, known,
                                          savings.visits_per_month(m.visits, first, last)).model_dump()
            swaps.append({
                "merchant": m.cm.name, "raw": m.raws, "cleaned_by": m.cm.cleaned_by, "visits": m.visits,
                "avg_bill": m.avg_bill, "tier": tier.tier, "tier_source": tier.source,
                "qloo_name": origin.name, "address": origin.address, "rating": origin.business_rating,
                "branch_note": res.branch_note, "twins_path": result.path, "twins_note": result.note,
                "signals": [names.get(e, e) for e in [origin.entity_id] + state.extras],
                "rating_floor": rank.rating_floor(origin, state.relaxed_steps),
                "recovery": state.decisions, "status": "ok" if len(picks) >= MIN_PICKS else "few_twins",
                "picks": [self._pick_dict(p) for p in picks], "saving": saving,
                "_origin": origin, "_picks": picks, "_signal_ids": [origin.entity_id] + state.extras,
            })

        self._explain(swaps, names)
        for s in swaps:
            for key in ("_origin", "_picks", "_signal_ids"):
                s.pop(key)

        total = round(sum(s["saving"]["monthly_usd"] for s in swaps if s["saving"]), 2)
        return {
            "period": {"first": first.isoformat(), "last": last.isoformat()},
            "summary": {
                "transactions": len(txns), "food_merchants": len(group), "swaps": len(swaps),
                "total_monthly_saving_usd": total,
                "saving_is_estimate": any(s["saving"] and s["saving"]["estimate"] for s in swaps),
                "qloo_calls": self.client.calls, "llm_enabled": self.llm.enabled,
            },
            "swaps": swaps, "already_budget": already_budget, "needs_review": needs_review,
            "skipped": skipped, "trace": [t.model_dump() for t in self.trace],
        }

    @staticmethod
    def _group(food: list[CleanMerchant], by_raw: dict[str, list[Transaction]]) -> list[Merchant]:
        groups: dict[tuple[str, str], Merchant] = {}
        for cm in food:
            key = (resolve.normalize(cm.name), resolve.city_key(cm.city))
            ts = by_raw[cm.raw]
            if key not in groups:
                groups[key] = Merchant(cm=cm, raws=[], amounts=[], dates=[])
            g = groups[key]
            g.raws.append(cm.raw)
            g.amounts += [t.amount_usd for t in ts]
            g.dates += [t.date for t in ts]
            if cm.cleaned_by == "rules":
                g.cm = g.cm.model_copy(update={"cleaned_by": "rules"})
        return list(groups.values())

    @staticmethod
    def _review(m: Merchant, reason: str) -> dict:
        return {"merchant": m.cm.name, "raw": m.raws, "visits": m.visits, "avg_bill": m.avg_bill,
                "cleaned_by": m.cm.cleaned_by, "reason": reason}

    @staticmethod
    def _pick_dict(p: RankedTwin) -> dict:
        return {"name": p.name, "address": p.address, "price_level": p.price_level,
                "rating": round(p.business_rating, 1), "affinity": round(p.affinity, 3), "score": p.score}

    def _twins_and_rank(self, m: Merchant, origin: Place, tier: int, state: SignalState,
                        visited: set[str]) -> tuple[twins.TwinResult, list[RankedTwin]]:
        result, ms, status = self._qloo("twins", m.cm.name, twins.find, origin, tier, m.cm.city,
                                        state.extras, self.client, state.tags)
        self._log("twins", f"qloo.insights[{result.path}]", status, m.cm.name, ms,
                  f"{len(result.twins)} twins, cap {tier - 1}, {len(state.extras)} extra signals"
                  + (f"; {result.note}" if result.note else ""))
        floor = rank.rating_floor(origin, state.relaxed_steps)
        picks = rank.pick(origin, result.twins, floor, visited)
        self._log("rank", "code", "ok", m.cm.name,
                  detail=f"{len(picks)} picks, floor {floor}, dropped {rank.drop_reasons(origin, result.twins, floor, visited)}")
        return result, picks

    # --- agentic recovery ---------------------------------------------------------------
    #
    # MODEL CHOOSES, CODE ENFORCES.
    # The LLM only picks one action name from the list the code says is possible right now.
    # Code validates the choice, applies it, re-runs twins/rank through the same budgeted
    # Qloo client, and stops after MAX_RECOVERY_ITERS. If the LLM fails or picks something
    # not allowed, a fixed rule decides instead, and the trace says so.

    def _allowed(self, state: SignalState, others: list[str]) -> list[Action]:
        allowed: list[Action] = []
        if any(e not in state.extras for e in others):
            allowed.append("broaden_signal")
        if state.relaxed_steps == 0:
            allowed.append("relax_rating_floor")
        if state.tags == resolve.FOOD_TAGS:
            allowed.append("widen_tags")
        return allowed + ["give_up"]

    def _choose(self, m: Merchant, tier: int, state: SignalState, allowed: list[Action],
                n_picks: int, dropped: dict, n_twins: int) -> tuple[Action, str, str]:
        """Returns (action, reason, decided_by)."""
        fallback = next(a for a in FALLBACK_ORDER if a in allowed)
        if not self.llm.enabled:
            return fallback, "LLM disabled", "fallback rule"
        prompt = (
            f"A restaurant-swap search for '{m.cm.name}' (price tier {tier}) found {n_twins} cheaper candidates, "
            f"but only {n_picks} passed the filters (need {MIN_PICKS}). Dropped: {json.dumps(dropped)}.\n"
            f"Current: {len(state.extras)} extra taste signals, rating floor relaxed {state.relaxed_steps} time(s), "
            f"bars {'included' if state.tags != resolve.FOOD_TAGS else 'excluded'}.\n"
            "Choose ONE action from this list:\n"
            + "\n".join(f"- {a}: {ACTION_HELP[a]}" for a in allowed)
            + '\nReply with JSON only: {"action": "<one of the list>", "reason": "<one short sentence>"}'
        )
        try:
            data, info = self.llm.chat_json(prompt)
        except LLMError as exc:
            self._log("recover", "llm", "error", m.cm.name, exc.info.ms, str(exc))
            return fallback, f"LLM call failed ({str(exc)[:80]})", "fallback rule"
        try:
            choice = ActionChoice.model_validate(data)
        except ValidationError as exc:
            return fallback, f"LLM reply invalid ({exc.errors()[0]['msg']}): {str(data)[:80]}", "fallback rule"
        if choice.action not in allowed:
            return fallback, f"LLM chose '{choice.action}', which is not allowed now", "fallback rule"
        self._log("recover", "llm", "ok", m.cm.name, info.ms, f"chose {choice.action}")
        return choice.action, choice.reason, "llm"

    def _recover(self, m: Merchant, origin: Place, tier: int, state: SignalState, others: list[str],
                 visited: set[str], result: twins.TwinResult, picks: list[RankedTwin]):
        for i in range(MAX_RECOVERY_ITERS):
            if len(picks) >= MIN_PICKS:
                break
            floor = rank.rating_floor(origin, state.relaxed_steps)
            dropped = rank.drop_reasons(origin, result.twins, floor, visited)
            allowed = self._allowed(state, others)
            action, reason, decided_by = self._choose(m, tier, state, allowed, len(picks), dropped, len(result.twins))
            state.decisions.append({"iteration": i + 1, "action": action, "reason": reason, "decided_by": decided_by})
            self._log("recover", "code", action, m.cm.name,
                      detail=f"iteration {i + 1}, decided by {decided_by}: {reason}")
            if action == "give_up":
                break
            if action == "broaden_signal":
                state.extras += [e for e in others if e not in state.extras][:EXTRA_SIGNALS]
            elif action == "relax_rating_floor":
                state.relaxed_steps += 1
            elif action == "widen_tags":
                state.tags = resolve.FOOD_TAGS + resolve.BAR_TAGS
            result, picks = self._twins_and_rank(m, origin, tier, state, visited)
        else:
            if len(picks) < MIN_PICKS:
                self._log("recover", "code", "iteration_cap", m.cm.name, detail=f"stopped after {MAX_RECOVERY_ITERS}")
        return result, picks

    # --- explanations -------------------------------------------------------------------
    #
    # HARD RULE: an explanation may only name places Qloo returned for that pick
    # (the origin, the twin, and the signal places). Code checks every [[name]] and also
    # scans for any other place name known in this run; failures fall back to a template.
    # Limit: a made-up name the model writes without brackets, and which is not a place
    # we know, cannot be detected without entity extraction.

    @staticmethod
    def _shared_tags(origin: Place, twin: Twin) -> list[str]:
        def descriptive(p: Place) -> dict[str, str]:
            return {t.id: t.name for t in p.tags
                    if t.type.startswith(DESCRIPTIVE_TAG_TYPES) and t.name.lower() not in GENERIC_TAG_NAMES}
        o, w = descriptive(origin), descriptive(twin)
        return list(dict.fromkeys(w[i] for i in w if i in o))[:MAX_SHARED_TAGS]

    def _template(self, origin: Place, twin: RankedTwin, shared: list[str]) -> str:
        common = f"shares {', '.join(shared[:3])} with {origin.name}" if shared else f"is a Qloo taste match for {origin.name}"
        return (f"{twin.name} {common}; Qloo affinity {twin.affinity:.2f}, "
                f"rated {twin.business_rating:.1f}, price level {twin.price_level} vs {origin.price_level or 'unknown'}.")

    def _explain(self, swaps: list[dict], names: dict[str, str]) -> None:
        items, allowed_by_id, facts = [], {}, {}
        for si, s in enumerate(swaps):
            origin: Place = s["_origin"]
            for pi, p in enumerate(s["_picks"]):
                pid = f"s{si}p{pi}"
                shared = self._shared_tags(origin, p)
                signals = {names.get(e, e): round(p.explain.get(e, 0.0), 2) for e in s["_signal_ids"]}
                allowed_by_id[pid] = {origin.name, p.name, *signals}
                facts[pid] = (origin, p, shared, s["picks"][pi])
                items.append({"pick_id": pid, "origin": origin.name, "swap": p.name,
                              "origin_price_level": origin.price_level, "swap_price_level": p.price_level,
                              "swap_rating": round(p.business_rating, 1), "shared_tags": shared,
                              "influence_of_user_places": signals})
        if not items:
            return

        every_name = {n for allowed in allowed_by_id.values() for n in allowed} | set(names.values())
        written: dict[str, str] = {}
        if self.llm.enabled:
            prompt = (
                "For each item, write ONE sentence (max 30 words) on why 'swap' is a good cheaper alternative to "
                "'origin' for this user. Use only the facts in the item. Wrap every place name in [[double brackets]]. "
                "Name only places that appear in that same item.\n"
                'Reply with JSON only: {"items": [{"pick_id": "...", "why": "..."}]}\n\n'
                + json.dumps(items, indent=1)
            )
            try:
                data, info = self.llm.chat_json(prompt)
                self._log("explain", "llm", "ok", ms=info.ms, detail=f"{len(items)} items requested")
                for raw in (data.get("items", []) if isinstance(data, dict) else []):
                    try:
                        item = WhyItem.model_validate(raw)
                    except ValidationError:
                        continue
                    if item.pick_id in allowed_by_id:
                        written[item.pick_id] = item.why
            except LLMError as exc:
                self._log("explain", "llm", "error", ms=exc.info.ms, detail=str(exc))

        rejected = 0
        for pid, (origin, twin, shared, out) in facts.items():
            why, problem = written.get(pid), "missing from LLM reply"
            if why:
                problem = self._check_names(why, allowed_by_id[pid], every_name)
            if why and not problem:
                out["why"], out["why_source"] = BRACKET_RE.sub(r"\1", why), "llm"
            else:
                rejected += 1
                out["why"], out["why_source"] = self._template(origin, twin, shared), "template"
                if self.llm.enabled:
                    self._log("explain", "code", "rejected", twin.name, detail=problem)
        self._log("explain", "code", "ok", detail=f"{len(facts) - rejected} LLM, {rejected} template")

    @staticmethod
    def _check_names(why: str, allowed: set[str], every_name: set[str]) -> str:
        """Returns '' if the text only names allowed places, else the problem."""
        allowed_norm = {resolve.normalize(a) for a in allowed}
        for name in BRACKET_RE.findall(why):
            if resolve.normalize(name) not in allowed_norm:
                return f"names [[{name}]], which Qloo did not return for this pick"
        plain = f" {resolve.normalize(BRACKET_RE.sub(' ', why))} "
        for name in every_name - allowed:
            n = resolve.normalize(name)
            if n and n not in allowed_norm and f" {n} " in plain:
                return f"mentions '{name}', which is not part of this pick"
        return ""

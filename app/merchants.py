"""Turn bank-style merchant strings into {name, category, city}.

LLM first (one batched call, invalid items retried up to MAX_RETRIES times),
then a rule-based cleaner for anything the LLM could not do.
"""

import json
import re

from pydantic import BaseModel, ConfigDict, ValidationError

from app.llm import LLM, LLMError
from app.models import FOOD_CATEGORIES, Category, CleanMerchant, TraceEntry

MAX_RETRIES = 2

SYSTEM = "You clean credit-card merchant strings. Reply with JSON only, no prose."
PROMPT = """Clean each merchant string below.

Rules:
- name: the business name as people know it. Remove payment prefixes (SQ *, TST*), store numbers,
  order IDs, domains and city/neighbourhood words. Fix casing and apostrophes (KATZS -> Katz's).
- Do NOT expand a name you are not sure of. "JOE'S 0412" stays "Joe's" (could be many places).
- category: one of restaurant, cafe, bar, bakery, fast_food, non_food.
  Rides, shopping, utilities, transit, subscriptions are non_food.
- city: use the given city unless the string clearly names a different one.
- raw: copy the input string exactly.

Return exactly: {{"items": [{{"raw": "...", "name": "...", "category": "...", "city": "..."}}]}}

Input:
{items}
"""
RETRY_NOTE = "\nYour previous answer had problems:\n{errors}\nReturn all of the input items again, fixed.\n"


class LLMItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw: str
    name: str
    category: Category
    city: str


def clean(raw_names: list[str], city_hints: dict[str, str], llm: LLM) -> tuple[list[CleanMerchant], list[TraceEntry]]:
    pending = list(dict.fromkeys(raw_names))
    done: dict[str, CleanMerchant] = {}
    trace: list[TraceEntry] = []
    errors: list[str] = []

    for attempt in range(1 + MAX_RETRIES):
        if not pending or not llm.enabled:
            break
        items = json.dumps([{"raw": r, "city": city_hints.get(r, "")} for r in pending], indent=1)
        prompt = PROMPT.format(items=items) + (RETRY_NOTE.format(errors="\n".join(errors[:10])) if errors else "")
        try:
            data, info = llm.chat_json(prompt, SYSTEM)
        except LLMError as exc:
            trace.append(TraceEntry(step="clean", tool="llm", status="error", ms=exc.info.ms,
                                    detail=f"attempt {attempt + 1}: {exc}"[:300]))
            break  # the LLM itself is failing; retrying the same prompt is unlikely to help
        accepted, errors = _accept(data, set(pending))
        done.update(accepted)
        pending = [r for r in pending if r not in done]
        trace.append(TraceEntry(step="clean", tool="llm", status="ok" if not pending else "partial",
                                ms=info.ms, detail=f"attempt {attempt + 1}: {len(accepted)} valid, {len(pending)} left"))

    if pending:
        why = "LLM disabled" if not llm.enabled else "LLM failed or output invalid"
        trace.append(TraceEntry(step="clean", tool="rules", status="fallback",
                                detail=f"{len(pending)} merchant(s) cleaned without LLM ({why})"))
    for raw in pending:
        done[raw] = rules_clean(raw, city_hints.get(raw, ""))
    return [done[r] for r in dict.fromkeys(raw_names)], trace


def _accept(data: object, wanted: set[str]) -> tuple[dict[str, CleanMerchant], list[str]]:
    """Validate the LLM reply item by item. Returns the valid items and a list of error lines."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return {}, ['top level must be {"items": [...]}']
    accepted, errors = {}, []
    for item in data["items"]:
        try:
            parsed = LLMItem.model_validate(item)
        except ValidationError as exc:
            errors.append(f"{str(item)[:80]}: {exc.errors()[0]['msg']}")
            continue
        if parsed.raw not in wanted:
            errors.append(f"raw {parsed.raw!r} is not one of the input strings")
        elif not parsed.name.strip() or not parsed.city.strip():
            errors.append(f"{parsed.raw!r}: name and city must be non-empty")
        else:
            accepted[parsed.raw] = CleanMerchant(**parsed.model_dump(), cleaned_by="llm")
    returned = {item.get("raw") for item in data["items"] if isinstance(item, dict)}
    errors += [f"missing item for raw {r!r}" for r in sorted(wanted - returned)]
    return accepted, errors


# --- rule-based fallback -------------------------------------------------------------

PREFIX_RE = re.compile(r"^(SQ|TST|SP|PY|DD|UE|PP)\s*\*\s*", re.I)
TAIL_AFTER_STAR_RE = re.compile(r"\*.*$")
DOMAIN_RE = re.compile(r"\b[\w-]+\.(com|net|org|co)\b", re.I)
NOISE_RE = re.compile(r"#\s*\d+|(?<![.\w])\d+\b")  # store numbers, but keep "NO.1"
CITY_WORDS = {"nyc", "ny", "new", "york", "brooklyn", "bklyn", "manhattan", "uws", "ues", "chelsea", "soho"}
NON_FOOD_WORDS = {"uber", "lyft", "amzn", "amazon", "netflix", "spotify", "coned", "mta", "nyct", "apple", "google"}
CATEGORY_WORDS = [("bakery", {"bakery", "bakeshop"}), ("cafe", {"cafe", "coffee", "espresso"}),
                  ("bar", {"bar", "pub", "tavern", "saloon"})]


def rules_clean(raw: str, city: str) -> CleanMerchant:
    words = set(re.findall(r"[a-z]+", raw.lower()))
    category: str = "restaurant"
    if words & NON_FOOD_WORDS:
        category = "non_food"
    else:
        for cat, keys in CATEGORY_WORDS:
            if words & keys:
                category = cat
                break
    text = PREFIX_RE.sub("", raw.strip())
    domain = DOMAIN_RE.search(text)
    text = domain.group(0).split(".")[0] if domain and text.upper().startswith(domain.group(0).upper()) else DOMAIN_RE.sub("", text)
    text = NOISE_RE.sub(" ", TAIL_AFTER_STAR_RE.sub("", text))
    kept = [w for w in re.split(r"\s+", text) if w and w.lower().strip(".,") not in CITY_WORDS]
    # Capitalise only the first letter of each word: str.title() turns "JOE'S" into "Joe'S".
    name = " ".join(w[:1].upper() + w[1:].lower() for w in kept).strip(" .,-") or raw.strip()
    return CleanMerchant(raw=raw, name=name, category=category, city=city or "unknown", cleaned_by="rules")


def split_food(cleaned: list[CleanMerchant]) -> tuple[list[CleanMerchant], list[dict]]:
    food = [c for c in cleaned if c.category in FOOD_CATEGORIES]
    skipped = [{"raw": c.raw, "name": c.name, "reason": f"non-food merchant (cleaned by {c.cleaned_by})"}
               for c in cleaned if c.category not in FOOD_CATEGORIES]
    return food, skipped

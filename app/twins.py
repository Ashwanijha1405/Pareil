"""Find cheaper taste twins for one origin place via Qloo insights.

Primary path: POST with weighted signals (origin 3, user's other places 1), the form verified in
FINDINGS.md (P1). If the POST errors or a result breaks a filter, fall back to GET with equal weights.
"""

from typing import Literal

from pydantic import BaseModel

from app.models import Place, Twin
from app.qloo_client import QlooBudgetExceeded, QlooClient, QlooError
from app.resolve import FOOD_TAGS

ORIGIN_WEIGHT = 3
EXTRA_WEIGHT = 1
TAKE = 20


class TwinResult(BaseModel):
    status: Literal["ok", "already_budget"]
    twins: list[Twin] = []
    path: Literal["", "post_weighted", "get_equal_weights"] = ""
    note: str = ""


def _common(city: str, cap: int, tags: tuple[str, ...]) -> dict:
    return {
        "filter.type": "urn:entity:place",
        "filter.location.query": city,
        "filter.tags": ",".join(tags),
        "filter.price_level.max": cap,
        "take": TAKE,
    }


def post_body(origin_id: str, extras: list[str], city: str, cap: int, tags: tuple[str, ...]) -> dict:
    signals = [{"id": origin_id, "weight": ORIGIN_WEIGHT}] + [{"id": e, "weight": EXTRA_WEIGHT} for e in extras]
    return {**_common(city, cap, tags), "signal.interests.entities": signals, "feature.explainability": True}


def get_params(origin_id: str, extras: list[str], city: str, cap: int, tags: tuple[str, ...]) -> dict:
    return {**_common(city, cap, tags), "signal.interests.entities": ",".join([origin_id] + extras),
            "feature.explainability": "true"}


def violations(twins: list[Twin], cap: int, tags: tuple[str, ...]) -> list[str]:
    bad = []
    for t in twins:
        if t.price_level is None or t.price_level > cap:
            bad.append(f"{t.name}: price_level {t.price_level} (cap {cap})")
        elif not t.tag_ids() & set(tags):
            bad.append(f"{t.name}: no requested tag")
    return bad


def find(origin: Place, tier: int, city: str, extras: list[str], client: QlooClient,
         tags: tuple[str, ...] = FOOD_TAGS) -> TwinResult:
    if tier <= 1:
        return TwinResult(status="already_budget", note="tier 1: already budget-friendly")
    cap = tier - 1

    try:
        twins = [Twin.from_qloo(e) for e in client.insights_post(post_body(origin.entity_id, extras, city, cap, tags))]
        bad = violations(twins, cap, tags)
        if not bad:
            return TwinResult(status="ok", twins=twins, path="post_weighted")
        reason = f"POST ignored a filter ({bad[0]})"
    except QlooBudgetExceeded:
        raise
    except QlooError as exc:
        reason = f"POST failed: {exc}"[:200]

    twins = [Twin.from_qloo(e) for e in client.insights_get(get_params(origin.entity_id, extras, city, cap, tags))]
    bad = violations(twins, cap, tags)
    if bad:
        bad_names = {b.split(":")[0] for b in bad}
        twins = [t for t in twins if t.name not in bad_names]
        reason += f"; GET also broke filters, dropped {len(bad)} in code"
    return TwinResult(status="ok", twins=twins, path="get_equal_weights", note=reason)

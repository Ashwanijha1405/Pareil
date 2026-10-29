"""Find cheaper taste twins for one origin place via Qloo insights.

Price: filter.price_level.min = max = origin tier - tiers_down (default 1: "one step cheaper").
Verified in FINDINGS.md (M1): min=max=2 returned 20/20 at level 2.

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
    status: Literal["ok", "already_budget", "no_lower_tier"]
    twins: list[Twin] = []
    path: Literal["", "post_weighted", "get_equal_weights"] = ""
    level: int = 0
    note: str = ""
    request: dict = {}  # endpoint and key params of the call that produced `twins`


def _common(city: str, level: int, tags: tuple[str, ...]) -> dict:
    return {
        "filter.type": "urn:entity:place",
        "filter.location.query": city,
        "filter.tags": ",".join(tags),
        "filter.price_level.min": level,
        "filter.price_level.max": level,
        "take": TAKE,
    }


def post_body(origin_id: str, extras: list[str], city: str, level: int, tags: tuple[str, ...]) -> dict:
    signals = [{"id": origin_id, "weight": ORIGIN_WEIGHT}] + [{"id": e, "weight": EXTRA_WEIGHT} for e in extras]
    return {**_common(city, level, tags), "signal.interests.entities": signals, "feature.explainability": True}


def get_params(origin_id: str, extras: list[str], city: str, level: int, tags: tuple[str, ...]) -> dict:
    return {**_common(city, level, tags), "signal.interests.entities": ",".join([origin_id] + extras),
            "feature.explainability": "true"}


def request_summary(method: str, origin_id: str, extras: list[str], city: str, level: int,
                    tags: tuple[str, ...]) -> dict:
    weights = [ORIGIN_WEIGHT] + [EXTRA_WEIGHT] * len(extras) if method == "POST" else [1] * (1 + len(extras))
    return {"endpoint": f"{method} /v2/insights", "filter.type": "urn:entity:place",
            "filter.location.query": city, "filter.tags": list(tags),
            "filter.price_level.min": level, "filter.price_level.max": level,
            "signals": [{"id": i, "weight": w} for i, w in zip([origin_id] + extras, weights)],
            "feature.explainability": True, "take": TAKE}


def violations(twins: list[Twin], level: int, tags: tuple[str, ...]) -> list[str]:
    bad = []
    for t in twins:
        if t.price_level != level:
            bad.append(f"{t.name}: price_level {t.price_level} (wanted {level})")
        elif not t.tag_ids() & set(tags):
            bad.append(f"{t.name}: no requested tag")
    return bad


def find(origin: Place, tier: int, city: str, extras: list[str], client: QlooClient,
         tags: tuple[str, ...] = FOOD_TAGS, tiers_down: int = 1) -> TwinResult:
    if tier <= 1:
        return TwinResult(status="already_budget", note="tier 1: already budget-friendly")
    level = tier - tiers_down
    if level < 1:
        return TwinResult(status="no_lower_tier", note=f"no tier {level} exists")

    try:
        twins = [Twin.from_qloo(e) for e in client.insights_post(post_body(origin.entity_id, extras, city, level, tags))]
        bad = violations(twins, level, tags)
        if not bad:
            return TwinResult(status="ok", twins=twins, path="post_weighted", level=level,
                              request=request_summary("POST", origin.entity_id, extras, city, level, tags))
        reason = f"POST ignored a filter ({bad[0]})"
    except QlooBudgetExceeded:
        raise
    except QlooError as exc:
        reason = f"POST failed: {exc}"[:200]

    twins = [Twin.from_qloo(e) for e in client.insights_get(get_params(origin.entity_id, extras, city, level, tags))]
    bad = violations(twins, level, tags)
    if bad:
        bad_names = {b.split(":")[0] for b in bad}
        twins = [t for t in twins if t.name not in bad_names]
        reason += f"; GET also broke filters, dropped {len(bad)} in code"
    return TwinResult(status="ok", twins=twins, path="get_equal_weights", level=level, note=reason,
                      request=request_summary("GET", origin.entity_id, extras, city, level, tags))

"""Deterministic ranking of Qloo twins. No LLM, no I/O.

Filters: drop the origin, places the user already visits, same-brand branches,
twins without a rating, and twins rated below the floor.

    score = affinity * (business_rating / 5)

affinity is Qloo's taste similarity (0-1); business_rating / 5 maps the rating to 0-1.
Qloo's affinities sit in a narrow band (~0.94-0.98), so the rating factor decides most orderings.
Ties break on entity_id so the same input always gives the same order.
"""

from app.models import Place, RankedTwin, Twin
from app.resolve import normalize

DEFAULT_FLOOR = 4.0
RELAX_STEP = 0.2


def rating_floor(origin: Place, relaxed_steps: int = 0) -> float:
    base = origin.business_rating if origin.business_rating is not None else DEFAULT_FLOOR
    return round(base - RELAX_STEP * relaxed_steps, 2)


def same_brand(a: str, b: str) -> bool:
    na, nb = normalize(a), normalize(b)
    return na == nb or na.startswith(nb + " ") or nb.startswith(na + " ")


def pick(origin: Place, twins: list[Twin], floor: float, exclude_ids: set[str] = frozenset(), n: int = 3) -> list[RankedTwin]:
    kept = [
        t for t in twins
        if t.entity_id != origin.entity_id
        and t.entity_id not in exclude_ids
        and not same_brand(t.name, origin.name)
        and t.business_rating is not None
        and t.business_rating >= floor
    ]
    ranked = [RankedTwin(**t.model_dump(), score=round(t.affinity * t.business_rating / 5, 4)) for t in kept]
    ranked.sort(key=lambda r: (-r.score, r.entity_id))
    return ranked[:n]

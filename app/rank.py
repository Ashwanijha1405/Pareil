"""Deterministic ranking of Qloo twins. No LLM, no I/O.

Product promise: same vibe, cheaper, never worse. A twin is rejected if it is the origin,
a place the user already visits, a branch of the same brand, unrated, rated below the origin
(4.0 if the origin has no rating), shares no SPECIFIC cuisine/genre concept with the origin
(broad ones like "american" or "fine_dining" don't count alone), or is nightlife-only while the origin is a restaurant (unless bars were explicitly allowed).

    score = (business_rating / 5) * (0.5 + 0.5 * jaccard)

jaccard is the overlap of meaningful (non-generic, non-nightlife) concepts between origin and
twin. Qloo affinity is kept in the output but not scored: it only spans ~0.94-0.98.
Ties break on entity_id so the same input always gives the same order.
"""

from app.models import Place, RankedTwin, Twin
from app.resolve import normalize

DEFAULT_FLOOR = 4.0

# Concepts come from these tag families. All three name cuisine/genre, with different spellings:
# cuisine:qloo:italian, genre:place:restaurant:italian, category:place:italian_restaurant -> "italian".
CONCEPT_PREFIXES = ("urn:tag:cuisine:qloo:", "urn:tag:genre:place:restaurant:", "urn:tag:category:place:")
# Seen on (nearly) every place in real NYC responses, so they say nothing about vibe.
# seafood: on 72/117 NYC twins, including pizza and burger places.
GENERIC_CONCEPTS = {"restaurant", "place", "seafood", "food", "takeout", "delivery"}
NIGHTLIFE_CONCEPTS = {"bar", "wine_bar", "cocktail_bar", "lounge_bar", "pub", "beer_bar",
                      "sports_bar", "night_club", "hookah_bar", "karaoke_bar"}
# Count toward overlap but can't satisfy the vibe check alone: umbrella cuisines and
# meal/occasion/style concepts, from real NYC responses (american on 39/117 twins, new_american 16).
BROAD_CONCEPTS = {"american", "new_american", "contemporary_american", "modern_american", "european",
                  "asian", "mediterranean", "fusion", "eurasian", "international",
                  "fine_dining", "brunch", "lunch", "breakfast", "family", "event_venue", "dance"}


def concepts(place: Place) -> set[str]:
    """Cuisine/genre concepts of a place, generic ones removed. Nightlife concepts are kept."""
    out = set()
    for tag_id in place.tag_ids():
        for prefix in CONCEPT_PREFIXES:
            if tag_id.startswith(prefix):
                key = tag_id[len(prefix):].removesuffix("_restaurant")
                if key and ":" not in key and key not in GENERIC_CONCEPTS:
                    out.add(key)
    return out


def food_concepts(place: Place) -> set[str]:
    return concepts(place) - NIGHTLIFE_CONCEPTS


def specific_concepts(place: Place) -> set[str]:
    return food_concepts(place) - BROAD_CONCEPTS


def is_nightlife_only(place: Place) -> bool:
    c = concepts(place)
    return bool(c & NIGHTLIFE_CONCEPTS) and not (c - NIGHTLIFE_CONCEPTS)


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def rating_floor(origin: Place) -> float:
    return origin.business_rating if origin.business_rating is not None else DEFAULT_FLOOR


def same_brand(a: str, b: str) -> bool:
    na, nb = normalize(a), normalize(b)
    return na == nb or na.startswith(nb + " ") or nb.startswith(na + " ")


def reject_reason(origin: Place, twin: Twin, floor: float, exclude_ids: set[str], allow_nightlife: bool) -> str:
    """'' if the twin is acceptable, else the reason. pick() and drop_reasons() both use this."""
    if twin.entity_id == origin.entity_id:
        return "is_origin"
    if twin.entity_id in exclude_ids:
        return "already_visited"
    if same_brand(twin.name, origin.name):
        return "same_brand"
    if twin.business_rating is None:
        return "no_rating"
    if twin.business_rating < floor:
        return "rating_below_floor"
    if not allow_nightlife and is_nightlife_only(twin) and not is_nightlife_only(origin):
        return "nightlife_only"
    if not specific_concepts(origin) & specific_concepts(twin):
        return "no_shared_specific_tag"
    return ""


def drop_reasons(origin: Place, twins: list[Twin], floor: float, exclude_ids: set[str] = frozenset(),
                 allow_nightlife: bool = False) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in twins:
        reason = reject_reason(origin, t, floor, exclude_ids, allow_nightlife)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def pick(origin: Place, twins: list[Twin], floor: float, exclude_ids: set[str] = frozenset(),
         allow_nightlife: bool = False, n: int | None = 3) -> list[RankedTwin]:
    origin_concepts = food_concepts(origin)
    ranked, seen = [], set()
    for t in twins:
        if t.entity_id in seen or reject_reason(origin, t, floor, exclude_ids, allow_nightlife):
            continue
        seen.add(t.entity_id)
        twin_concepts = food_concepts(t)
        j = jaccard(origin_concepts, twin_concepts)
        ranked.append(RankedTwin(
            **t.model_dump(),
            score=round(t.business_rating / 5 * (0.5 + 0.5 * j), 4),
            jaccard=round(j, 3),
            shared=sorted(origin_concepts & twin_concepts),
            tiers_down=(origin.price_level - t.price_level) if origin.price_level and t.price_level else 1,
        ))
    ranked.sort(key=lambda r: (-r.score, r.entity_id))
    return ranked if n is None else ranked[:n]


def dedupe(candidates: list[list[RankedTwin]], n: int = 3) -> list[list[RankedTwin]]:
    """Each twin goes only to the merchant where it scores highest.

    candidates is one ranked list per merchant, in processing order (highest total spend first);
    a score tie goes to the earlier merchant. Each list is then cut to n.
    """
    owner: dict[str, tuple[float, int]] = {}
    for i, twins in enumerate(candidates):
        for t in twins:
            if t.entity_id not in owner or t.score > owner[t.entity_id][0]:
                owner[t.entity_id] = (t.score, i)
    return [[t for t in twins if owner[t.entity_id][1] == i][:n] for i, twins in enumerate(candidates)]

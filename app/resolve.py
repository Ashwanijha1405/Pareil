"""Match a cleaned merchant to one Qloo place, or mark it needs_review instead of guessing."""

import re
from difflib import SequenceMatcher

from app.models import CleanMerchant, Place, Resolution
from app.qloo_client import QlooClient

# Tag IDs observed in real Qloo responses (FINDINGS.md); the docs list none for places.
FOOD_TAGS = ("urn:tag:genre:place:restaurant", "urn:tag:category:place:cafe", "urn:tag:category:place:bakery")
BAR_TAGS = ("urn:tag:category:place:bar", "urn:tag:category:place:wine_bar",
            "urn:tag:category:place:cocktail_bar", "urn:tag:category:place:pub")

# The points used in the verified search tests (scripts/price_test.py).
CITY_POINTS = {"new york": "40.7279,-74.0003", "bengaluru": "12.9716,77.5946"}
CITY_ALIASES = {"nyc": "new york", "new york city": "new york", "bangalore": "bengaluru"}

MIN_SCORE = 0.75
AMBIGUITY_GAP = 0.1
DROP_TOKENS = {"the", "nyc", "ny"}


def city_key(city: str) -> str:
    key = city.strip().lower()
    return CITY_ALIASES.get(key, key)


def normalize(name: str) -> str:
    text = name.lower().replace("’", "'").replace("'", "").replace("&", " and ")  # "Burgers & Wings" == "Burgers and Wings"
    text = re.sub(r"[^a-z0-9]+", " ", text).replace("new york", " ")
    return " ".join(w for w in text.split() if w not in DROP_TOKENS)


def name_score(query: str, candidate: str) -> float:
    q, c = normalize(query), normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if c.startswith(q + " ") or q.startswith(c + " "):
        return 0.9
    # Fuzzy only when the first word agrees: "bellas home kitchen" vs "wanisa home kitchen" scores 0.79 otherwise.
    if q.split()[0] != c.split()[0]:
        return 0.0
    return SequenceMatcher(None, q, c).ratio()


def pick(cm: CleanMerchant, results: list[dict]) -> Resolution:
    places = [Place.from_qloo(r) for r in results]
    food = [p for p in places if p.tag_ids() & set(FOOD_TAGS + BAR_TAGS)]
    if not food:
        reason = "not found in Qloo" if not places else f"Qloo found {len(places)} place(s), none tagged as food"
        return Resolution(merchant=cm, status="needs_review", reason=reason)

    scored = sorted(((name_score(cm.name, p.name), i, p) for i, p in enumerate(food)), key=lambda x: (-x[0], x[1]))
    best_score, _, best = scored[0]
    if best_score == 0:
        return Resolution(merchant=cm, status="needs_review", reason="not found in Qloo (no similar name)")
    if best_score < MIN_SCORE:
        return Resolution(merchant=cm, status="needs_review", match_score=best_score,
                          reason=f"no confident match (closest: {best.name}, {best_score:.2f})")

    best_norm = normalize(best.name)
    query_norm = normalize(cm.name)
    if " " not in query_norm:
        # A one-word name ("Joe's") that starts several differently named places is generic,
        # even if one place happens to carry exactly that name.
        variants = {normalize(p.name) for p in food if normalize(p.name).startswith(query_norm + " ")}
        if len(variants) >= 2:
            names = ", ".join(dict.fromkeys(p.name for p in food if normalize(p.name) != query_norm))
            return Resolution(merchant=cm, status="needs_review", match_score=best_score,
                              reason=f"generic name; Qloo has several: {names}")
    def is_branch(p: Place) -> bool:
        # Same name, or (for multi-word names) the name plus a location suffix:
        # "Leon's Burgers & Wings HSR Layout" is a branch of "Leon's Burgers & Wings".
        n = normalize(p.name)
        return n == best_norm or (" " in query_norm and n.startswith(query_norm + " "))

    if best_score < 1.0:
        rivals = [p for s, _, p in scored[1:]
                  if s >= best_score - AMBIGUITY_GAP and normalize(p.name) != best_norm and not is_branch(p)]
        if rivals:
            names = ", ".join(dict.fromkeys([best.name] + [p.name for p in rivals]))
            return Resolution(merchant=cm, status="needs_review", match_score=best_score,
                              reason=f"ambiguous: {names}")

    branches = [p for s, _, p in scored if s >= best_score - AMBIGUITY_GAP and is_branch(p)]
    if len(branches) <= 1:
        return Resolution(merchant=cm, status="resolved", place=best, match_score=best_score)
    # Prefer the branch whose location words appear in the bank string ("LEONS BURGERS HSR").
    raw_words = set(normalize(cm.raw).split())
    located = [p for p in branches if set(normalize(p.name).split()[len(query_norm.split()):]) & raw_words]
    chosen, how = (located[0], "matched the bank string") if located else (branches[0], "Qloo's first")
    note = f"{len(branches)} branches; using {chosen.name} ({how})"
    return Resolution(merchant=cm, status="resolved", place=chosen, match_score=best_score, branch_note=note)


def resolve(cm: CleanMerchant, client: QlooClient) -> Resolution:
    point = CITY_POINTS.get(city_key(cm.city))
    if not point:
        return Resolution(merchant=cm, status="needs_review", reason=f"city '{cm.city}' not supported yet")
    return pick(cm, client.search(cm.name, point))

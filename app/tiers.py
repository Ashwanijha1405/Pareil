"""Price tier (1-4) for a merchant: Qloo's price_level, else inferred from the user's own spend.

Rule, in order:
1. Qloo price_level present           -> that tier                       (source "qloo")
2. >= 2 tiers have Qloo-tiered spend  -> tier whose average bill is nearest
   on a log scale; ties go to the cheaper tier                           ("inferred_from_user_spend")
3. otherwise fixed per-bill bands: <=$15 -> 1, <=$35 -> 2, <=$75 -> 3, else 4   ("inferred_fixed_bands")

Only merchants with a Qloo tier feed rule 2, so an inferred tier never shapes another inference.
Merchants where the user already spends like a lower tier (own average bill falls in a lower
fixed band than Qloo's tier, e.g. Katz's: tier 3, $32.90 a bill) are left out of the averages.
Log scale because tiers are multiplicative: $40 is nearer $30 than $60.
"""

import math
from collections import defaultdict
from statistics import mean

from app.models import TierInfo

FIXED_BANDS = ((15.0, 1), (35.0, 2), (75.0, 3))


def spend_band(avg: float) -> int:
    for limit, tier in FIXED_BANDS:
        if avg <= limit:
            return tier
    return 4


def known_amounts(amounts_by_merchant: dict[str, list[float]],
                  qloo_tiers: dict[str, int | None]) -> tuple[dict[int, list[float]], list[str]]:
    """Bills per Qloo tier, and the merchants left out because the user spends like a lower tier there."""
    known: dict[int, list[float]] = defaultdict(list)
    excluded = []
    for merchant, amounts in amounts_by_merchant.items():
        tier = qloo_tiers.get(merchant)
        if not tier or not amounts:
            continue
        if spend_band(mean(amounts)) < tier:
            excluded.append(merchant)
            continue
        known[tier].extend(amounts)
    return dict(known), excluded


def assign(price_level: int | None, merchant_avg: float, known: dict[int, list[float]]) -> TierInfo:
    if price_level:
        return TierInfo(tier=price_level, source="qloo")
    averages = {tier: mean(a) for tier, a in known.items() if a}
    if len(averages) >= 2 and merchant_avg > 0:
        target = math.log(merchant_avg)
        tier = min(averages, key=lambda t: (abs(math.log(averages[t]) - target), t))
        return TierInfo(tier=tier, source="inferred_from_user_spend")
    return TierInfo(tier=spend_band(merchant_avg), source="inferred_fixed_bands")

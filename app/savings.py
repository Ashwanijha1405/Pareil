"""Estimated monthly saving from swapping one merchant for a cheaper twin. No I/O.

    origin_avg = the user's own average bill at this merchant
    target_avg = mean bill at the user's Qloo-tiered merchants of the twin's tier,
                 or FALLBACK_AVG[tier] if that tier has fewer than MIN_VISITS bills  -> estimate=True
    full       = min(visits_per_month * (origin_avg - target_avg), monthly spend at this merchant)
    half       = full * SWAP_SHARE   (headline: "if you swap 1 in 2 visits")

If origin_avg <= target_avg the saving is 0: the user already spends like a lower tier there.
"""

from datetime import date
from statistics import mean

from app.models import Saving

MIN_VISITS = 3
SWAP_SHARE = 0.5
FALLBACK_AVG = {1: 12.0, 2: 25.0, 3: 55.0, 4: 110.0}  # USD per bill, a rough NYC guess


def tier_avg(tier: int, known: dict[int, list[float]]) -> tuple[float, bool]:
    """Returns (average bill, is_estimate)."""
    amounts = known.get(tier, [])
    if len(amounts) >= MIN_VISITS:
        return round(mean(amounts), 2), False
    return FALLBACK_AVG[tier], True


def visits_per_month(n_visits: int, first: date, last: date) -> float:
    months = max(1.0, (last - first).days / 30.44)  # Oct 1 -> Oct 31 is one month
    return round(n_visits / months, 2)


def estimate(origin_avg: float, target_tier: int, known: dict[int, list[float]], per_month: float) -> Saving:
    target_avg, is_estimate = tier_avg(target_tier, known)
    note = f"tier-{target_tier} average is a fallback (fewer than {MIN_VISITS} bills)" if is_estimate else ""
    if origin_avg <= target_avg:
        full, note = 0.0, "already spending like a lower tier here"
    else:
        full = min(per_month * (origin_avg - target_avg), per_month * origin_avg)
    return Saving(
        monthly_usd_full=round(full, 2),
        monthly_usd_half=round(full * SWAP_SHARE, 2),
        origin_avg=round(origin_avg, 2),
        target_avg=target_avg,
        visits_per_month=per_month,
        estimate=is_estimate,
        note=note,
    )

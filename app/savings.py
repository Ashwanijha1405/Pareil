"""Estimated monthly saving from swapping one merchant for a cheaper twin. No I/O.

    tier_avg(t) = mean bill at Qloo-tiered merchants of tier t (user's own data)
                  or FALLBACK_AVG[t] if that tier has fewer than MIN_VISITS bills  -> estimate=True
    saving      = visits_per_month * (tier_avg(origin) - tier_avg(target)), floored at 0
"""

from datetime import date
from statistics import mean

from app.models import Saving

MIN_VISITS = 3
FALLBACK_AVG = {1: 12.0, 2: 25.0, 3: 55.0, 4: 110.0}  # USD per bill, a rough NYC guess


def tier_avg(tier: int, known: dict[int, list[float]]) -> tuple[float, bool]:
    """Returns (average bill, is_estimate)."""
    amounts = known.get(tier, [])
    if len(amounts) >= MIN_VISITS:
        return round(mean(amounts), 2), False
    return FALLBACK_AVG[tier], True


def visits_per_month(n_visits: int, first: date, last: date) -> float:
    months = max(1.0, ((last - first).days + 1) / 30)
    return round(n_visits / months, 2)


def estimate(origin_tier: int, target_tier: int, known: dict[int, list[float]], per_month: float) -> Saving:
    origin_avg, origin_est = tier_avg(origin_tier, known)
    target_avg, target_est = tier_avg(target_tier, known)
    gap = origin_avg - target_avg
    note = ""
    if origin_est or target_est:
        note = "uses fallback averages for tiers with fewer than %d bills" % MIN_VISITS
    if gap < 0:
        note = f"your tier-{target_tier} bills average more than tier-{origin_tier}; no saving claimed"
    return Saving(
        monthly_usd=round(max(0.0, gap) * per_month, 2),
        origin_avg=origin_avg,
        target_avg=target_avg,
        visits_per_month=per_month,
        estimate=origin_est or target_est,
        note=note,
    )

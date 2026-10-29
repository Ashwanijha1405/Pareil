from datetime import date

import pytest

from app.savings import FALLBACK_AVG, estimate, tier_avg, visits_per_month

TIER3 = {3: [60.0, 70.0, 80.0]}  # average 70


def test_uses_users_own_average_with_enough_bills():
    assert tier_avg(4, {4: [200.0, 220.0, 240.0]}) == (220.0, False)


def test_falls_back_with_fewer_than_three_bills():
    assert tier_avg(4, {4: [200.0, 220.0]}) == (FALLBACK_AVG[4], True)


def test_origin_side_is_the_merchants_own_average_bill():
    s = estimate(origin_avg=225.0, target_tier=3, known=TIER3, per_month=4.0)
    assert s.origin_avg == 225.0
    assert s.monthly_full == 4.0 * (225.0 - 70.0)
    assert s.estimate is False


def test_headline_is_half_of_full():
    s = estimate(origin_avg=225.0, target_tier=3, known=TIER3, per_month=4.0)
    assert s.monthly_half == s.monthly_full / 2


def test_fallback_target_tier_marks_estimate():
    s = estimate(origin_avg=225.0, target_tier=3, known={}, per_month=2.0)
    assert s.estimate is True
    assert s.monthly_full == 2.0 * (225.0 - FALLBACK_AVG[3])


def test_already_spending_like_lower_tier_saves_nothing():
    # Katz's in the sample: Qloo says tier 3, but the user's bills average $32.90.
    s = estimate(origin_avg=32.90, target_tier=3, known=TIER3, per_month=2.0)
    assert (s.monthly_full, s.monthly_half) == (0.0, 0.0)
    assert s.note == "already spending like a lower tier here"


def test_saving_never_exceeds_monthly_spend_at_the_merchant():
    # Refunds make a tier average negative, so the raw gap would exceed the bill.
    s = estimate(origin_avg=50.0, target_tier=1, known={1: [-5.0, -5.0, -5.0]}, per_month=3.0)
    assert s.monthly_full == 3.0 * 50.0


@pytest.mark.parametrize("n, first, last, expected", [
    (4, date(2026, 10, 1), date(2026, 10, 31), 4.0),   # one calendar month
    (2, date(2026, 10, 5), date(2026, 10, 6), 2.0),    # short span counts as one month
    (8, date(2026, 10, 1), date(2026, 11, 30), 4.06),  # 60 days
])
def test_visits_per_month(n, first, last, expected):
    assert visits_per_month(n, first, last) == expected

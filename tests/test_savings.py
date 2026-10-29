from datetime import date

import pytest

from app.savings import FALLBACK_AVG, estimate, tier_avg, visits_per_month


def test_uses_users_own_average_with_enough_bills():
    assert tier_avg(4, {4: [200.0, 220.0, 240.0]}) == (220.0, False)


def test_falls_back_with_fewer_than_three_bills():
    assert tier_avg(4, {4: [200.0, 220.0]}) == (FALLBACK_AVG[4], True)


def test_monthly_saving_formula():
    known = {4: [200.0, 220.0, 240.0], 3: [60.0, 70.0, 80.0]}
    s = estimate(origin_tier=4, target_tier=3, known=known, per_month=4.0)
    assert s.monthly_usd == 4.0 * (220.0 - 70.0)
    assert s.estimate is False


def test_any_fallback_tier_marks_estimate():
    s = estimate(origin_tier=4, target_tier=3, known={4: [200.0, 220.0, 240.0]}, per_month=2.0)
    assert s.estimate is True
    assert s.monthly_usd == 2.0 * (220.0 - FALLBACK_AVG[3])


def test_inverted_averages_claim_no_saving():
    known = {3: [40.0, 40.0, 40.0], 2: [60.0, 60.0, 60.0]}
    s = estimate(origin_tier=3, target_tier=2, known=known, per_month=5.0)
    assert s.monthly_usd == 0.0
    assert "no saving claimed" in s.note


@pytest.mark.parametrize("n, first, last, expected", [
    (4, date(2026, 10, 1), date(2026, 10, 31), 4.0),   # one calendar month
    (2, date(2026, 10, 5), date(2026, 10, 6), 2.0),    # short span counts as one month
    (8, date(2026, 10, 1), date(2026, 11, 30), 4.06),  # 60 days
])
def test_visits_per_month(n, first, last, expected):
    assert visits_per_month(n, first, last) == expected

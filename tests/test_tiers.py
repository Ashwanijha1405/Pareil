import pytest

from app.tiers import assign, known_amounts


def test_qloo_price_level_wins_over_spend():
    info = assign(4, merchant_avg=10.0, known={1: [10.0], 2: [25.0]})
    assert (info.tier, info.source) == (4, "qloo")


def test_inferred_tier_is_nearest_on_log_scale():
    # ln(40) is 0.41 from ln(60) but 1.20 from ln(12): tier 3, although 40 is numerically closer to the midpoint.
    info = assign(None, merchant_avg=40.0, known={1: [12.0], 3: [60.0]})
    assert (info.tier, info.source) == (3, "inferred_from_user_spend")


def test_log_tie_goes_to_cheaper_tier():
    # 20 is the geometric mean of 10 and 40, so it is equally far from both.
    assert assign(None, merchant_avg=20.0, known={1: [10.0], 2: [40.0]}).tier == 1


def test_needs_two_known_tiers_to_infer_from_spend():
    info = assign(None, merchant_avg=200.0, known={1: [12.0, 14.0]})
    assert info.source == "inferred_fixed_bands"


@pytest.mark.parametrize("avg, tier", [(8.0, 1), (15.0, 1), (15.01, 2), (35.0, 2), (75.0, 3), (75.5, 4), (300.0, 4)])
def test_fixed_bands(avg, tier):
    assert assign(None, merchant_avg=avg, known={}).tier == tier


def test_known_amounts_ignores_merchants_without_qloo_tier():
    known = known_amounts(
        {"carbone": [200.0, 220.0], "joes": [9.0], "mystery": [50.0]},
        {"carbone": 4, "joes": 1, "mystery": None},
    )
    assert known == {4: [200.0, 220.0], 1: [9.0]}

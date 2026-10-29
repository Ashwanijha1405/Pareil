from app.agent import SignalState, offered_actions

OTHERS = ["a", "b", "c", "d"]


def state(**kw):
    return SignalState(extras=["a", "b"], **kw)


def test_mostly_rating_offers_only_give_up():
    actions, cause = offered_actions({"rating_below_floor": 38, "no_shared_specific_tag": 2}, 20, state(), OTHERS, 3)
    assert (actions, cause) == (["give_up"], "rating")


def test_mostly_no_shared_tag_offers_broaden_and_widen():
    actions, cause = offered_actions({"no_shared_specific_tag": 12, "rating_below_floor": 5}, 20, state(), OTHERS, 4)
    assert (actions, cause) == (["broaden_signal", "widen_tags", "give_up"], "cuisine")


def test_used_up_actions_are_not_offered_again():
    s = state(tags=("x",))  # bars already allowed
    s.extras = list(OTHERS)  # no more places to add
    actions, _ = offered_actions({"no_shared_specific_tag": 12}, 20, s, OTHERS, 4)
    assert actions == ["give_up"]


def test_thin_supply_one_tier_down_offers_two_tiers_down():
    actions, cause = offered_actions({"already_visited": 1}, 1, state(), OTHERS, 3)
    assert (actions, cause) == (["allow_two_tiers_down", "give_up"], "thin_supply")


def test_two_tiers_down_needs_a_tier_to_exist_and_is_offered_once():
    assert offered_actions({}, 0, state(), OTHERS, 2)[0] == ["give_up"]  # tier 2 - 2 = 0
    assert offered_actions({}, 0, state(two_tiers_down=True), OTHERS, 4)[0] == ["give_up"]


def test_exactly_half_is_not_mostly():
    actions, cause = offered_actions({"rating_below_floor": 5, "no_shared_specific_tag": 5}, 20, state(), OTHERS, 3)
    assert cause != "rating" and "give_up" in actions

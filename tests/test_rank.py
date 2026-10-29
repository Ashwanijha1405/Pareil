from app.models import Place, Twin
from app.rank import drop_reasons, pick, rating_floor

ORIGIN = Place(entity_id="origin", name="Carbone New York", price_level=4, business_rating=4.3)


def twin(eid, name, rating, affinity=0.95, price=3):
    return Twin(entity_id=eid, name=name, business_rating=rating, affinity=affinity, price_level=price)


def test_score_is_affinity_times_rating_over_five():
    [only] = pick(ORIGIN, [twin("a", "Pylos", 4.5, affinity=0.96)], floor=4.3)
    assert only.score == round(0.96 * 4.5 / 5, 4)


def test_filters_origin_visited_same_brand_unrated_and_below_floor():
    twins = [
        twin("origin", "Carbone New York", 4.9),
        twin("visited", "Au Cheval", 4.9),
        twin("branch", "Carbone Uptown", 4.9),
        twin("unrated", "Mystery", None),
        twin("low", "Meh Place", 4.2),
        twin("good", "Pylos", 4.6),
    ]
    picks = pick(ORIGIN, twins, floor=4.3, exclude_ids={"visited"})
    assert [p.entity_id for p in picks] == ["good"]
    assert drop_reasons(ORIGIN, twins, 4.3, {"visited"}) == {
        "is_origin": 1, "already_visited": 1, "same_brand": 1, "no_rating": 1, "rating_below_floor": 1,
    }


def test_rating_equal_to_floor_is_kept():
    assert len(pick(ORIGIN, [twin("a", "Pylos", 4.3)], floor=4.3)) == 1


def test_order_is_by_score_then_entity_id():
    twins = [twin("b", "B", 4.5), twin("a", "A", 4.5), twin("c", "C", 4.8)]
    assert [p.entity_id for p in pick(ORIGIN, twins, floor=4.0)] == ["c", "a", "b"]


def test_returns_at_most_n():
    twins = [twin(str(i), f"Place {i}", 4.5) for i in range(6)]
    assert len(pick(ORIGIN, twins, floor=4.0, n=3)) == 3


def test_floor_defaults_to_4_and_relaxes_by_0_2():
    assert rating_floor(ORIGIN) == 4.3
    assert rating_floor(ORIGIN, relaxed_steps=1) == 4.1
    assert rating_floor(Place(entity_id="x", name="No rating")) == 4.0

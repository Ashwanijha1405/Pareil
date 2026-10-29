from app.models import Place, Tag, Twin
from app.rank import concepts, dedupe, drop_reasons, is_nightlife_only, pick, rating_floor, specific_concepts


def tags(*ids):
    return [Tag(id=i) for i in ids]


def cuisine(*names):
    return tags(*(f"urn:tag:cuisine:qloo:{n}" for n in names))


ORIGIN = Place(entity_id="origin", name="Carbone New York", price_level=4, business_rating=4.3,
               tags=cuisine("italian", "fine_dining"))


def twin(eid, name, rating, concepts_=("italian",), price=3, affinity=0.95, extra_tags=()):
    return Twin(entity_id=eid, name=name, business_rating=rating, affinity=affinity, price_level=price,
                tags=cuisine(*concepts_) + tags(*extra_tags))


def test_concepts_merge_tag_families_and_drop_generic():
    p = Place(entity_id="x", name="X", tags=tags(
        "urn:tag:cuisine:qloo:italian",
        "urn:tag:genre:place:restaurant:italian",
        "urn:tag:category:place:pizza_restaurant",
        "urn:tag:genre:place:restaurant",          # generic: on every place
        "urn:tag:category:place:restaurant",       # generic
        "urn:tag:cuisine:qloo:seafood",            # generic in NYC data
        "urn:tag:offerings:place:beer",            # not a concept family
    ))
    assert concepts(p) == {"italian", "pizza"}


def test_score_is_rating_times_tag_overlap():
    # origin {italian, fine_dining}, twin {italian}: jaccard 1/2
    [only] = pick(ORIGIN, [twin("a", "Pylos", 4.5)], floor=4.3)
    assert only.jaccard == 0.5
    assert only.score == round(4.5 / 5 * (0.5 + 0.5 * 0.5), 4)
    assert only.shared == ["italian"]


def test_full_overlap_beats_higher_rating_with_partial_overlap():
    full = twin("full", "Full", 4.4, concepts_=("italian", "fine_dining"))  # 0.88 * 1.0  = 0.88
    partial = twin("part", "Partial", 4.8, concepts_=("italian",))         # 0.96 * 0.75 = 0.72
    assert [p.entity_id for p in pick(ORIGIN, [partial, full], floor=4.3)] == ["full", "part"]


def test_vibe_check_rejects_twin_without_shared_cuisine():
    ramen = twin("r", "Ivan Ramen", 4.7, concepts_=("japanese", "ramen"))
    only_generic = twin("g", "Generic", 4.7, concepts_=("seafood",))
    assert pick(ORIGIN, [ramen, only_generic], floor=4.3) == []
    assert drop_reasons(ORIGIN, [ramen, only_generic], 4.3) == {"no_shared_specific_tag": 2}


def test_broad_tag_alone_does_not_pass_vibe_check():
    # Katz's vs Murray's Cheese in the sample: both "american", nothing more specific.
    katz = Place(entity_id="k", name="Katz's", business_rating=4.5, tags=cuisine("american", "deli", "jewish"))
    cheese = twin("m", "Murray's Cheese", 4.6, concepts_=("american",))
    deli = twin("r", "Russ & Daughters", 4.6, concepts_=("american", "deli", "jewish"))
    assert specific_concepts(cheese) == set()
    assert [p.entity_id for p in pick(katz, [cheese, deli], floor=4.5)] == ["r"]
    assert drop_reasons(katz, [cheese, deli], 4.5) == {"no_shared_specific_tag": 1}


def test_broad_tags_still_count_toward_overlap_score():
    katz = Place(entity_id="k", name="Katz's", business_rating=4.5, tags=cuisine("american", "deli", "jewish"))
    [deli] = pick(katz, [twin("r", "Russ", 4.6, concepts_=("american", "deli"))], floor=4.5)
    assert deli.jaccard == round(2 / 3, 3)


def test_nightlife_only_twin_rejected_unless_allowed():
    bar = twin("bar", "Wine Bar", 4.6, concepts_=("wine_bar",))
    assert is_nightlife_only(bar)
    assert drop_reasons(ORIGIN, [bar], 4.3) == {"nightlife_only": 1}
    # Allowed past the nightlife rule, it still has to share a cuisine.
    assert drop_reasons(ORIGIN, [bar], 4.3, allow_nightlife=True) == {"no_shared_specific_tag": 1}


def test_bar_that_serves_the_same_cuisine_is_not_nightlife_only():
    trattoria_bar = twin("tb", "Italian Wine Bar", 4.6, concepts_=("wine_bar", "italian"))
    assert not is_nightlife_only(trattoria_bar)
    assert len(pick(ORIGIN, [trattoria_bar], floor=4.3)) == 1


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


def test_rating_equal_to_floor_is_kept_and_floor_never_below_origin():
    assert len(pick(ORIGIN, [twin("a", "Pylos", 4.3)], floor=rating_floor(ORIGIN))) == 1
    assert rating_floor(ORIGIN) == 4.3
    assert rating_floor(Place(entity_id="x", name="No rating")) == 4.0


def test_order_is_by_score_then_entity_id_and_cut_to_n():
    twins = [twin(i, f"Place {i}", 4.5) for i in ("d", "b", "a", "c")]
    assert [p.entity_id for p in pick(ORIGIN, twins, floor=4.0)] == ["a", "b", "c"]
    assert len(pick(ORIGIN, twins, floor=4.0, n=None)) == 4


def test_tiers_down_is_origin_minus_twin_price():
    [p] = pick(ORIGIN, [twin("a", "Pylos", 4.5, price=2)], floor=4.3)
    assert p.tiers_down == 2


def ranked(eid, score):
    return pick(Place(entity_id="o", name="O", business_rating=1.0, tags=cuisine("italian")),
                [twin(eid, eid, 5.0)], floor=1.0)[0].model_copy(update={"score": score})


def test_dedupe_gives_each_twin_to_its_highest_score():
    first = [ranked("pylos", 0.80), ranked("ci_siamo", 0.79)]
    second = [ranked("pylos", 0.85), ranked("joseph", 0.70)]
    out = dedupe([first, second])
    assert [t.entity_id for t in out[0]] == ["ci_siamo"]
    assert [t.entity_id for t in out[1]] == ["pylos", "joseph"]


def test_dedupe_tie_goes_to_earlier_merchant_and_cuts_to_n():
    first = [ranked("pylos", 0.8), ranked("a", 0.7), ranked("b", 0.6), ranked("c", 0.5)]
    second = [ranked("pylos", 0.8)]
    out = dedupe([first, second], n=3)
    assert [t.entity_id for t in out[0]] == ["pylos", "a", "b"]
    assert out[1] == []

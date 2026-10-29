from app.models import CleanMerchant
from app.resolve import pick

FOOD = [{"id": "urn:tag:genre:place:restaurant"}]


def result(eid, name):
    return {"entity_id": eid, "name": name, "properties": {"price_level": 3}, "tags": FOOD}


def merchant(name, raw=None):
    return CleanMerchant(raw=raw or name.upper(), name=name, category="restaurant", city="Bengaluru")


LEONS = [result("hsr", "Leon's Burgers & Wings HSR Layout"), result("kal", "Leon's Burgers & Wings Kalyan Nagar"),
         result("kor", "Leon's Burgers & Wings Koramangala")]


def test_location_suffixed_branches_are_one_place_not_ambiguous():
    r = pick(merchant("Leon's Burgers & Wings", raw="LEONS BURGERS AND WINGS"), LEONS)
    assert r.status == "resolved"
    assert r.place.entity_id == "hsr"  # Qloo's first
    assert "3 branches" in r.branch_note


def test_branch_named_in_the_bank_string_wins():
    r = pick(merchant("Leon's Burgers & Wings", raw="LEONS BURGERS KORAMANGALA"), LEONS)
    assert r.place.entity_id == "kor"
    assert "matched the bank string" in r.branch_note


def test_one_word_generic_name_is_still_ambiguous():
    results = [result("a", "Joe's"), result("b", "Joe's Pizza"), result("c", "Joe's Shanghai")]
    r = pick(merchant("Joe's"), results)
    assert r.status == "needs_review" and r.reason.startswith("generic name")


def test_different_places_close_in_score_are_ambiguous():
    results = [result("a", "Thai Basil Cafe"), result("b", "Thai Basil Kitchen")]
    r = pick(merchant("Thai Basil House"), results)
    assert r.status == "needs_review" and r.reason.startswith("ambiguous")


def test_non_food_results_are_ignored():
    shop = {"entity_id": "x", "name": "Carbone Memorials", "properties": {}, "tags": [{"id": "urn:tag:category:place:store"}]}
    r = pick(merchant("Carbone"), [shop])
    assert r.status == "needs_review" and "none tagged as food" in r.reason


def test_ampersand_and_the_word_and_match():
    # The LLM cleaned "LEONS BURGERS AND WINGS"; Qloo writes "&".
    r = pick(merchant("Leon's Burgers and Wings", raw="LEONS BURGERS AND WINGS KORAMANGALA"), LEONS)
    assert r.status == "resolved" and r.place.entity_id == "kor"

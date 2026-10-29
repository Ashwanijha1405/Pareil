from app.agent import Agent

ALLOWED = {"ARAKU Coffee", "Third Wave Coffee"}
EVERY = ALLOWED | {"Popeyes", "Momos Under The Tree"}


def check(text, cuisine=("Coffee Shop", "Cafe")):
    return Agent._check_text(text, ALLOWED, EVERY, cuisine)


def test_place_names_and_cuisine_labels_may_contain_banned_words():
    assert check("Your [[ARAKU Coffee]] visits drive this one (35%). [[Third Wave Coffee]] is a cheaper Coffee Shop.") == ""


def test_generic_offering_words_are_rejected():
    assert "generic word 'wine'" in check("Your [[ARAKU Coffee]] visits drive this one (35%), and it has great wine.")


def test_unknown_bracketed_place_is_rejected():
    assert "did not return" in check("Like [[Blue Tokai]], it is a cheaper Cafe.")


def test_other_known_place_without_brackets_is_rejected():
    assert "not part of this pick" in check("Your Popeyes visits drive this one (35%). A cheaper Cafe.")

from app.models import Place


def raw(images):
    return {"entity_id": "e1", "name": "Ci Siamo", "properties": {"images": images}}


def test_place_takes_first_qloo_photo():
    url = "https://images.qloo.com/i/ABC-420x-outside.jpg"
    assert Place.from_qloo(raw([{"url": url, "type": "urn:image:place:unknown"}])).image == url


def test_place_ignores_photos_from_other_hosts():
    assert Place.from_qloo(raw([{"url": "https://example.com/x.jpg"}])).image == ""


def test_place_without_photos_has_empty_image():
    assert Place.from_qloo(raw(None)).image == ""
    assert Place.from_qloo({"entity_id": "e1", "name": "X"}).image == ""

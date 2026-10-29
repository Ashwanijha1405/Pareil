"""Probe what price/rating data Qloo returns for places (Bengaluru vs NYC).

Run from the repo root:  .venv/Scripts/python scripts/price_test.py
Raw responses are written to qloo_raw/ (gitignored).
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "qloo_raw"

PRICE_RE = re.compile(r"price|cost|budget", re.I)
RATING_RE = re.compile(r"rating|star|review|michelin|resy|tripadvisor", re.I)
ADDRESS_RE = re.compile(r"address|city", re.I)

BLR_POINT = "12.9716,77.5946"
NYC_POINT = "40.7279,-74.0003"

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(REPO / ".env")
API_KEY = os.getenv("QLOO_API_KEY", "")
BASE_URL = os.getenv("QLOO_BASE_URL", "").rstrip("/")
if not API_KEY or API_KEY == "your_qloo_key_here" or not BASE_URL:
    sys.exit("Set QLOO_API_KEY and QLOO_BASE_URL in .env first.")


def call(test_name, path, params):
    """GET a Qloo endpoint, print the status, save the raw body. Returns parsed JSON or None."""
    resp = requests.get(
        BASE_URL + path, params=params, headers={"X-Api-Key": API_KEY}, timeout=30
    )
    print(f"\n[{test_name}] GET {path} -> HTTP {resp.status_code}")
    RAW_DIR.mkdir(exist_ok=True)
    try:
        body = resp.json()
    except ValueError:
        body = {"_non_json_body": resp.text[:2000]}
    (RAW_DIR / f"{test_name}.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
    if not resp.ok:
        print(f"  error body: {json.dumps(body)[:500]}")
        return None
    return body


def walk(obj, prefix=""):
    """Yield (dotted_path, value) for every leaf in a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        for i, v in enumerate(obj):
            yield from walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def matching(entity, pattern):
    return {p: v for p, v in walk(entity.get("properties", {})) if pattern.search(p)}


def price_level(entity):
    return entity.get("properties", {}).get("price_level")


def short(value, n=60):
    s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return s if len(s) <= n else s[: n - 3] + "..."


def search(test_name, query, point):
    body = call(test_name, "/search", {
        "query": query, "types": "urn:entity:place", "filter.location": point, "take": 5,
    })
    results = (body or {}).get("results", [])
    for i, r in enumerate(results, 1):
        addr = r.get("properties", {}).get("address", "")
        print(f"  {i}. {r.get('name')} | {short(addr, 70)} | id={r.get('entity_id')}")
    if not results:
        print("  no results")
    return results[0] if results else None


def details(test_name, entity):
    body = call(test_name, "/entities", {"entity_ids": entity["entity_id"]})
    results = (body or {}).get("results", [])
    if not results:
        print("  no entity returned")
        return None
    full = results[0]
    print(f"  top-level keys: {sorted(full.keys())}")
    paths = [p for p, _ in walk(full.get("properties", {}))]
    print(f"  properties key paths ({len(paths)}):")
    for p in paths:
        print(f"    {p}")
    for label, pattern in (("PRICE", PRICE_RE), ("RATING", RATING_RE)):
        hits = matching(full, pattern)
        print(f"  >>> {label}-related: " + (", ".join(f"{p}={short(v, 40)}" for p, v in hits.items()) or "NONE"))
    return full


def insights(test_name, signal_id, locality, extra=None):
    params = {
        "filter.type": "urn:entity:place",
        "signal.interests.entities": signal_id,
        "filter.location.query": locality,
        "feature.explainability": "true",
        "take": 20,
    }
    params.update(extra or {})
    body = call(test_name, "/v2/insights", params)
    entities = ((body or {}).get("results") or {}).get("entities", [])
    print(f"  {len(entities)} results")
    for i, e in enumerate(entities, 1):
        addr = matching(e, ADDRESS_RE)
        price = matching(e, PRICE_RE)
        rating = matching(e, RATING_RE)
        print(f"  {i:2}. {e.get('name')}")
        print(f"      where:  {short(addr, 110) if addr else '-'}")
        print(f"      price:  {short(price, 110) if price else '-'}")
        print(f"      rating: {short(rating, 110) if rating else '-'}")
        print(f"      affinity: {(e.get('query') or {}).get('affinity')}")
    return entities


def coverage(label, entities):
    n = len(entities)
    # price_range is always {from: null, to: null} for restaurants, so only price_level counts.
    with_price = sum(1 for e in entities if price_level(e) is not None)
    with_rating = sum(1 for e in entities if matching(e, RATING_RE))
    food = sum(
        1 for e in entities
        if any(re.search(r"restaurant|food|cafe|bar|bakery|dining", t.get("id", "") + t.get("name", ""), re.I)
               for t in e.get("tags", []) if isinstance(t, dict))
    )
    levels = sorted({price_level(e) for e in entities if price_level(e) is not None})
    pct = f"{100 * with_price / n:.0f}%" if n else "n/a"
    print(f"\n  == {label}: {n} results | price field {with_price}/{n} ({pct}) | "
          f"rating field {with_rating}/{n} | food-tagged {food}/{n} | price_level values {levels}")
    return {"label": label, "n": n, "price": with_price, "rating": with_rating, "food": food, "levels": levels}


def compare_filtered(label, base, filtered, max_level):
    base_ids = {e.get("entity_id") for e in base}
    filt_ids = {e.get("entity_id") for e in filtered}
    levels = [price_level(e) for e in filtered]
    violations = [lv for lv in levels if lv is not None and lv > max_level]
    print(f"\n  == {label}: {len(filtered)} results, overlap with unfiltered {len(base_ids & filt_ids)}, "
          f"price_level values {levels}, violations of max={max_level}: {len(violations)}, "
          f"missing price_level: {levels.count(None)}")


def main():
    summary = []

    print("=" * 70, "\nTEST A: what Qloo knows about a place (Bengaluru)")
    popeyes = search("A1_search_popeyes_blr", "Popeyes", BLR_POINT)
    premium = search("A2_search_smokehousedeli_blr", "Smoke House Deli", BLR_POINT)
    if popeyes:
        details("A3_entity_popeyes_blr", popeyes)
    if premium:
        premium_full = details("A4_entity_smokehousedeli_blr", premium)

    if popeyes:
        print("=" * 70, "\nTEST B: taste twins of Popeyes in Bengaluru")
        b = insights("B_insights_popeyes_blr", popeyes["entity_id"], "Bengaluru")
        summary.append(coverage("BLR / Popeyes signal", b))

        print("=" * 70, "\nTEST C1: Test B with filter.price_level.max=2")
        c1 = insights("C1_insights_popeyes_blr_pricemax2", popeyes["entity_id"], "Bengaluru",
                      {"filter.price_level.max": 2})
        compare_filtered("C1 vs B", b, c1, 2)

    if premium:
        print("=" * 70, "\nTEST C2: premium signal, unfiltered vs cheaper")
        c2 = insights("C2a_insights_smokehousedeli_blr", premium["entity_id"], "Bengaluru")
        summary.append(coverage("BLR / Smoke House Deli signal", c2))
        own = price_level(premium_full or premium)
        cap = (own - 1) if isinstance(own, int) and own > 1 else 2
        print(f"\n  Smoke House Deli price_level = {own}; filtering to max {cap}")
        c2b = insights("C2b_insights_smokehousedeli_blr_cheaper", premium["entity_id"], "Bengaluru",
                       {"filter.price_level.max": cap})
        compare_filtered("C2b vs C2a", c2, c2b, cap)

    print("=" * 70, "\nTEST D: coverage comparison (New York)")
    carbone = search("D1_search_carbone_nyc", "Carbone", NYC_POINT)
    if carbone:
        carbone_full = details("D2_entity_carbone_nyc", carbone)
        d = insights("D3_insights_carbone_nyc", carbone["entity_id"], "New York")
        summary.append(coverage("NYC / Carbone signal", d))
        own = price_level(carbone_full or carbone)
        cap = (own - 1) if isinstance(own, int) and own > 1 else 2
        print(f"\n  Carbone price_level = {own}; filtering to max {cap}")
        d4 = insights("D4_insights_carbone_nyc_cheaper", carbone["entity_id"], "New York",
                      {"filter.price_level.max": cap})
        compare_filtered("D4 vs D3", d, d4, cap)

    print("=" * 70, "\nSUMMARY")
    for s in summary:
        pct = f"{100 * s['price'] / s['n']:.0f}%" if s["n"] else "n/a"
        print(f"  {s['label']:32} results={s['n']:2}  price={s['price']}/{s['n']} ({pct})  "
              f"rating={s['rating']}/{s['n']}  food={s['food']}/{s['n']}  levels={s['levels']}")


if __name__ == "__main__":
    main()

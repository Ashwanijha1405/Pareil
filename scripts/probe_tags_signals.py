"""Probe filter.tags (food-only twins) and multi-entity / weighted signals.

Run from the repo root:  .venv/Scripts/python scripts/probe_tags_signals.py
Reuses the GET helper from price_test.py; raw responses go to qloo_raw/.
"""

import json

import requests

from price_test import API_KEY, BASE_URL, NYC_POINT, RAW_DIR, call, search

FOOD_TAGS = [
    "urn:tag:genre:place:restaurant",
    "urn:tag:category:place:cafe",
    "urn:tag:category:place:bakery",
]
SMOKE_HOUSE_DELI_BLR = "9B125C66-0074-4719-A7AA-A15348C672BA"


def post_insights(test_name, body):
    resp = requests.post(
        BASE_URL + "/v2/insights", json=body, headers={"X-Api-Key": API_KEY}, timeout=30
    )
    print(f"\n[{test_name}] POST /v2/insights -> HTTP {resp.status_code}")
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"_text": resp.text[:2000]}
    (RAW_DIR / f"{test_name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    if not resp.ok:
        print(f"  error body: {json.dumps(data)[:500]}")
        return None
    return data


def entities_of(body):
    return ((body or {}).get("results") or {}).get("entities", [])


def report_tags(label, body):
    ents = entities_of(body)
    on_tag = 0
    for e in ents:
        ids = {t.get("id") for t in e.get("tags", [])}
        hit = sorted(ids & set(FOOD_TAGS))
        on_tag += bool(hit)
        cats = [t["name"] for t in e.get("tags", []) if t.get("type") == "urn:tag:category:place"][:2]
        print(f"   {e['name'][:40]:40} pl={e['properties'].get('price_level')} {cats} matched={hit or 'NONE'}")
    print(f"  == {label}: {len(ents)} results, {on_tag}/{len(ents)} carry a filter tag")


def report_signals(label, body, names, baseline_ids=None):
    ents = entities_of(body)
    per_result = {i: 0 for i in names}
    for e in ents:
        for row in (e.get("query") or {}).get("explainability", {}).get("signal.interests.entities", []):
            if row.get("entity_id") in per_result:
                per_result[row["entity_id"]] += 1
    print(f"  == {label}: {len(ents)} results")
    for eid, n in per_result.items():
        print(f"     {names[eid]:24} attributed in {n}/{len(ents)} results")
    agg = ((body or {}).get("query") or {}).get("explainability", {}).get("signal.interests.entities", {})
    for bucket in ("effect_on_top3_recs", "effect_on_top10_recs"):
        rows = {names.get(r["entity_id"], r["entity_id"]): round(r["avg_score"], 3) for r in agg.get(bucket, [])}
        print(f"     {bucket}: {rows}")
    if baseline_ids is not None:
        ids = {e["entity_id"] for e in ents}
        print(f"     overlap with Carbone-only (D3): {len(ids & baseline_ids)}/{len(ents)}")
    for e in ents[:5]:
        print(f"     - {e['name'][:40]:40} pl={e['properties'].get('price_level')} aff={e['query']['affinity']:.3f}")
    return {e["entity_id"] for e in ents}


def main():
    print("=" * 70, "\nTAG TEST: Smoke House Deli (BLR) twins with food tags")
    base = {
        "filter.type": "urn:entity:place",
        "signal.interests.entities": SMOKE_HOUSE_DELI_BLR,
        "filter.location.query": "Bengaluru",
        "filter.tags": ",".join(FOOD_TAGS),
        "feature.explainability": "true",
        "take": 20,
    }
    report_tags("T1 tags only", call("T1_tags_smokehousedeli_blr", "/v2/insights", base))
    report_tags("T2 tags + price_level.max=2",
                call("T2_tags_price2_smokehousedeli_blr", "/v2/insights", {**base, "filter.price_level.max": 2}))

    print("=" * 70, "\nSIGNAL TEST: Carbone + two other NYC places")
    d3 = json.loads((RAW_DIR / "D3_insights_carbone_nyc.json").read_text(encoding="utf-8"))
    carbone_id = d3["query"]["explainability"]["signal.interests.entities"]["effect_on_top3_recs"][0]["entity_id"]
    joes = search("S0a_search_joes_pizza_nyc", "Joe's Pizza", NYC_POINT)
    katz = search("S0b_search_katz_nyc", "Katz's Delicatessen", NYC_POINT)
    if not (joes and katz):
        print("  could not resolve both extra signals; stopping")
        return
    names = {carbone_id: "Carbone", joes["entity_id"]: joes["name"][:24], katz["entity_id"]: katz["name"][:24]}
    baseline = {e["entity_id"] for e in d3["results"]["entities"]}

    s1 = call("S1_multisignal_get_nyc", "/v2/insights", {
        "filter.type": "urn:entity:place",
        "signal.interests.entities": ",".join(names),
        "filter.location.query": "New York",
        "feature.explainability": "true",
        "take": 20,
    })
    if s1:
        report_signals("S1 GET, 3 signals, equal weight", s1, names, baseline)

    # The docs example uses {"entity": ..., "weight": ...}; the API rejects that with 400
    # ("objects with an id property"), so the key is "id".
    s2 = post_insights("S2b_multisignal_post_weighted_id_nyc", {
        "filter.type": "urn:entity:place",
        "signal.interests.entities": [
            {"id": carbone_id, "weight": 3},
            {"id": joes["entity_id"], "weight": 1},
            {"id": katz["entity_id"], "weight": 1},
        ],
        "filter.location.query": "New York",
        "feature.explainability": True,
        "take": 20,
    })
    if s2:
        report_signals("S2 POST, weights 3/1/1", s2, names, baseline)


if __name__ == "__main__":
    main()

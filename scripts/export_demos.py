"""Write the trimmed demo reports the static frontend plays back: static/demo/{nyc,blr}.json.

    python scripts/export_demos.py              # run both demos live now (Qloo + LLM calls), then trim
    python scripts/export_demos.py --from DIR   # trim reports already saved as DIR/nyc.json, DIR/blr.json

Only fields the UI displays are kept (whitelist below): names, tiers, ratings, shared tags,
explainability %, savings and trace step summaries. No raw Qloo payloads, entity ids or tag ids.
Qloo photos stay as URLs (hot-linked); no image file is ever downloaded.
Re-run after any change to the engine so the recorded demos match the live code.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = REPO / "static" / "demo"
DEMOS = {"nyc": ("data/sample_transactions.csv", "NYC demo"), "blr": ("data/sample_bengaluru.csv", "Bengaluru demo")}

SUMMARY = ("transactions", "food_merchants", "swaps", "monthly_saving_half", "monthly_saving_full",
           "saving_is_estimate", "qloo_calls")
SWAP = ("merchant", "qloo_name", "visits", "avg_bill", "tier", "rating", "kind", "image")
PICK = ("name", "address", "image", "price_level", "tiers_down", "label", "rating", "shared", "why")
SAVING = ("monthly_half", "monthly_full", "estimate")
BUDGET = ("merchant", "qloo_name", "visits", "avg_bill", "tier", "image")
WHERE = ("name", "visits", "avg_bill", "status", "note", "reason")
STEP = ("step", "tool", "target", "status", "ms", "detail")
# Request parameters shown in the "How we know" panel; signals keep name and weight only.
META = ("endpoint", "query", "filter.location", "filter.location.query", "filter.price_level.max", "filter.tags",
        "feature.explainability")


def keep(d: dict, fields) -> dict:
    return {k: d[k] for k in fields if k in d}


def pick(p: dict) -> dict:
    return {**keep(p, PICK), "drivers": [keep(x, ("place", "percent")) for x in p.get("drivers") or []]}


def step(t: dict) -> dict:
    out = keep(t, STEP)
    meta = t.get("meta") or {}
    if meta.get("endpoint"):
        out["meta"] = {**keep(meta, META),
                       "signals": [keep(s, ("name", "weight")) for s in meta.get("signals") or []]}
    return out


def trim(report: dict) -> dict:
    return {
        "source": report["source"], "ran_at": report["ran_at"], "replayed_at": report["ran_at"], "live": False,
        "period": keep(report["period"], ("first", "last")),
        "currency": report["currency"], "symbol": report["symbol"],
        "summary": keep(report["summary"], SUMMARY),
        "swaps": [{**keep(s, SWAP), "saving": keep(s.get("saving") or {}, SAVING),
                   "picks": [pick(p) for p in s["picks"]], "alternates": [pick(p) for p in s.get("alternates", [])]}
                  for s in report["swaps"]],
        "already_budget": [keep(a, BUDGET) for a in report["already_budget"]],
        "where_you_spent": [keep(w, WHERE) for w in report["where_you_spent"]],
        "skipped": [{} for _ in report["skipped"]],  # the UI shows only the count; names are in where_you_spent
        "trace": [step(t) for t in report["trace"]],
    }


def run_live(demo: str) -> dict:
    from app.agent import Agent
    from app.config import load_settings
    from app.ingest import parse_csv

    path, label = DEMOS[demo]
    txns = parse_csv((REPO / path).read_text(encoding="utf-8"))
    report = Agent(load_settings()).run(txns)
    report.update({"source": f"{label} · {len(txns)} transactions",
                   "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="src", type=Path, help="directory holding saved full reports (nyc.json, blr.json)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for demo in DEMOS:
        report = json.loads((args.src / f"{demo}.json").read_text(encoding="utf-8")) if args.src else run_live(demo)
        out = OUT / f"{demo}.json"
        out.write_text(json.dumps(trim(report), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{out.relative_to(REPO)}: recorded {report['ran_at']}, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

"""python -m app.cli data/sample_transactions.csv [--out report.json]"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.agent import Agent
from app.config import load_settings
from app.models import Transaction

TIER_SIGNS = {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}


def load_transactions(path: Path) -> list[Transaction]:
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            try:
                rows.append(Transaction.model_validate(row))
            except ValidationError as exc:
                raise SystemExit(f"{path}:{i}: bad row: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}")
    if not rows:
        raise SystemExit(f"{path}: no transactions")
    return rows


def print_report(r: dict) -> None:
    s = r["summary"]
    est = " (estimate)" if s["saving_is_estimate"] else ""
    print(f"\nPareil report  {r['period']['first']} -> {r['period']['last']}")
    print(f"{s['transactions']} transactions, {s['food_merchants']} food merchants, "
          f"{s['qloo_calls']} Qloo calls, LLM {'on' if s['llm_enabled'] else 'off'}")
    print(f"Estimated monthly saving: ${s['total_monthly_saving_usd']:.2f}{est}\n")

    for sw in r["swaps"]:
        flags = [f"tier from {sw['tier_source']}"] if sw["tier_source"] != "qloo" else []
        flags += ["cleaned without LLM"] if sw["cleaned_by"] == "rules" else []
        print(f"== {sw['qloo_name']} {TIER_SIGNS[sw['tier']]}  {sw['visits']} visits, avg ${sw['avg_bill']:.2f}"
              + (f"  [{'; '.join(flags)}]" if flags else ""))
        print(f"   signals: {', '.join(sw['signals'])} | via {sw['twins_path']} | rating floor {sw['rating_floor']}")
        for d in sw["recovery"]:
            print(f"   recovery {d['iteration']}: {d['action']} ({d['decided_by']}): {d['reason']}")
        if not sw["picks"]:
            print("   no twin passed the filters")
        for p in sw["picks"]:
            print(f"   -> {p['name']} {TIER_SIGNS.get(p['price_level'], '?')}  rating {p['rating']}  "
                  f"affinity {p['affinity']}  score {p['score']}")
            print(f"      {p['why']}" + ("" if p["why_source"] == "llm" else "  [template]"))
        if sw["saving"]:
            sv = sw["saving"]
            print(f"   saving: {sv['visits_per_month']} visits/mo x (${sv['origin_avg']:.2f} - ${sv['target_avg']:.2f})"
                  f" = ${sv['monthly_usd']:.2f}/mo" + (" (estimate)" if sv["estimate"] else ""))
            if sv["note"]:
                print(f"           {sv['note']}")
        if sw["branch_note"]:
            print(f"   note: {sw['branch_note']}")
        print()

    if r["already_budget"]:
        print("Already budget-friendly: " + ", ".join(f"{a['qloo_name']} ({a['visits']}x)" for a in r["already_budget"]))
    if r["needs_review"]:
        print("Needs review:")
        for n in r["needs_review"]:
            print(f"   {n['merchant']} ({', '.join(n['raw'])}): {n['reason']}")
    if r["skipped"]:
        print("Skipped: " + ", ".join(sorted({s['name'] for s in r["skipped"]})) + " (non-food)")

    print("\nTrace:")
    for t in r["trace"]:
        print(f"   {t['step']:8} {t['tool']:30} {t['status']:24} {t['ms']:6}ms  {t['target'][:24]:24} {t['detail'][:90]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Find cheaper taste twins for the places you spend at.")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=Path("report.json"))
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    txns = load_transactions(args.csv)
    settings = load_settings()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "input": str(args.csv), "llm_model": settings.llm_model if settings.llm_enabled else None,
              **Agent(settings).run(txns)}
    args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print_report(report)
    print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()

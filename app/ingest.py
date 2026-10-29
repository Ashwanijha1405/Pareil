"""Parse a transactions CSV (from disk or an upload held in memory) into Transactions."""

import csv
import io

from pydantic import ValidationError

from app import currency
from app.models import Transaction

REQUIRED = ("date", "merchant", "amount", "city")
AMOUNT_ALIASES = {"amount": None, "amount_usd": "USD", "amount_inr": "INR"}


class IngestError(ValueError):
    pass


def parse_csv(text: str, max_rows: int | None = None) -> list[Transaction]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    amount_col = next((h for h in AMOUNT_ALIASES if h in headers), None)
    missing = [c for c in REQUIRED if c != "amount" and c not in headers] + ([] if amount_col else ["amount"])
    if missing:
        raise IngestError(f"missing column(s): {', '.join(missing)}. Expected: {', '.join(REQUIRED)} (optional: currency)")

    rows = []
    for line, raw in enumerate(reader, start=2):
        if max_rows is not None and len(rows) >= max_rows:
            raise IngestError(f"too many rows: the limit is {max_rows}")
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        code = (row.get("currency") or AMOUNT_ALIASES[amount_col] or currency.for_city(row.get("city", ""))).upper()
        if code not in currency.BY_CODE:
            raise IngestError(f"row {line}: currency must be one of {', '.join(currency.BY_CODE)}, got {code!r}")
        try:
            rows.append(Transaction(date=row.get("date"), merchant=row.get("merchant"), amount=row.get(amount_col),
                                    city=row.get("city"), currency=code))
        except ValidationError as exc:
            err = exc.errors()[0]
            raise IngestError(f"row {line}: {err['loc'][0]} {err['msg'].lower()}") from exc
    if not rows:
        raise IngestError("no transactions in the file")
    codes = {t.currency for t in rows}
    if len(codes) > 1:
        raise IngestError(f"one currency per file, found {', '.join(sorted(codes))}")
    return rows

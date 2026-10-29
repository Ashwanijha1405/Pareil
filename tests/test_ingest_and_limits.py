import pytest

from app.ingest import IngestError, parse_csv
from app.runs import RateLimiter

HEADER = "date,merchant,amount,city\n"


def test_currency_comes_from_the_city_and_is_never_converted():
    [t] = parse_csv(HEADER + "2026-10-01,ARAKU COFFEE,1180,Bengaluru\n")
    assert (t.currency, t.amount) == ("INR", 1180.0)
    [t] = parse_csv(HEADER + "2026-10-01,CARBONE,214.75,New York\n")
    assert (t.currency, t.amount) == ("USD", 214.75)


def test_legacy_amount_usd_header_is_accepted():
    [t] = parse_csv("date,merchant,amount_usd,city\n2026-10-01,CARBONE,10,New York\n")
    assert t.currency == "USD"


@pytest.mark.parametrize("text, message", [
    ("date,merchant,city\n2026-10-01,X,New York\n", "missing column(s): amount"),
    (HEADER + "2026-10-01,X,abc,New York\n", "row 2: amount"),
    (HEADER + "yesterday,X,5,New York\n", "row 2: date"),
    (HEADER + "2026-10-01,X,5,New York\n2026-10-02,Y,5,Bengaluru\n", "one currency per file"),
    (HEADER, "no transactions"),
])
def test_bad_files_get_a_clear_message(text, message):
    with pytest.raises(IngestError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_csv(text)


def test_row_limit():
    rows = "".join(f"2026-10-01,X{i},5,New York\n" for i in range(4))
    with pytest.raises(IngestError, match="limit is 3"):
        parse_csv(HEADER + rows, max_rows=3)


def test_rate_limiter_blocks_after_max_hits_per_ip():
    limiter = RateLimiter(max_hits=2, window_s=600)
    assert limiter.check("1.1.1.1") == 0 and limiter.check("1.1.1.1") == 0
    assert limiter.check("1.1.1.1") > 0       # third live run is refused
    assert limiter.check("2.2.2.2") == 0      # other IPs are unaffected

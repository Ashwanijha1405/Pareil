import re

from app.config import DEV_ORIGIN_REGEX, parse_origins
from app.runs import client_ip_from


def test_parse_origins_trims_and_drops_trailing_slash():
    assert parse_origins(" https://pareil.vercel.app/ , https://x.dev,,") == ["https://pareil.vercel.app", "https://x.dev"]
    assert parse_origins("") == []


def test_dev_origin_regex_allows_only_local_http():
    allowed = ["http://localhost:5500", "http://127.0.0.1:8000", "http://localhost"]
    blocked = ["https://localhost:5500", "http://localhost.evil.com", "http://evil.com/?http://localhost:1", "http://192.168.1.4:5500"]
    assert all(re.fullmatch(DEV_ORIGIN_REGEX, o) for o in allowed)
    assert not any(re.fullmatch(DEV_ORIGIN_REGEX, o) for o in blocked)


def test_client_ip_uses_the_proxy_appended_hop():
    assert client_ip_from("6.6.6.6, 203.0.113.9", "10.0.0.1") == "203.0.113.9"  # first entry forged by the client
    assert client_ip_from("203.0.113.9", "10.0.0.1") == "203.0.113.9"
    assert client_ip_from("", "10.0.0.1") == "10.0.0.1"

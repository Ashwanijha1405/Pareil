"""Per-currency constants. Amounts are never converted; a report uses the currency of its data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Currency:
    code: str
    symbol: str
    bands: tuple[tuple[float, int], ...]  # per-bill upper limits for tiers 1-3; above the last is tier 4
    fallback_avg: dict[int, float]  # per-bill average used when the user has too few bills at a tier


USD = Currency("USD", "$", ((15.0, 1), (35.0, 2), (75.0, 3)), {1: 12.0, 2: 25.0, 3: 55.0, 4: 110.0})
# INR values are estimates for Bengaluru restaurant bills, not data; reports using them are marked "estimate".
INR = Currency("INR", "₹", ((400.0, 1), (1000.0, 2), (2200.0, 3)), {1: 300.0, 2: 700.0, 3: 1500.0, 4: 3000.0})

BY_CODE = {"USD": USD, "INR": INR}
CITY_CURRENCY = {"bengaluru": "INR", "bangalore": "INR"}


def for_city(city: str) -> str:
    return CITY_CURRENCY.get(city.strip().lower(), "USD")

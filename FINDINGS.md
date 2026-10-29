# Qloo price & coverage findings

Run: 2026-10-29, `scripts/price_test.py` against `https://hackathon.api.qloo.com`. All 14 calls returned HTTP 200.

## Field and parameter names

| Name | Kind | Source | Notes |
|---|---|---|---|
| `properties.price_level` | response field | observed | Integer 1–4 (like $–$$$$). The only usable price signal for restaurants. |
| `properties.price_range` | response field | observed | Always `{from: null, to: null, currency: "usd"}` for restaurants, even in Bengaluru. No value. |
| `filter.price_level.min` / `.max` | request param | docs (`docs.qloo.com/reference/parameters`) | "Accepts values 1–4". Place only. |
| `filter.price_range.min` / `.max` | request param | docs | 0–1,000,000, described as hotel price range. Not tested. |
| `properties.business_rating` | response field | observed | Float. Present on 100% of results in every test. |
| `properties.external.tripadvisor.rating`, `.rating_count` | response field | observed | Present on some places (Smoke House Deli, Carbone). |
| `properties.external.resy.rating`, `.rating_count` | response field | observed | Carbone (NYC) only. Not seen in Bengaluru. |
| `filter.properties.business_rating.min/.max`, `filter.external.tripadvisor.rating.min/.max`, `filter.external.resy.rating.min/.max` | request params | docs | Not tested. |
| `feature.explainability=true` | request param | docs | Works. Adds `query.explainability` per result and at top level. |

Auth: `X-Api-Key` header. Endpoints used: `/search`, `/entities`, `/v2/insights`.

## Price-field coverage (`price_level` present, 20 results each)

| Signal | City | `price_level` coverage | Food places | Levels seen |
|---|---|---|---|---|
| Popeyes | Bengaluru | 20/20 (100%) | 20/20 | 1, 2, 3 |
| Smoke House Deli | Bengaluru | 4/20 (20%) | ~11/20 by hand (script's loose tag match says 14) | 3, 4 |
| Carbone | New York | 20/20 (100%) | 20/20 | 3, 4 |

## Server-side price filtering works

| Test | Filter | HTTP | Overlap with unfiltered | Results over the cap |
|---|---|---|---|---|
| C1 Popeyes BLR | `price_level.max=2` | 200 | 18/20 | 0 |
| C2b Smoke House Deli BLR | `price_level.max=2` | 200 | 0/20 | 0 |
| D4 Carbone NYC | `price_level.max=3` | 200 | 6/20 | 0 |

- The filter is strict: it also drops places with no `price_level`. In C2b this removed the salons and gyms, and 20/20 results were cafés and restaurants.
- C1 hardly changed because Popeyes is itself level 2. To get cheaper places, use `max = own_level - 1`.
- Filtering in Python would also work, since the field is always present when it exists, but the server-side filter keeps `take=20` full.

## Surprises

- **Premium Bengaluru places can lack `price_level`.** Smoke House Deli (the entity itself) has none, so we can't compute "one level cheaper" from it. We would need a fallback, such as asking the user or assuming level 3.
- **Insights for `urn:entity:place` are not restricted to food.** Smoke House Deli's twins include salons, gyms, a skin clinic and Miniso. Restaurant tags exist in the responses (`urn:tag:category:place:restaurant`, `urn:tag:genre:place:restaurant`). Restricting by tag is the next thing to test; it is not verified yet.
- **Results cluster around the signal branch.** Popeyes Kalyan Nagar gave twins in Kammanahalli/Kalyan Nagar. Which branch we pick changes the results.
- **Currency is `usd` everywhere**, and there are no real price amounts. Prices are relative tiers only.
- **Kit rules:** "Cache only what your project needs, respect the event quota, and make retry behavior bounded. Do not automate bulk scraping." The kit lists the `@qloo/qloo-harness` CLI/MCP as the supported surfaces. Direct REST calls worked, but confirm with organizers that they're allowed. The kit doesn't publish a rate-limit number.

## Verdict

| Result | Decision |
|---|---|
| Price data exists AND Bengaluru results are good | Build for India |
| Price data exists, Bengaluru thin, NYC good | Build, demo in NYC |
| No price data anywhere | Stop: switch idea |

**Build.** Price data exists (`price_level`), and the server-side filter works.
NYC is clean in every test. Bengaluru works for casual signals and gives good food results once `filter.price_level.max` is applied. However, premium Bengaluru signals have patchy `price_level` and drift to non-food places.
Recommendation: build city-agnostic, **demo in NYC**, and show Bengaluru as a second example with the restaurant-tag filter added.

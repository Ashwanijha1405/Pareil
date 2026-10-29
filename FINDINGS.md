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

## Restaurant tag filter (2026-10-29, `scripts/probe_tags_signals.py`)

`filter.tags` is in the docs: "comma-separated list of tag IDs". `operator.filter.tags` defaults to `union` (OR).
The docs' only example ID (`urn:tag:genre:restaurant:Italian`) doesn't match the IDs the API returns. The IDs below come from observed responses.

Tags used: `urn:tag:genre:place:restaurant,urn:tag:category:place:cafe,urn:tag:category:place:bakery`

| Test (Smoke House Deli, Bengaluru) | HTTP | Food places | Carry a filter tag |
|---|---|---|---|
| T1 tags only, no price filter | 200 | 20/20 (salons, gyms, clinic gone) | 20/20 |
| T2 tags + `filter.price_level.max=2` | 200 | 20/20 | 20/20 |

- Every result, cafés and bakeries included, carries `urn:tag:genre:place:restaurant`. The café/bakery tags add nothing here, but they're harmless in a union.
- **T1 still lets through places with no `price_level`** (about half of them). T2's price filter removes those. This is fine for twins, which always have a price cap. Origins can still lack a tier, so `tiers.py` needs its fallback.
- One edge case: SMOOR (a chocolate shop) and Wishing Chair (a home-goods store with a café) pass because Qloo tags them `genre:place:restaurant`. They're acceptable as food places.

## Multiple and weighted signals (2026-10-29)

Docs: `signal.interests.entities` accepts "a comma-separated list of entity IDs" (GET). Per-entity weights are POST-only: "Weights must be greater than 0 and are relative."

| Test (NYC: Carbone + Joe's Pizza + Katz's) | HTTP | Each input in per-result explainability | Avg influence on top 10 (Carbone / Joe's / Katz's) | Overlap with Carbone-only |
|---|---|---|---|---|
| S1 GET, comma-separated, equal weight | 200 | 20/20 for all 3 | 0.31 / 0.35 / 0.34 | 0/20 |
| S2 POST, `{"entity": id, "weight": n}` (docs form) | **400** | - | - | - |
| S2b POST, `{"id": id, "weight": n}`, weights 3/1/1 | 200 | 20/20 for all 3 | 0.41 / 0.30 / 0.29 | 2/20 |

- **The docs are wrong about the key name.** The API error says: "objects with an id property". Use `id`, not `entity`.
- **Equal weights wash out the origin.** S1 drifted to tier-1 casual places (Bobwhite, 2nd Ave Deli). They're "personal", but they're no longer twins of Carbone.
- **Weights work.** At 3/1/1, Carbone becomes the strongest input and the results go back to Carbone-like places (Via Carota, Raoul's, Misi).
- **Explainability names each input**, so a "why" can say which of the user's places drove a pick.
- Decision for `twins.find`: POST with origin weight 3 and the 2 extra signals at weight 1.
- **Filters work in the POST body (P1, verified 2026-10-29).** I sent weights 3/1/1 with `"filter.tags": "<food tags, comma-separated>"` and `"filter.price_level.max": 3`. Result: HTTP 200, 20/20 food-tagged, 0/20 over the cap or missing `price_level`, and all 3 inputs attributed on 20/20 results. `twins.py` still falls back to GET with equal weights if a POST fails or a result breaks a filter, and the trace records which path was used.

## Other observed tag facts

- Bar tag IDs (observed, for `widen_tags`): `urn:tag:category:place:bar`, `urn:tag:category:place:wine_bar`, `urn:tag:category:place:cocktail_bar`, `urn:tag:category:place:pub`.
- Some entries in an entity's `tags` list have no `id` key. Parse them with `.get("id")`.

## Verdict

| Result | Decision |
|---|---|
| Price data exists AND Bengaluru results are good | Build for India |
| Price data exists, Bengaluru thin, NYC good | Build, demo in NYC |
| No price data anywhere | Stop: switch idea |

**Build.** Price data exists (`price_level`), and the server-side filter works.
NYC is clean in every test. Bengaluru works for casual signals and gives good food results once `filter.price_level.max` is applied. However, premium Bengaluru signals have patchy `price_level` and drift to non-food places.
Recommendation: build city-agnostic, **demo in NYC**, and show Bengaluru as a second example with the restaurant-tag filter added.

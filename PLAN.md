# Fuel Route API — Plan

Scope: execute complete local assignment. User authorizes gates + implementation. GitHub publishing + Loom recording deferred by user.
Geoapify work paused by user. No new requests, batch jobs, or polling until user resumes.
Roles: Sol lead/review. Luna inspect. Terra implement.

## Assignment
- Django API. Input start + finish, both USA.
- Return route map + fuel stops, cost effective.
- Range 500 mi. 10 mpg. Tank 50 US gal.
- Return total fuel money.
- Prices from `fuel-prices-for-be-assessment.csv`.
- Free map/routing API. 1 call ideal, 2–3 acceptable.
- Fast response. Loom ≤5 min (Postman + code). GitHub. Deadline 3 days.

## Stack
- Django 6.1.2 (PyPI checked 2026-10-30). Pin.
- Plain Django JSON views. No DRF.
- SQLite.
- Pure Python geometry + optimizer. NumPy/SciPy only if measurement show need.
- Routing: OSRM. Default public demo `https://router.project-osrm.org`. Local OSRM via `OSRM_BASE_URL` (e.g. `http://127.0.0.1:5050`). No silent fallback.
- Local trials: District of Columbia and Jackson–Dickson regional corridor. Neither covers the USA.
- Native prebuilt macOS package preferred when avoids Docker VM overhead; portable pinned Docker config retained.
- National graph build out of submission scope: public routing covers USA. Local regional graphs optional.
- Public OSRM demo is default. 1 req/s per process, no SLA; disclose.
- Road snapping bounded: endpoints at most 1,000 m, fuel stops at most 100 m. Limits configurable, finite, positive, included in cache identity. Missing nearby road returns coverage error.
- Coincident coordinates share smallest applicable snapping radius. No endpoint/stop radius mismatch at zero-fuel origin. Station coordinates and snaps do not prove physical access.
- Native serving uses memory-mapped graph + disables unused route-step dataset. Route geometry remains enabled. This does not establish nationwide preprocessing feasibility.
- Offline station matching reads local OSM fuel nodes; no Geoapify dependency. Ambiguous or missing identity/address evidence stays unresolved.
- Map: Leaflet + OSM tiles + attribution. Tile requests = browser, disclosed separate.

## Dataset facts (CSV inspected)
- 8151 rows. 6738 unique IDs. No coordinates.
- Canada rows present (AB BC MB NB NS ON QC SK YT). Drop. US only.
- 678 IDs repeat. All repeats share same address + city + state + Rack ID. Consistent source records, many price rows. Not proof of same physical station.
- 227 repeat IDs have name variants ("PILOT TRAVEL CENTER #1243" vs "PILOT #1243").
- Price spread inside repeat ID: median $0.06, max $0.90. No date column. No "latest" price.
- 26 exact duplicate rows.
- 1256 city values have trailing whitespace. Trim.
- Addresses mostly highway exit form ("I-44, EXIT 283 & US-69"). Not street address.

## Station rules
- Group key = OPIS ID + normalized address/city/state. Justified for this file (Luna recheck). Means source consistency, not verified physical identity.
- Mismatch inside ID on load = flag, no merge.
- Keep all source rows + distinct prices.
- Station price = median of source rows, exact duplicate rows excluded from calculation (kept in storage). Label "derived snapshot price". Not current, not newest. Return source min/max/row count as metadata.
- Planning use only stations with `precision=station`.
- Full import: every station accepted only by per-station evidence rule (Gate A section), checked automatically per record. Gate A manual sample validates method, not every station. Store evidence fields per station (matched name/number, matched address/exit, source).
- Evidence point must fall inside its source state boundary. Import consistency checks do not independently prove physical station identity; source evidence still required.
- City-only / unresolved stations: keep source record, exclude from planning.
- No station found on corridor: report "insufficient verified station coverage", not "no station exists".

## Coverage rules
- CSV snapshot only. Live nationwide brand pricing outside assignment scope.
- Missing CSV rows or unresolved coordinates never mean no physical station exists.
- Starting fuel covers verified trip: no purchase needed. Purchase cost $0, even without station prices.
- Refueling required, no feasible chain of verified priced stations found: candidate unavailable. Code `INSUFFICIENT_VERIFIED_PRICE_COVERAGE`.
- Preserve available road geometry, distance, duration, fuel consumed, coverage reason. Total purchase cost = null, never $0 or invented price.
- Baseline unavailable, alternative verified feasible: return alternative; baseline cost + savings = null.
- Baseline feasible, alternatives unavailable: return baseline + explicit comparison status.
- No verified feasible candidate: HTTP 422 with available route information + coverage/verification reason. No executable fuel plan claimed.

## Baseline + alternatives
- Baseline = fastest driving route returned by routing engine. Optimize fuel purchases along baseline.
- First routing request asks for bounded alternative routes too. Provider may return none. Do not promise alternatives exist.
- Screen nearby routes + station detours locally. Estimated costs rank candidates only; never final totals or feasibility proof.
- Compare verified baseline with best verified alternative found. Same start fuel, 50-gal tank, 10 mpg, arrival reserve 0.
- Report each verified candidate: driven distance + duration, gallons consumed + purchased, purchase cost, ordered purchases, fuel before/after purchase, arrival fuel, lowest-fuel points.
- Compare purchase savings, added miles, added duration. Savings only when both totals known.
- Baseline refueling detours may change driven distance/time. Compare final verified driven paths; retain original baseline geometry separately.
- Recommendation = lowest purchase cost among verified feasible candidates. Tie: shorter duration, then distance.
- Search bounded. No globally cheapest route claim.

## Location input rules
- Ambiguous city response: stable max 20 candidates, each with reusable coordinate `location`; `truncated` signals more matches. Narrow by state when truncated.
- Accept coordinates, "City, ST", or street address.
- Coordinates: no call.
- City: local Census Gazetteer table. No call. Ambiguous ("Springfield") = clarification response with candidates.
- Street address: Census Geocoder batch, both endpoints in 1 request (candidate, Gate B). No landmarks.
- Address not resolvable: error with reason. No guess.
- Outside USA: error.

## Fuel model
- `start_fuel_gallons` optional, default 50. 0 ≤ x ≤ 50. Cache key uses effective value.
- Existing fuel cost = 0. Trip within starting range = $0 purchase cost.
- Report separate: gallons purchased, purchase cost, gallons consumed, remaining gallons.
- Every driven station waypoint listed, including zero purchase. `purchase=false` marks pass-through. Waypoint index + station ID identify stop low points and map markers.
- Start fuel 0: purchase must happen at origin station itself. Origin must match verified station (station ID or coordinates at station point). No positive driving leg before purchase. Else error.
- Zero-fuel coordinates within existing 1e-6-mi origin tolerance normalize to nearest verified station point before cache/routing. Equal-distance distinct points require clarification. First purchase waypoint must equal canonical origin exactly; no tolerance increase.
- Prices = USD per US gallon snapshot. Not live. Document.

## Optimizer (fixed ordered stops)
- Input: ordered leg distances, prices, start fuel, tank 50 gal, 10 mpg.
- First leg: first purchase stop (or destination) must be ≤ `start_fuel_gallons × 10` miles. Full-tank range never used for first leg.
- At each stop: find first cheaper station reachable on full tank.
  - Found: buy just enough to reach it.
  - Not found: fill tank, or buy just enough to reach destination if destination in range.
- Ties: equal price = not cheaper. Order by route position, then station ID.
- Partial purchase allowed. Fuel never < 0, never > 50.
- Optimal claim = only for final fixed stop sequence. Candidate selection + road routing = heuristic. Say so.
- Test vs brute-force reference solver on tiny cases.
- Unit tests bounded + deterministic. Nine-state fuel oracle: 128 fixed-seed cases, max four purchase stops. Existing integer-reference cases retained. Check fuel conservation, tank bounds, cost, minimum-fuel points, invalid inputs, and verified-route failure branches.
- Unit suite: mocked providers, tiny geometry/data fixtures. No network, graph builds, large map fixtures, sleeps, benchmarks, or unbounded fuzz/mutation runs. No elapsed-time assertions. Live routing checks separate.

## Request flow + call budget
1. Resolve locations (0 or 1 geocoding call).
2. Routing call 1: start → finish, request alternatives. Keep baseline + returned alternatives.
3. Local: find priced station candidates per route (bbox prefilter + route segment grid). Rank routes/stops by estimated cost. Estimated detour factor only for ranking.
4. Local: propose baseline stops + best alternative stops. Respect initial fuel; safety margin cannot reject already verified feasible 500-mi legs.
5. Prioritize baseline verification, then best alternative verification. Route each chosen waypoint sequence; recompute purchases from real legs.
6. Candidate needs no refueling detour: original returned route already supplies verified distances; no extra routing call needed.
7. Same driven waypoints, only purchases change: local optimizer only. Any driven waypoint change needs new verification.
8. Max 3 routing calls total. Alternative verification + repair share remaining calls after initial request. Max 1 repair call, only within total budget. Same rule all input types.
9. Baseline fails verification: use remaining call for repair or best alternative, based on known failure + coverage. Never assume enough calls for baseline, alternative, and repair together.
10. Budget exhausted: preserve verified feasible results. Comparison status explains alternative not verified within budget; never publish estimated alternative as executable plan.
11. Store result in `RoutePlan`; return baseline, recommendation, comparison status, map URL. No feasible result: explicit error + available route information.

Budget counted separate. Brief names "map/routing API": routing count = budget. Geocoding disclosed separate. Employer acceptance unknown — README state both counts plain.

| Input | Geocoding calls | Routing calls |
|---|---:|---:|
| Coordinates or local city | 0 | 1–3, verification + repair shared |
| 1–2 street addresses (Census batch) | 1 | 1–3, verification + repair shared |
| Full cache hit | 0 | 0 |

Default public demo: max 4 external server calls (1 Census + 3 routing). Local OSRM via `OSRM_BASE_URL`: routing requests local, external server calls 0–1 Census only. Browser assets/tiles separate. Disclose both modes.

- Response distinguishes verified executable candidates from unavailable/unverified comparisons. Never return estimated plan as executable.
- Top-level `reasons` preserves distinct unavailable-candidate causes. Any candidate verification-provider failure prevents plan-cache reuse; stored map remains available.
- Cache: geocode results, routes, plans.
  - Geocode key = normalized input text.
  - Route key = ordered waypoint coordinates.
  - Plan key = normalized inputs + start fuel + station dataset version + planning settings version.
  - Station dataset version = hash of station coordinates + derived prices + evidence. Changes on reimport.
  - Planning settings version = hash of range, mpg, tank, corridor, safety margin, repair bound, alternative-search settings, comparison rules.

## API
- `POST /api/routes` body: `start`, `finish` required; `start_fuel_gallons` optional (default 50). Extra keys ignored.
- Response: `plan_id`, status, baseline, verified alternatives, recommended candidate, comparison status, savings/extra miles/extra duration when known, `map_url`.
- Top-level `geometries`: id → simplified geometry, each distinct once. Roads carry `geometry_id`.
- Per candidate: verified route geometry id, distance, duration, ordered stops (name, address, coordinates, route position, derived price + source price range, gallons bought, stop cost, fuel before/after), totals (purchased, cost, consumed, remaining), lowest-fuel points.
- Unavailable candidate: reason + available road information; purchase cost null. No invented stops or savings.
- `GET /map/<plan_id>`: Leaflet page from stored `RoutePlan`. Zero server-side routing/geocoding calls. Browser tile requests remain (disclosed).
- Errors: ambiguous location (with candidates), non-US, unresolvable address, insufficient verified coverage, zero-fuel origin not at station, verification failed within budget, provider failure.

## Gates before scaffold
### Gate A — station location quality
- Sample ≥100 US stations. Deliberate coverage, not only random: address formats (exit form, street form, intersections), regions, chains (Pilot, Love's, TA, independents).
- Methods: independent operator locator records, local OSM `amenity=fuel` data. Geoapify branch paused. Nominatim sample only, rules below.
- `precision=station` require evidence identifying this particular station:
  - name or store number match (e.g. "#1243"), AND
  - address or highway/exit match.
  - Fuel tag or brand alone = insufficient. Other fuel station nearby cannot satisfy it.
- City centroid distance = plausibility check only. Not proof.
- Provider confidence alone ≠ verified.
- Independent manual check on sample subset.
- Nominatim public use: single thread, cache results, identify app (User-Agent), ≤1 req/s. Sample lookups only. No fuel station enumeration. No full dataset run without separate permission.
- Output: coverage %, failure classes, chosen method. User decide if coverage enough.
- Geoapify branch requires explicit user resume; not prerequisite for offline matching.

### Gate B — endpoint geocoding + call budget
- Census batch: at most one request for both street addresses. Provider failure stays explicit.
- Keep call budget above.

## Execution TODO — open work only, dependency order
- [ ] Assess broader, multibrand source-backed station evidence and obtain coverage acceptance. Current eligible coverage: 356 Love's groups, about 5.4%. Geoapify paused.
- [ ] Assess station snapping/access beyond the verified regional route. Do not assume all resolved stations are reachable. Preserve zero-fuel no-driving rule and zero arrival reserve until explicitly changed.
- [ ] Resolve redistribution terms for operator-derived assets before public delivery. Keep local source assets.
- [ ] Complete GitHub publishing and Loom recording when requested.


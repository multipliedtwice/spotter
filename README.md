# Fuel Route API

A Django + SQLite API that plans fuel stops along a driving route in the USA. It requests the fastest driving route and a bounded set of alternatives from OSRM (public demo by default, local OSRM optional), picks verified fuel stops along the corridor, and minimizes fuel purchase cost for a vehicle with a 500-mile range (50 US gallons at 10 mpg). Each plan is stored and shown on a Leaflet map.

> **Coverage limitation:** only 356 of 6,626 station groups in the supplied price file (all Love's, 41 states) have verified coordinates and take part in planning. Routes outside that coverage can return 422, and cheaper stations from other brands are not considered.

## Setup

Python 3.12+. Export `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`; see `.env.example`. There is no `.env` loader. Routing works out of the box with the public OSRM demo (`https://router.project-osrm.org`, no SLA, 1 request per second per process). For a local OSRM, set `OSRM_BASE_URL` (for example `http://127.0.0.1:5050`); see [docs/routing.md](docs/routing.md).

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_data stations fuel-prices-for-be-assessment.csv
python manage.py load_data gazetteer data/gazetteer.csv
python manage.py load_data evidence data/station_evidence.csv
python manage.py runserver --nothreading
```

Evidence CSV format, import checks and review tooling: [docs/station-evidence.md](docs/station-evidence.md).

## API

```sh
curl -X POST http://127.0.0.1:8000/api/routes -H 'Content-Type: application/json' -d '{"start":"Dallas, TX","finish":"Los Angeles, CA","start_fuel_gallons":20}'
```

The response reports `start_fuel_gallons` (the effective starting fuel; default 50 is a full tank) and `cost_basis`. `purchase_cost_usd` is the cost of fuel purchased during the journey only. Starting fuel is valued at $0, so a trip within the starting range costs $0.

Accepted location formats for `start` and `finish` (both required):

- coordinates: `{ "latitude": 40.7, "longitude": -74.0 }`
- station: `{ "station_id": "7" }`
- `"City, ST"` or `"City, State"`
- `"street, city, state ZIP"` (ZIP may be separate; trailing USA is optional)

For an ambiguous city, retry with one of the returned candidate `location` objects (at most 20 candidates; if truncated, narrow by state). Both locations must lie inside the local US polygon. Extra request keys are ignored.

`start_fuel_gallons` is optional, 0 to 50 gallons, default 50 (full tank). With `0`, a verified station at the origin is required.

Response (`200`): `plan_id`, baseline, alternatives, recommendation, comparison, `map_url`, `geometries`. Each road carries a `geometry_id`; `geometries` maps each distinct route geometry once, simplified (Douglas-Peucker, 1e-3 degrees tolerance, about 110 m; display only, part of the plan cache identity). Station search and verification use the full geometry. A verified candidate has geometry id, distance, duration, every driven waypoint, purchases, fuel balances and low points. Pass-through waypoints have `purchase: false`; stop low points include station ID and waypoint index. `reasons` lists causes for unavailable candidates. The map uses the stored result and makes no server-side provider calls; the browser loads OpenStreetMap tiles.

Status codes:

- `200`: plan returned.
- `400`: invalid or unresolved input.
- `422`: insufficient verified station coverage, or no drivable route in loaded road data; available road retained, cost null.
- `503`: provider or required data failure.

## Demo

Primary: `"Dallas, TX"` to `"Los Angeles, CA"`, starting fuel 20 gallons, public OSRM routing, bundled station evidence imported. Request: the API example above.

Live result on 2026-10-31: 1,453.9 miles, about 25.4 hours. Five purchase stops: Baird TX 41.91 gal ($130.24), El Paso TX 50.00 gal ($153.78), Las Cruces NM 7.05 gal ($22.66), Benson AZ 22.23 gal ($72.89), Eloy AZ 4.20 gal ($14.42). Total 125.39 gallons and $393.99 of fuel purchased during the journey; the 20 starting gallons are valued at $0. The fastest-route baseline plan costs $419.61 with three stops; the recommendation saves $25.62 for 1.71 extra miles and about 10 minutes. Uncached response about 5 seconds (three public OSRM calls, rate-limited to one per second); a repeated request is served from the plan cache. Results change with OSRM road data and station data.

Short comparison (secondary): station 63724 Jackson, TN to 67420 Dickson, TN, starting fuel 0.

Baseline $27.03; recommended $25.88. Save $1.15 for 0.82 extra miles and 298.6 seconds (about 5 minutes). The recommendation minimizes fuel purchase cost; time has no assigned value. Results depend on road and station data. This example needs the Jackson–Dickson regional graph or explicit public validation, with bundled station evidence imported; the DC graph does not cover it. The 78.1-mile, zero-start-fuel trip demonstrates cheaper refills, not the 500-mile tank boundary. A trip over 500 miles uses default public routing or a covering local graph; unit boundary tests use mocked data. Commands: [docs/routing.md](docs/routing.md).

## Limits and assumptions

- Vehicle: 50 US gallons, 10 mpg, zero arrival reserve. Existing fuel costs zero; a no-purchase trip costs $0.
- Cost is in USD; each stop charge rounds half up to cents and the total sums stop charges. Price is USD per gallon with six decimal places, taken as the median per ID and normalized location (exact duplicate rows excluded). The source has no date: prices are a snapshot, not current or latest. Min, max and source row count are returned.
- Station coverage is a known limitation. Bundled eligible evidence covers 356 Love's station groups across 41 states, about 5.4% of 6,626 US source groups. Other brands lack eligible location evidence, and unresolved locations stay excluded from plans. Missing verified coverage does not mean no station exists; no nationwide priced-station coverage is claimed. Provenance: [data/SOURCES.md](data/SOURCES.md).
- Optimization: for a fixed ordered set of stops the optimizer minimizes unrounded fuel cost (cent rounding may change the exact optimum). Route and station sequence search is a bounded heuristic with no global-optimum claim. The provider may return no alternatives. Waypoint routes are verified, and final fuel uses the returned road legs.
- Routing-call budget: an uncached request makes 1 to 3 routing HTTP requests, including verification and repair. With the default public demo all are external, for a maximum of 4 external calls including Census. With a local OSRM, routing requests are local. Coordinates and local city lookups make 0 external geocoding calls; street addresses make 1 external Census batch call. Browser tile and asset calls are separate.
- Caching: caches expire. The plan cache includes a persisted station-data digest and planning/provider settings, and is invalidated by ORM writes and the supplied imports. Raw SQL changes need a manual invalidate step; see [docs/routing.md](docs/routing.md).
- OSRM has no automatic fallback between public and local. Settings (`OSRM_BASE_URL`, `OSRM_PROFILE`, `OSRM_DATASET_VERSION`, `OSRM_TIMEOUT`, snapping radii, `FUEL_CORRIDOR_MILES`) are documented in [docs/routing.md](docs/routing.md).
- Map: Leaflet with OpenStreetMap attribution.

## Tests

After resource and service preflight, run one gate at a time:

```sh
python manage.py test
```

Tests use synthetic fixtures and mocked providers. Postman coordinates are public locations; no synthetic station prices are presented as production prices.

Optimizer reference checks: bounded integer cases plus 128 fixed-seed fractional-fuel cases, at most four purchase stops and nine fuel states. They check optimal unrounded cost, fuel conservation, tank limits and failure branches. Provider responses are mocked; there are no live API calls, graph preprocessing, large map fixtures or elapsed-time assertions. Live OSRM checks are separate from the unit suite.

## Further documentation

- [docs/routing.md](docs/routing.md): OSRM settings and snapping, cache invalidation, explicit public validation, local OSRM trials (Docker and native macOS), car-profile PBF filter, Jackson–Dickson corridor.
- [docs/station-evidence.md](docs/station-evidence.md): evidence CSV format and import checks, review sampling, Geoapify (paused), offline Love's, offline OSM.
- [data/SOURCES.md](data/SOURCES.md): data source provenance.

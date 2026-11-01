# Fuel Route API

A Django + SQLite API that plans fuel stops along a driving route in the USA. It requests the fastest driving route and a bounded set of alternatives from OSRM (public demo by default, local OSRM optional), picks verified fuel stops along the corridor, and minimizes fuel purchase cost for a vehicle with a 500-mile range (50 US gallons at 10 mpg). Each plan is stored and shown on a Leaflet map.

> **Coverage limitation:** 1,214 of 6,626 US station groups (18.3%, 43 states) have accepted coordinates and take part in planning. This preserves 356 operator-backed locations and adds 858 OSM matches. Unmatched stations remain excluded; some routes can return 422 and cheaper unresolved stations can be missed.

## Setup

Python 3.12+. `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS` are optional for local use (settings fall back to local-only defaults); set both for any deployment, see `.env.example`. There is no `.env` loader. Routing works out of the box with the public OSRM demo (`https://router.project-osrm.org`, no SLA, 1 request per second per process). For a local OSRM, set `OSRM_BASE_URL` (for example `http://127.0.0.1:5050`); see [docs/routing.md](docs/routing.md).

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

`start` and `finish` (both required) accept:

- coordinates: `{ "latitude": 40.7, "longitude": -74.0 }`
- station: `{ "station_id": "7" }`
- `"City, ST"` or `"City, State"` (a trailing country such as `"Dallas, TX, USA"` is accepted)
- `"street, city, state ZIP"` (trailing USA is optional)

For an ambiguous city, retry with one of the returned candidate `location` objects (at most 20; if truncated, narrow by state). Both locations must lie inside the local US polygon. Extra request keys are ignored.

`start_fuel_gallons` is optional, 0 to 50, default 50 (full tank). With `0`, a verified station at the origin is required.

Response (`200`):

- `distance_miles`, `purchase_cost_usd`, `fuel_stops`: taken from the recommended plan. `fuel_stops` lists only stops where fuel is bought (station, price per gallon, gallons, cost, route position, waypoint index). If there is no recommendation, `purchase_cost_usd` and `fuel_stops` are null and `distance_miles` is the baseline road distance.
- `plan_id`, `map_url`, `baseline`, `alternatives`, `recommended`, `comparison`, `reasons`, `start_fuel_gallons`, `cost_basis`.
- `geometries`: each distinct route geometry once, simplified (Douglas-Peucker, about 110 m, display only). Roads reference it by `geometry_id`.

A verified candidate has distance, duration, every driven waypoint (pass-through waypoints have `purchase: false`), purchases, fuel balances and low points. The map uses the stored result and makes no server-side provider calls.

Status codes:

- `200`: plan returned.
- `400`: invalid or unresolved input.
- `422`: insufficient verified station coverage, or no drivable route in loaded road data; available road retained, cost null.
- `503`: provider or required data failure.

## Example

Dallas, TX to Los Angeles, CA, starting fuel 20 gallons, public OSRM, bundled evidence imported. Live check on 2026-11-01: 1,453.6 miles, about 25.3 hours, four purchase stops (QuikTrip Abilene TX, Circle K El Paso TX, QuikTrip Tucson AZ, Flyers Phoenix AZ), 125.36 gallons, $368.39 of fuel purchased. The remaining routing call verified a second proposal at $386.38, so the fastest-road plan stays recommended; comparison is `compared` with savings $0. Three routing calls; about 6.4 s uncached, 0.3 s cached. Results change with road and station data.

## Limits and assumptions

- Vehicle: 50 US gallons, 10 mpg, zero arrival reserve. Starting fuel is valued at $0; `purchase_cost_usd` covers fuel bought during the journey only.
- Prices are a snapshot (the source has no date): median per station ID and location, USD per gallon. Each stop charge rounds half up to cents.
- Station coverage: 1,214 of 6,626 US groups are usable; 5,412 remain unlocated. OSM matching supports fuel geometry, source-confirmed business sites, and independently linked highway exits/intersections. City points screen candidates and never become fuel-stop coordinates. Missing coverage does not mean no station exists. Provenance: [data/SOURCES.md](data/SOURCES.md).
- Stop search is a bounded heuristic with no global-optimum claim; waypoint routes are verified with the returned road legs.
- City lookup uses Census gazetteer points. 21 coastal places whose Census point lies in water use Census Geocoder (Boston, San Francisco) or USGS GNIS points instead; see [data/SOURCES.md](data/SOURCES.md).
- Calls per uncached request: 1 to 3 OSRM routing requests, plus 1 Census batch call for street addresses. Coordinates and local city lookups make no geocoding call.
- The plan cache expires and is invalidated by station-data and settings changes; see [docs/routing.md](docs/routing.md). OSRM settings are documented there too.

## Tests

```sh
pip install --only-binary=:all: -r requirements-osm.txt
python manage.py test
```

OSM resolver tests need `osmium` from `requirements-osm.txt`. Tests use synthetic fixtures and mocked providers; there are no live API calls.

## Further documentation

- [docs/routing.md](docs/routing.md): OSRM settings, cache invalidation, local OSRM, validation.
- [docs/station-evidence.md](docs/station-evidence.md): evidence CSV format, import checks, review.
- [data/SOURCES.md](data/SOURCES.md): data source provenance.

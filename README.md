# Fuel Route API

Django + SQLite. Fastest driving route baseline. Bounded alternative search. Verified waypoint fuel plan. Leaflet map.

## Setup

Python 3.12+. Export `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`; see `.env.example`. No `.env` loader. Routing works out of the box with the public OSRM demo (`https://router.project-osrm.org`, no SLA, 1 request per second per process). For a local OSRM, set `OSRM_BASE_URL` (for example `http://127.0.0.1:5050`) and see the local OSRM sections below.

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

Required: `data/us_boundary.geojson`, state FeatureCollection with Polygon/MultiPolygon geometry and unique `STUSPS` for every imported station state. Gazetteer CSV: `name,state,latitude,longitude`. Evidence CSV: `station_id,address,city,state,latitude,longitude,matched_name,matched_address,source`. Evidence import replaces previous set. Each point must lie within its source state Census boundary. Independent per-station evidence required: particular name or store number, plus address or highway and exit. Import checks source name or store number and meaningful name token; exact address or same highway type/number and exit. Evidence source and matched values retained. These consistency checks cannot prove coordinates identify the correct physical station; review sources independently. Unresolved records retained, excluded from plans. For review sample: `python manage.py sample_stations sample.csv --count 100`.

## API

```sh
curl -X POST http://127.0.0.1:8000/api/routes -H 'Content-Type: application/json' -d '{"start":{"station_id":"63724"},"finish":{"station_id":"67420"},"start_fuel_gallons":0}'
```

Example: Jackson–Dickson regional graph or explicit public validation, with bundled station evidence imported. DC graph does not cover it.

Snapshot example: baseline $27.03; recommended $25.88. Save $1.15 for 0.82 extra miles and 298.6 seconds (about 5 minutes). Recommendation minimizes fuel purchase cost; time has no assigned value. Results depend on road and station data. The 78.1-mile, zero-start-fuel trip demonstrates cheaper refills, not the 500-mile tank boundary. A trip over 500 miles uses default public routing or a covering local graph; unit boundary tests use mocked data.

Locations: `{ "latitude": 40.7, "longitude": -74.0 }`, `{ "station_id": "7" }`, `"City, ST"`, `"City, State"`, or `"street, city, state ZIP"`. Street address may use separate ZIP and optional USA. Ambiguous city: retry with a candidate `location` object. At most 20 candidates; if truncated, narrow by state. Both locations must lie inside local US polygon. `start` and `finish` required. `start_fuel_gallons` optional, default 50 (full tank), 0–50 gallons; extra keys ignored. Existing fuel costs $0 under this model, so a trip within the starting range returns $0 purchase cost. Zero: verified station at origin required.

`200`: `plan_id`, baseline, alternatives, recommendation, comparison, `map_url`, `geometries`. Each road carries `geometry_id`; `geometries` maps each distinct route geometry once, simplified (Douglas-Peucker, 1e-3 degrees tolerance, about 110 m; display only, part of plan cache identity). Station search and verification use the full geometry. Verified candidate: geometry id, distance, duration, every driven waypoint, purchases, fuel balances, low points. Pass-through waypoints have `purchase: false`. Stop low points include station ID and waypoint index. `reasons` lists unavailable candidate causes. `422`: insufficient verified station coverage or no drivable route in loaded road data; available road retained, cost null. `400`: invalid or unresolved input. `503`: provider or required data failure. Map uses stored result; no server-side provider calls. Browser loads OpenStreetMap tiles.

## Limits

50 US gallons; 10 mpg; zero arrival reserve. Existing fuel cost zero. No-purchase trip: $0. Cost: USD; each stop charge rounds half up to cents; total sums stop charges. Price: USD per gallon, six decimal places. Source price: median per ID and normalized location, exact duplicate rows excluded. No source date. Snapshot, not current or latest price. Min, max, source row count returned. Missing verified coverage does not mean no station exists.

Bundled eligible evidence: 356 Love's station groups across 41 states, about 5.4% of 6,626 US source groups. Other brands lack eligible location evidence. Unresolved locations stay excluded. Coverage gaps expected; no nationwide priced-station coverage claim. Source provenance: `data/SOURCES.md`.

Fixed ordered stops: optimizer minimizes unrounded fuel cost; cent rounding may change the exact optimum. Route and station sequence search: bounded heuristic; no global optimum claim. Provider may return no alternatives. Waypoint routes verified; final fuel uses returned road legs. OSRM: public demo `https://router.project-osrm.org` by default (no SLA); local OSRM via `OSRM_BASE_URL`; no automatic fallback. Configure `OSRM_BASE_URL`, `OSRM_PROFILE`, `OSRM_DATASET_VERSION`, `OSRM_TIMEOUT`; default profile `driving`, timeout 20 seconds. Road snapping is limited to 1000 m for endpoints and 100 m for fuel stops; coincident points share the smallest applicable limit. Configure positive finite `OSRM_ENDPOINT_RADIUS_METERS` and `OSRM_STOP_RADIUS_METERS`. Missing nearby road means coverage unavailable. Default corridor 5 miles; configure `FUEL_CORRIDOR_MILES`. Public demo is optional, no SLA. Public demo request scheduling is per process; use one process or coordinate rate limits externally. Map: Leaflet + OpenStreetMap attribution.

Uncached request: 1–3 routing HTTP requests, including verification and repair. Default public demo: all external; maximum external calls including Census: 4. Local OSRM via `OSRM_BASE_URL`: routing requests local. Coordinates/local city: 0 external geocoding calls. Street addresses: 1 external Census batch call. Caches expire. Plan cache includes a persisted station-data digest and planning/provider settings. Station `save`, `delete`, queryset `update`/`delete`, `bulk_create`, `bulk_update`, and the supplied imports invalidate the digest transactionally. For raw SQL or fixture paths that bypass these ORM methods, stop serving requests and run `python manage.py shell -c "from planner.models import invalidate_station_dataset; invalidate_station_dataset('default')"` after changes and before resuming. Any candidate verification-provider failure prevents plan-cache reuse; result stays available through its map URL. Corridor must be positive and finite; spatial lookup scales with corridor and latitude and wraps across the antimeridian. Browser tile and asset calls separate.

## Explicit public validation

Public routing is the default. Public demo has no SLA and requires per-process rate scheduling. Import bundled evidence first. This process example sets the demo explicitly.

```sh
OSRM_BASE_URL=https://router.project-osrm.org OSRM_DATASET_VERSION=public-demo python manage.py runserver 127.0.0.1:8001 --noreload --nothreading
```

Set Postman `baseUrl` to `http://127.0.0.1:8001` for this process. Comparison: station `63724` (Jackson, TN) to `67420` (Dickson, TN), starting fuel `0`. Long trip: `63724` to `1516` (Amarillo, TX), starting fuel `0`. The Jackson–Dickson corridor graph can serve the comparison locally; the long trip uses public routing or a covering local graph. No automatic fallback. Public operator location license remains unknown.

## Tests

After resource and service preflight, run one gate at a time:

```sh
python manage.py test
```

Tests use synthetic fixtures and mocked providers. Postman coordinates are public locations; no synthetic station prices presented as production prices.

Optimizer reference checks: bounded integer cases plus 128 fixed-seed fractional-fuel cases, at most four purchase stops and nine fuel states. Check optimal unrounded cost, fuel conservation, tank limits and failure branches. Provider responses mocked; no live API calls, graph preprocessing, large map fixtures or elapsed-time assertions. Live OSRM checks separate from unit suite.

## Geoapify evidence source (paused)

Do not run Geoapify requests while paused.

Set `GEOAPIFY_API_KEY` in the environment. Do not put the key in files or command arguments. Synchronous geocoding: at most two requests/second; one request costs one credit according to [Geoapify documentation](https://apidocs.geoapify.com/docs/geocoding/). Check current account quota before choosing budgets.

```sh
python manage.py sample_stations sample.csv --count 100
python manage.py resolve_geoapify --sample sample.csv --cache data/source_geoapify.json --output data/sample_evidence.csv --max-requests 100 --credit-budget 100
```

Omit `--sample` for all station groups. Required: both budgets. Same cache + new budget resumes incomplete work. Output exists: choose another path or explicitly add `--replace-output`; replacement writes the current selection only. Budget exhausted: output partial; command reports groups awaiting requests. Cache stores selected provider response fields, no key. Results lacking particular station identity and address/exit proof stay unresolved. Name, city, or confidence alone is insufficient. Source row IDs in evidence use OPIS ID plus one-based row position inside the imported group. Review evidence sources before importing. `--replace-output` may discard previous output; import also replaces prior evidence set. Verify completeness before either operation.

Resolver: first query includes source address. If no independently matched evidence, second query uses name and city; address still must come from the result. Each uncached query uses one request and one credit. `--sample` accepts source CSV or `sample_stations` columns. Geoapify store references, place ID and available datasource attribution/license are retained. Check source licenses and attribution before use.


## Local OSRM regional trial

District of Columbia extract only. Does not cover US routes. Evaluate resource needs before any larger dataset. With `OSRM_BASE_URL` pointing to local OSRM, application routing fails when local OSRM is unavailable; no silent public fallback.

Before download, preprocessing, or startup: inspect CPU and memory pressure, free disk, competing builds/tests, Docker availability, and port 5050. Wait if contended. Image download also needs disk and network. Preprocessing and server use separate containers; each limited to one CPU and 1 GiB. The limit may be insufficient; report failure, do not assume coverage. Docker and native servers map graph files with `--mmap` and disables `ROUTE_STEPS`; route geometry remains enabled. Mapping reduces graph heap allocation, not total memory demand, and does not make USA preprocessing feasible. Run stages sequentially. Normal container output remains enabled.

`compose.yaml` pins official OSRM `v6.0.0` image. [OSRM Docker/MLD instructions](https://github.com/Project-OSRM/osrm-backend/tree/v6.0.0#using-docker). [Pinned image architecture metadata](https://github.com/Project-OSRM/osrm-backend/pkgs/container/osrm-backend/399470569?tag=latest). Confirm local Docker architecture support before pulling.

Use an empty task directory `local/osrm/`. Supply an existing `.osm.pbf` as `local/osrm/region.osm.pbf`, or explicitly download the small [Geofabrik DC extract](https://download.geofabrik.de/north-america/us/district-of-columbia.html) (about 20 MB; OSM/ODbL). The following commands create regional data, not nationwide data:

```sh
mkdir -p local/osrm
curl --fail --location https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf --output local/osrm/region.osm.pbf
docker compose run --rm --no-deps osrm osrm-extract --threads 1 -p /opt/car.lua /data/region.osm.pbf
docker compose run --rm --no-deps osrm osrm-partition --threads 1 /data/region.osrm
docker compose run --rm --no-deps osrm osrm-customize --threads 1 /data/region.osrm
docker compose up -d osrm
export OSRM_BASE_URL=http://127.0.0.1:5050
export OSRM_DATASET_VERSION=dc-trial-1
curl --fail 'http://127.0.0.1:5050/route/v1/driving/-77.0365,38.8977;-77.0091,38.8899?overview=false'
```

Only download into an empty task directory; do not overwrite an existing PBF or processed graph. `docker compose up` starts the named `spotter-osrm-trial` container bound to localhost. To stop this task's service: `docker compose stop osrm`. `local/osrm/` is ignored by Git. Keep required data until the trial is finished; remove only task-created files after inspecting paths. Change `OSRM_DATASET_VERSION` whenever the graph changes to invalidate route and plan caches. If choosing the public demo explicitly: `export OSRM_BASE_URL=https://router.project-osrm.org`. Public demo rate scheduling applies only to that host.

## Offline Love's operator evidence

Provide an operator store asset as `data/source_loves_locations.json` with a `stores` array from [Love's store locator](https://www.loves.com/api/fetch_stores). Keep store number, coordinates, address, city, state, highway, exit, name and store-type fields only. No prices or contact fields. Resolver makes no network calls.

```sh
python manage.py resolve_loves --input data/source_loves_locations.json --output local/loves/evidence.csv --unresolved local/loves/unresolved.csv
```

Requires operator Love's store flag, source Love's name and store number, matching city and state, independently matching address or typed highway and exit/mile marker, and a point inside the Census state boundary. Exit and mile markers stay distinct; ambiguous road/marker pairings remain unresolved. Ambiguous and unmatched groups remain unresolved. Operator data license unknown; review terms before use. Output contains no prices. Import replaces the existing evidence set; merge reviewed output with existing evidence first. Prices remain from supplied CSV, not operator data.

## Offline OSM station evidence

Optional dependency: `python -m pip install --only-binary=:all: -r requirements-osm.txt`. Import source stations first. Supply an existing local PBF; no network requests. Run only after resource and disk preflight.

```sh
python manage.py resolve_osm --pbf local/osrm/region.osm.pbf --output local/osm/evidence.csv --unresolved local/osrm/unresolved.csv
```

Reads fuel nodes in one pass with one decode worker and a bounded two-item worker queue. Only fuel nodes reach the Python matcher. Requires OSM name or numeric store ref, address or highway and exit, city, and state tags. Matches source identity and independently tagged address. Multiple matches remain unresolved. Ways and relations are unsupported. Output source links identify OSM nodes; inspect evidence before import. Missing or ambiguous groups stay unresolved. Prices come only from the source CSV. OSM data: [ODbL attribution](https://www.openstreetmap.org/copyright).

## Optional car-profile PBF filter

Requires installed `osmium` CLI and an existing PBF. Default OSRM car profile only; custom profiles need separate review. Output path must not exist. Source stays intact. Preserves tags and referenced objects; includes all highway types, route ways, restriction, route, maneuver and manoeuvre relations, and fuel nodes/ways. Car profile decides road access. Filter may read input up to three times; check resource pressure, free disk and competing work first. No output size or memory-fit guarantee. Compare raw and filtered DC routes before using this for a larger graph.

```sh
taskpolicy -b nice -n 19 python scripts/osrm_filter.py --input /path/to/source.osm.pbf --output /path/to/filtered.osm.pbf
```

Pass filtered PBF to native `prepare` only after parity review and resource preflight. Preserve original input. No download runs automatically.

## Native OSRM regional trial on macOS

Use the installed Homebrew `osrm-backend` 26.10.0. The native and Docker graph formats may differ; never reuse or overwrite one version's graph with the other. Keep native files in a separate empty `local/osrm-native/` directory. Same resource, disk, competing-process, and port preflight applies. Run one stage at a time; wait when contended. This DC graph covers DC only. Full USA graph remains unbuilt; resource needs are unknown. US coordinate validation uses the local Census boundary asset, independent of graph coverage.

```sh
OSRM_PREFIX="$(brew --prefix osrm-backend)"
python scripts/osrm_native.py prepare --input local/osrm/region.osm.pbf
taskpolicy -b nice -n 19 python scripts/osrm_native.py extract --profile "$OSRM_PREFIX/share/osrm-backend/profiles/car.lua"
taskpolicy -b nice -n 19 python scripts/osrm_native.py partition
taskpolicy -b nice -n 19 python scripts/osrm_native.py customize
export OSRM_BASE_URL=http://127.0.0.1:5050
export OSRM_DATASET_VERSION=dc-native-26-10-0-1
taskpolicy -b nice -n 19 python scripts/osrm_native.py serve
```

To use a mounted SD card, pass a dedicated graph directory such as `--data-dir /Volumes/CB_SD128/spotter-ai-osrm/dc-native` to every native stage, including `prepare` and `serve`. Confirm the intended volume is mounted and the parent directory exists. Prepare requires an empty graph directory and copies only the explicitly supplied PBF. Add `--link-input` to prepare to hard-link a PBF on the same filesystem; both names share contents and must not be modified. Cross-filesystem links fail without a copy fallback. Keep source downloads outside that graph directory, and native graphs separate from Docker data. SD storage does not add RAM. No nationwide PBF downloads automatically; supply one explicitly after resource and disk preflight.

Run the DC readiness `curl` from the preceding section in another terminal. Stop only this task's foreground routing process when finished. `taskpolicy` and `nice` lower scheduling priority; they do not cap total memory or CPU. Do not run native and Docker services on port 5050 together. Change `OSRM_DATASET_VERSION` after any graph rebuild.

## Native Jackson–Dickson corridor on macOS

Regional corridor only, not all Tennessee or USA. Requires the existing `us-261028.osm.pbf`, installed `osmium` and Homebrew OSRM 26.10.0. Confirm the SD volume, free disk, memory pressure, competing work and port 5050 before each stage. Run stages sequentially. OSRM preprocessing and serving use one thread; background priority is not a resource cap.

For a fresh setup only, use a new output PBF and an empty native graph directory. Existing PBFs and graph files are not overwritten. This extract uses the verified regional bounds and preserves complete ways:

```sh
OSRM_TASK=/Volumes/CB_SD128/spotter-ai-osrm
OSRM_PREFIX="$(brew --prefix osrm-backend)"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium extract --bbox=-88.83,35.56,-87.40,36.10 --strategy=complete_ways --set-bounds --output "$OSRM_TASK/jackson-dickson.osm.pbf" "$OSRM_TASK/us-261028.osm.pbf"
taskpolicy -b nice -n 19 python scripts/osrm_native.py prepare --data-dir "$OSRM_TASK/tn-native" --input "$OSRM_TASK/jackson-dickson.osm.pbf" --link-input
taskpolicy -b nice -n 19 python scripts/osrm_native.py extract --data-dir "$OSRM_TASK/tn-native" --profile "$OSRM_PREFIX/share/osrm-backend/profiles/car.lua"
taskpolicy -b nice -n 19 python scripts/osrm_native.py partition --data-dir "$OSRM_TASK/tn-native"
taskpolicy -b nice -n 19 python scripts/osrm_native.py customize --data-dir "$OSRM_TASK/tn-native"
taskpolicy -b nice -n 19 python scripts/osrm_native.py serve --data-dir "$OSRM_TASK/tn-native"
```

If the prepared graph already exists, use only the `serve` command. In another terminal, start the API against that graph:

```sh
OSRM_BASE_URL=http://127.0.0.1:5050 OSRM_DATASET_VERSION=tn-jackson-dickson-26-10-0-20261028 python manage.py runserver 127.0.0.1:8000 --noreload --nothreading
```

Use the Jackson–Dickson API example above. Change the dataset version if the graph changes. Stop only this task's foreground processes when finished. The SD card adds storage, not RAM; nationwide preprocessing feasibility remains open.

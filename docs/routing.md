# Routing configuration and local OSRM

Commands below run from the repository root. Back to the [README](../README.md).

## OSRM settings and road snapping

OSRM: public demo `https://router.project-osrm.org` by default (no SLA); local OSRM via `OSRM_BASE_URL`; no automatic fallback. Configure `OSRM_BASE_URL`, `OSRM_PROFILE`, `OSRM_DATASET_VERSION`, `OSRM_TIMEOUT`; default profile `driving`, timeout 20 seconds.

Road snapping is limited to 1000 m for endpoints and 100 m for fuel stops; coincident points share the smallest applicable limit. Configure positive finite `OSRM_ENDPOINT_RADIUS_METERS` and `OSRM_STOP_RADIUS_METERS`. A missing nearby road means coverage is unavailable.

Default corridor 5 miles; configure `FUEL_CORRIDOR_MILES`. The corridor must be positive and finite; spatial lookup scales with corridor and latitude and wraps across the antimeridian.

The public demo is optional and has no SLA. Public demo request scheduling is per process; use one process or coordinate rate limits externally. With `OSRM_BASE_URL` pointing to a local OSRM, application routing fails when local OSRM is unavailable; there is no silent public fallback.

## Cache invalidation

The plan cache includes a persisted station-data digest and planning/provider settings. Station `save`, `delete`, queryset `update`/`delete`, `bulk_create`, `bulk_update`, and the supplied imports invalidate the digest transactionally. For raw SQL or fixture paths that bypass these ORM methods, stop serving requests and run the following after changes and before resuming:

```sh
python manage.py shell -c "from planner.models import invalidate_station_dataset; invalidate_station_dataset('default')"
```

Any candidate verification-provider failure prevents plan-cache reuse; the result stays available through its map URL. Change `OSRM_DATASET_VERSION` whenever the graph changes to invalidate route and plan caches.

## Explicit public validation

Public routing is the default. The public demo has no SLA and requires per-process rate scheduling. Import bundled evidence first. This process example sets the demo explicitly.

```sh
OSRM_BASE_URL=https://router.project-osrm.org OSRM_DATASET_VERSION=public-demo python manage.py runserver 127.0.0.1:8001 --noreload --nothreading
```

Set Postman `baseUrl` to `http://127.0.0.1:8001` for this process. Comparison: station `63724` (Jackson, TN) to `67420` (Dickson, TN), starting fuel `0`. Long trip: `63724` to `1516` (Amarillo, TX), starting fuel `0`. The Jackson–Dickson corridor graph can serve the comparison locally; the long trip uses public routing or a covering local graph. No automatic fallback. Public operator location license remains unknown.

## Local OSRM regional trial (Docker)

District of Columbia extract only. Does not cover US routes. Evaluate resource needs before any larger dataset. With `OSRM_BASE_URL` pointing to local OSRM, application routing fails when local OSRM is unavailable; no silent public fallback.

Before download, preprocessing, or startup: inspect CPU and memory pressure, free disk, competing builds/tests, Docker availability, and port 5050. Wait if contended. Image download also needs disk and network. Preprocessing and server use separate containers; each limited to one CPU and 1 GiB. The limit may be insufficient; report failure, do not assume coverage. Docker and native servers map graph files with `--mmap` and disable `ROUTE_STEPS`; route geometry remains enabled. Mapping reduces graph heap allocation, not total memory demand, and does not make USA preprocessing feasible. Run stages sequentially. Normal container output remains enabled.

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

Run the DC readiness `curl` from the Docker trial section above in another terminal. Stop only this task's foreground routing process when finished. `taskpolicy` and `nice` lower scheduling priority; they do not cap total memory or CPU. Do not run native and Docker services on port 5050 together. Change `OSRM_DATASET_VERSION` after any graph rebuild.

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

Use the Jackson–Dickson request from the README (station `63724` to `67420`, `start_fuel_gallons` 0). Change the dataset version if the graph changes. Stop only this task's foreground processes when finished. The SD card adds storage, not RAM; nationwide preprocessing feasibility remains open.

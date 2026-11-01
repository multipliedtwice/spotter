# Station evidence

Commands below run from the repository root. Back to the [README](../README.md). Source provenance: [data/SOURCES.md](../data/SOURCES.md).

## Required data and CSV formats

Required: `data/us_boundary.geojson`, state FeatureCollection with Polygon/MultiPolygon geometry and unique `STUSPS` for every imported station state.

Gazetteer CSV: `name,state,latitude,longitude`.

Evidence CSV: `station_id,address,city,state,latitude,longitude,matched_name,matched_address,source`. Evidence import replaces the previous set. Each point must lie within its source state Census boundary.

## Import checks

Independent per-station evidence is required: particular name or store number, plus address or highway and exit. Import checks source name or store number and meaningful name token; exact address or same highway type/number and exit. Evidence source and matched values are retained. These consistency checks cannot prove coordinates identify the correct physical station; review sources independently. Unresolved records are retained and excluded from plans.

## Review sample

```sh
python manage.py sample_stations sample.csv --count 100
```

## Geoapify evidence source (paused)

Do not run Geoapify requests while paused.

Set `GEOAPIFY_API_KEY` in the environment. Do not put the key in files or command arguments. Synchronous geocoding: at most two requests/second; one request costs one credit according to [Geoapify documentation](https://apidocs.geoapify.com/docs/geocoding/). Check current account quota before choosing budgets.

```sh
python manage.py sample_stations sample.csv --count 100
python manage.py resolve_geoapify --sample sample.csv --cache data/source_geoapify.json --output data/sample_evidence.csv --max-requests 100 --credit-budget 100
```

Omit `--sample` for all station groups. Required: both budgets. Same cache + new budget resumes incomplete work. If the output exists, choose another path or explicitly add `--replace-output`; replacement writes the current selection only. Budget exhausted: output is partial; the command reports groups awaiting requests. Cache stores selected provider response fields, no key. Results lacking particular station identity and address/exit proof stay unresolved. Name, city, or confidence alone is insufficient. Source row IDs in evidence use OPIS ID plus one-based row position inside the imported group. Review evidence sources before importing. `--replace-output` may discard previous output; import also replaces the prior evidence set. Verify completeness before either operation.

Resolver: the first query includes the source address. If there is no independently matched evidence, the second query uses name and city; the address still must come from the result. Each uncached query uses one request and one credit. `--sample` accepts source CSV or `sample_stations` columns. Geoapify store references, place ID and available datasource attribution/license are retained. Check source licenses and attribution before use.

## Offline Love's operator evidence

Provide an operator store asset as `data/source_loves_locations.json` with a `stores` array from [Love's store locator](https://www.loves.com/api/fetch_stores). Keep store number, coordinates, address, city, state, highway, exit, name and store-type fields only. No prices or contact fields. Resolver makes no network calls.

```sh
python manage.py resolve_loves --input data/source_loves_locations.json --output local/loves/evidence.csv --unresolved local/loves/unresolved.csv
```

Requires operator Love's store flag, source Love's name and store number, matching city and state, independently matching address or typed highway and exit/mile marker, and a point inside the Census state boundary. Exit and mile markers stay distinct; ambiguous road/marker pairings remain unresolved. Ambiguous and unmatched groups remain unresolved. Operator data license unknown; review terms before use. Output contains no prices. Import replaces the existing evidence set; merge reviewed output with existing evidence first. Prices remain from supplied CSV, not operator data.

## Offline OSM station evidence

Install OSM resolver requirements, including `osmium==4.3.2`, with `python -m pip install --only-binary=:all: -r requirements-osm.txt`. Import source stations first. Supply an existing local PBF; no network requests. Run only after resource and disk preflight.

```sh
python manage.py resolve_osm --pbf local/osrm/region.osm.pbf --output local/osm/evidence.csv --unresolved local/osrm/unresolved.csv
```

Use sorted extract ≤256 MiB. Nodes must precede ways. Fuel/site geometry needs complete references; motorway context needs junction coordinates and way membership only. Do not feed national raw PBF to `resolve_osm`. One decode worker, bounded queue. Compressed-size limit is not a memory cap. City gazetteer required when OSM city absent.

Fresh preparation only; choose new output paths. Check CPU, memory, disk and competing work before every stage. macOS commands below lower priority; other hosts use equivalent background scheduling. Source file stays intact.

```sh
OSM_SOURCE=/path/to/us.osm.pbf
OSM_WORK=local/osm-stations
mkdir -p "$OSM_WORK"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium tags-filter "$OSM_SOURCE" nwr/amenity=fuel --output "$OSM_WORK/fuel.osm.pbf"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium tags-filter -R "$OSM_SOURCE" n/highway=motorway_junction w/highway=motorway,motorway_link --output "$OSM_WORK/roads.osm.pbf"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium merge "$OSM_WORK/fuel.osm.pbf" "$OSM_WORK/roads.osm.pbf" --output "$OSM_WORK/fuel-and-roads.osm.pbf"
```

Fuel nodes, closed ways, multipolygon relations supported. Areas use interior point, including holes. Street match normalizes common abbreviations. Exit match requires junction node in typed motorway way and fuel point within one mile. Junction `ref` or legacy `old_ref` (single exit number only) can match source exit; legacy numbers cover renumbered states. City point screens only; source state polygon required. Raw tags, geometry, junction, road ref and membership retained in `osm_evidence`. Import rechecks context. Conflicting refs and ambiguous sites rejected. Review evidence before import. Import replaces previous evidence; merge reviewed existing Love's rows first. Prices come from source CSV. OSM data: [ODbL attribution](https://www.openstreetmap.org/copyright).

## Business sites

For national input, select only named convenience shops, motorway services and retail areas whose canonical identity matches a source station. Selector streams input without node cache. Check resources and free disk before each command. Output paths must be new. `getid -r` reads raw input again to supply referenced geometry. Merge the resulting site file with the fuel and junction extract before resolution.

```sh
taskpolicy -b nice -n 19 python manage.py select_osm_sites --pbf "$OSM_SOURCE" --output "$OSM_WORK/selected-sites.osm.pbf"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium getid -r -I "$OSM_WORK/selected-sites.osm.pbf" "$OSM_SOURCE" -o "$OSM_WORK/sites.osm.pbf"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium merge "$OSM_WORK/fuel-and-roads.osm.pbf" "$OSM_WORK/sites.osm.pbf" -o "$OSM_WORK/combined.osm.pbf"
taskpolicy -b nice -n 19 python manage.py resolve_osm --pbf "$OSM_WORK/combined.osm.pbf" --output "$OSM_WORK/evidence.csv" --unresolved "$OSM_WORK/unresolved.csv"
```

A business point without OSM fuel tag requires matching explicit store ref and independent street or typed exit proof. CSV supplies priced business role; OSM supplies site. A retail or services area can supply identity for a fuel point inside its geometry. Saved context retains both objects; import checks containment and matching again. An exact store ref takes priority over weaker candidate matches. Distinct sites remain unresolved. Review evidence and redistribution terms before use.

Intersections with two or more typed routes can match one junction. Same motorway way refs plus directly attached motorway-link `destination:ref` must prove every source route. State-coded route refs count as state routes only in that state. Optional source exit must match junction `ref` or a single legacy `old_ref`. OR, mile markers and single-route addresses without exits do not use this rule. Fuel point remains within one mile of junction. Saved ramp IDs, refs and node membership allow import recheck.

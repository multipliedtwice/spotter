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

Optional dependency: `python -m pip install --only-binary=:all: -r requirements-osm.txt`. Import source stations first. Supply an existing local PBF; no network requests. Run only after resource and disk preflight.

```sh
python manage.py resolve_osm --pbf local/osrm/region.osm.pbf --output local/osm/evidence.csv --unresolved local/osrm/unresolved.csv
```

Reads fuel nodes in one pass with one decode worker and a bounded two-item worker queue. Only fuel nodes reach the Python matcher. Requires OSM name or numeric store ref, address or highway and exit, city, and state tags. Matches source identity and independently tagged address. Multiple matches remain unresolved. Ways and relations are unsupported. Output source links identify OSM nodes; inspect evidence before import. Missing or ambiguous groups stay unresolved. Prices come only from the source CSV. OSM data: [ODbL attribution](https://www.openstreetmap.org/copyright).

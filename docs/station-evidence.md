# Station evidence

Commands below run from the repository root. Back to the [README](../README.md). Source provenance: [data/SOURCES.md](../data/SOURCES.md).

## Required data and CSV formats

Required: `data/us_boundary.geojson`, state FeatureCollection with Polygon/MultiPolygon geometry and unique `STUSPS` for every imported station state.

Gazetteer CSV: `name,state,latitude,longitude`.

Evidence CSV: `station_id,address,city,state,latitude,longitude,matched_name,matched_address,source`. Evidence import replaces the previous set. Each point must lie within its source state Census boundary.

## Import checks

Independent per-station evidence: particular name or store number plus address or highway and exit. User-approved primary-operator fallback permits exact numbered identity without confirmed source road; show operator street and label full source address unverified. Import rechecks raw record, point and ownership. Third-party directory, OSM, EPA and unnumbered records cannot use fallback. Unresolved records stay excluded.

## Review sample

```sh
python manage.py sample_stations sample.csv --count 100
```

## Geoapify evidence source

Coverage geocoding enabled. Use bounded requests and cache. Preserve accepted station evidence.

Set `GEOAPIFY_API_KEY` in the environment. Do not put the key in files or command arguments. Synchronous geocoding: at most two requests/second; one request costs one credit according to [Geoapify documentation](https://apidocs.geoapify.com/docs/geocoding/). Check current account quota before choosing budgets.

```sh
python manage.py sample_stations sample.csv --count 100
python manage.py resolve_geoapify --sample sample.csv --cache data/source_geoapify.json --output data/sample_evidence.csv --max-requests 100 --credit-budget 100
```

Omit `--sample` for all station groups. Required: both budgets. Same cache + new budget resumes incomplete work. If the output exists, choose another path or explicitly add `--replace-output`; replacement writes the current selection only. Budget exhausted: output is partial; the command reports groups awaiting requests. Cache stores selected provider response fields, no key. Results lacking particular station identity and address/exit proof stay unresolved. Name, city, or confidence alone is insufficient. Source row IDs in evidence use OPIS ID plus one-based row position inside the imported group. Review evidence sources before importing. `--replace-output` may discard previous output; import also replaces the prior evidence set. Verify completeness before either operation.

Resolver: the first query includes the source address. If there is no independently matched evidence, the second query uses name and city; the address still must come from the result. Each uncached query uses one request and one credit. `--sample` accepts source CSV or `sample_stations` columns. `--unresolved-only` excludes stations with both coordinates; use it to preserve accepted evidence. Cached responses can be replayed with zero request and credit budgets without an API key. Geoapify store references, place ID and available datasource attribution/license are retained. Check source licenses and attribution before use.

## Offline Love's operator evidence

Provide an operator store asset as `data/source_loves_locations.json` with a `stores` array from [Love's store locator](https://www.loves.com/api/fetch_stores). Keep store number, coordinates, address, city, state, highway, exit, name and store-type fields only. No prices or contact fields. Resolver makes no network calls.

`data/approved_named_plazas.json` permits only the listed Love's #176 Matfield Green source group and exact Cassoday operator record. Recheck I-35 mile 97, point and all source identities. Show operator postal city and plaza label; no general city alias.

```sh
python manage.py resolve_loves --input data/source_loves_locations.json --output local/loves/evidence.csv --unresolved local/loves/unresolved.csv
```

Requires operator Love's store flag, source Love's name and store number, matching city and state, independently matching address or typed highway and exit/mile marker, and a point inside the Census state boundary. Exit and mile markers stay distinct; ambiguous road/marker pairings remain unresolved. Complete route-only source addresses may use the approved primary-operator exception below. Those rows retain raw store fields and source URL in `operator_evidence`; import rechecks every supplied typed highway, identity, point, and unique store ownership. Generic HWY never implies US/SR. Ambiguous and unmatched groups remain unresolved. Operator data license unknown; review terms before use. Output contains no prices. Import replaces the existing evidence set; merge reviewed output with existing evidence first. Prices remain from supplied CSV, not operator data.

Optional `--pbf local/osm-stations/roads.osm.pbf`: compact sorted extract, at most 256 MiB; one decode worker. Raw operator point remains unchanged. Saved junction context must independently prove the source exit/intersection through motorway or numbered trunk junction, ramp-reference, membership, distance, and state checks. Import repeats validation. Evidence displays the published street, highway, and raw exit field; no invented marker label.

Tagged `motorway_junction` nodes on trunk ways require the exact published `ref`, way membership and complete source-road proof. Attached motorway/trunk link refs may support secondary routes. No at-grade or unnumbered trunk inference. Older compact extracts may omit trunk ways. Source: [OpenStreetMap motorway junction definition](https://wiki.openstreetmap.org/wiki/Tag:highway%3Dmotorway_junction).

Ten existing groups have explicit user approval in `data/approved_operator_locations.json`. Accept only exact approved group, unchanged operator point, exact store number/city/state and confirmed primary highway/exit. Context marks `approved_primary_exit: true`. Import rechecks the asset and raw operator record; stores `verification_scope: operator_identity_and_primary_exit` and the full source description in `unverified_source_address_details`. Extra source-road names or directional qualifiers remain unverified. Missing/changed/duplicate approvals reject this path. Other records retain strict checks.

## Offline OSM station evidence

Install OSM resolver requirements, including `osmium==4.3.2`, with `python -m pip install --only-binary=:all: -r requirements-osm.txt`. Import source stations first. Supply an existing local PBF; no network requests. Run only after resource and disk preflight.

```sh
python manage.py resolve_osm --pbf local/osrm/region.osm.pbf --output local/osm/evidence.csv --unresolved local/osrm/unresolved.csv
```

Use sorted extract ≤256 MiB. Nodes must precede ways. Fuel/site geometry needs complete references; junction context needs coordinates and way membership. Do not feed national raw PBF to `resolve_osm`. One decode worker, bounded queue. Compressed-size limit is not a memory cap. City gazetteer required when OSM city absent.

Joined fuel/site evidence: check every explicit city and state on both objects. Any source-locality conflict rejects match. Gazetteer fallback only when both omit city; site tags cannot hide conflicting fuel tags.

Fresh preparation only; choose new output paths. Check CPU, memory, disk and competing work before every stage. macOS commands below lower priority; other hosts use equivalent background scheduling. Source file stays intact.

```sh
OSM_SOURCE=/path/to/us.osm.pbf
OSM_WORK=local/osm-stations
mkdir -p "$OSM_WORK"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium tags-filter "$OSM_SOURCE" nwr/amenity=fuel --output "$OSM_WORK/fuel.osm.pbf"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium tags-filter -R "$OSM_SOURCE" n/highway=motorway_junction w/highway=motorway,motorway_link,trunk,trunk_link --output "$OSM_WORK/roads.osm.pbf"
taskpolicy -b nice -n 19 env OSMIUM_POOL_THREADS=1 OSMIUM_MAX_WORK_QUEUE_SIZE=2 osmium merge "$OSM_WORK/fuel.osm.pbf" "$OSM_WORK/roads.osm.pbf" --output "$OSM_WORK/fuel-and-roads.osm.pbf"
```

Fuel nodes, closed ways, multipolygon relations supported. Areas use interior point, including holes. Street match normalizes common abbreviations. Exit match requires junction node in typed motorway or trunk way and fuel point within one mile. Motorway junction `ref` or legacy `old_ref` (single exit number only) can match source exit; trunk requires exact `ref`. City point screens only; source state polygon required. Raw tags, geometry, junction, road ref and membership retained in `osm_evidence`. Import rechecks context. Conflicting refs and ambiguous sites rejected. Review evidence before import. Import replaces previous evidence; merge reviewed existing Love's rows first. Prices come from source CSV. OSM data: [ODbL attribution](https://www.openstreetmap.org/copyright).

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

## Independent directory records

Source: public [FindFuelStops directory](https://www.findfuelstops.com/). Detail-page `GasStation` JSON-LD supplies station name, address, city/state, country, coordinates, canonical source URL. Save selected facts only. Never import directory prices.

Asset shape: `{"records": [...]}`. Each record requires `source`, `name`, `address`, `city`, `state`, `latitude`, `longitude`; `country` may be absent. If present, country must be `US`. Source URL: `https://www.findfuelstops.com/truck-stop-NNNNNN`. Coordinates: finite numbers inside source state.

```sh
python manage.py resolve_directory --input data/source_directory_locations.json --output local/directory/evidence.csv --unresolved local/directory/unresolved.csv
```

Output paths must be new. Resolver makes no network calls. Require canonical station identity, no conflicting explicit store ref, matching city/state, point inside source state, plus independent street address or typed highway and exit/mile marker. `Ex` normalizes to `EXIT` for comparison. Street suffix abbreviations normalize; house numbers and directions stay distinct. Generic highway, name, city, or store number alone insufficient. Duplicate sources, ambiguous matches, shared ownership remain excluded.

Evidence carries raw selected source record in optional `directory_evidence` CSV column. Import rechecks source URL, identity, address, coordinates, state boundary, and unique source ownership. Existing CSVs without this column remain supported. Merge reviewed evidence with existing accepted rows before import; import replaces entire coordinate set. Keep unresolved source groups in denominator.

Directory redistribution license unknown. Preserve source URLs; review terms before public delivery.

## Public OPIS catalog sample

Source: official [Truckstop Spread Report sample](https://info.opisnet.com/hubfs/Product%20Campaigns/Truckstop%20Spread%20Report/OPIS%20Truckstop%20Spread%20Report%20Sample.pdf). Candidate asset: `{"records":[...]}`; each record exactly `id`, `name`, `address`, `address2`, `city`, `state`, `country`, `latitude`, `longitude`, `source`. Keep location fields only; exclude sample prices and contacts. Country: `USA`. Source URL: exact public sample PDF.

```sh
python manage.py resolve_directory --input data/source_opis_locations.json --output local/opis/evidence.csv --unresolved local/opis/unresolved.csv
```

Require numeric OPIS ID equal supplied source ID, canonical name without conflicting store numbers, exact normalized full `address2`, matching city/state, and raw point inside source state. No partial highway comparison; BUS/ALT and every other address token must remain equal. Coordinates copied from published catalog record. Raw record stays in `directory_evidence`; `place_id` retains catalog ID. Shared-PDF ownership key: source URL plus normalized record ID. FindFuelStops retains unique-URL ownership. Import rechecks both paths. Sample contains 29 records, never a national export. Merge reviewed evidence before replacing the coordinate set; redistribution terms remain unresolved.

## First-party operator records

Use normalized operator assets documented in `data/SOURCES.md`. No runtime provider calls. Each record keeps published identity, address, point, source URL. Store numbers normalized for ownership; namespaces prevent unrelated operators sharing a number from colliding. Pilot/One9 cross-brand aliases prohibited. Kwik Trip and QuikTrip stay distinct.

```sh
python manage.py resolve_pilot --input data/source_pilot_locations.json --output local/pilot/evidence.csv --unresolved local/pilot/unresolved.csv
python manage.py resolve_kwiktrip --input data/source_kwiktrip_locations.json --pbf local/osm-stations/roads.osm.pbf --output local/kwiktrip/evidence.csv --unresolved local/kwiktrip/unresolved.csv
python manage.py resolve_yesway --input data/source_yesway_locations.json --pbf local/osm-stations/roads.osm.pbf --output local/yesway/evidence.csv --unresolved local/yesway/unresolved.csv
python manage.py resolve_operator --input data/source_maverik_quiktrip_locations.json --pbf local/osm-stations/roads.osm.pbf --output local/operators/evidence.csv --unresolved local/operators/unresolved.csv
```

Output paths must be new. Optional PBF: compact sorted extract, at most 256 MiB. One decode worker. Junction coordinates, typed motorway/trunk refs, way membership, and attached ramp refs provide independent highway/exit proof. Exact numbered operator points may use a supporting motorway junction within five miles; trunk junctions and generic OSM matching retain a one-mile limit. Both paths require the source-state boundary and all applicable highway/exit checks. Operator coordinates remain operator coordinates; never label them OSM geometry.

Optional `--roads data/source_operator_roads.json`: raw OSM way asset, at most 64 MiB. Complete route-only source address required; exits, mile markers, alternatives, directional qualifiers and unsupported road expressions reject this path. Every typed source route must occur on nearby drivable road geometry. Closest road point must lie within one mile of the unchanged operator point and inside the source state. Business, alternate, bypass, spur and truck route refs excluded. Evidence retains raw selected way IDs, URLs, tags, node IDs and geometry in `operator_evidence.roads`; import rechecks them. Scope: `operator_identity_and_nearby_named_roads`. Station point always comes from the exact operator record.

Pilot Dealer may match Pilot and Flying J Dealer may match Flying J for the same explicit store number and city/state. Flying J source labels may use literal Travel Plaza, TravelPlaza or Fuel Stop. Express and One9 remain distinct. Pilot family shares operator-number ownership checks. Canonical location URLs may contain dots in the final slug.

Require exact chain/store number, matching city/state, point inside state and unique ownership. Prefer independent street/highway proof; identity-only fallback retains source address as unverified. Evidence city comparison normalizes punctuation, spacing, leading Saint/St. No alias between different cities. Runtime city lookup unchanged. Shared typed notation such as `I-80/94` means both I-80 and I-94; every supplied route must match. Never convert generic HWY into US/SR or infer a branch.

Explicit `US Hwy`, `US Highway`, and `US Route` normalize to `US`. Generic `Hwy` stays distinct. Exit/mile markers never broadcast across separate road clauses or to a road written after the marker.

Explicit `CR`/`County Road` and `FM`/`Farm to Market` remain distinct typed routes. Every recognized source route needs independent road proof, even when other source text is unsupported. Qualified alternate/business routes never become unqualified routes.

Literal name variants: `MAVERIK COUNTRY STORE` → `MAVERIK`; `ALLSUPS CONVENIENCE STORE` → `ALLSUPS`. No general business-suffix removal. Allsup's operator [homepage](https://allsups.com/) uses the full convenience-store name. Wyoming DOT's [licensed taxpayer list](https://www.dot.state.wy.us/files/live/sites/wydot/files/shared/Fuel_Tax_Administration/Licensed%20Taxpayer%20List/Licensed%20Taxpayer%20List%20Sorted%20by%20DBA.pdf) links Maverik Country Store names and numbered locations to Maverik Inc. These name variants never establish a particular station's address or coordinates; remaining identity/location checks still required.

Primary-operator exception: complete source address contains only typed highway(s), without street number or exit. Operator's published address/highway must independently confirm every supplied route. Exact numbered identity, city/state, boundary, and ownership checks remain mandatory. Third-party directory alone cannot use exception. Unknown location stays unresolved.

Evidence retains raw operator record and optional OSM junction or road ways in `operator_evidence`. Import repeats identity, address, coordinates, source URL, boundary, and ownership checks. Explicit coming-soon Yesway records excluded; absent status stays unknown. Coordinates never establish a live fuel-product or opening guarantee.

Yesway/Allsup's: native `store` label supplies the published store number. `acf.internal_store_code` stays raw metadata, never a number alias. Missing status or fuel-card fields remain absent; temporary-closure and non-store labels excluded.

Merge reviewed outputs with existing accepted evidence before import. Preserve existing accepted coordinates unless separately reviewed. Source prices always come from assessment CSV. Do not claim full coverage from retrieved-record counts.

## Circle K operator records

Public endpoint: `https://api.circlek.com/us/ngrp-store-locator/v1/stations/{id}`. Source asset: `{"source":"https://api.circlek.com/us/ngrp-store-locator/v1/stations","stores":[...]}`. Per store: exactly `id`, `brand`, `publicBrand`, `latitude`, `longitude`, `address`, `source`. Address: exactly `street`, `city`, `state`, `postalCode`, `country`. Keep selected published fields; exclude prices and contacts.

```sh
python manage.py resolve_circlek --input local/circlek/source.json --pbf local/osm-stations/roads.osm.pbf --output local/circlek/evidence.csv --unresolved local/circlek/unresolved.csv
```

Require exact source brand and explicit number matching published API station ID, canonical per-ID URL, `CIRCLEK` brand fields, US address, matching city/state, finite point inside state and unique ownership. Prefer independent street/highway proof; identity-only fallback labels source road unverified. API ID retained as `place_id`; display name `Circle K` never invents a published numbered name. Raw selected record stays in `operator_evidence`; import rechecks it. Missing or changed IDs stay unresolved. No identifier aliases. Resolver makes no network calls.

OSM Circle K candidates with seven-digit source numbers reject a conflicting seven-digit store ID in an allowlisted official Circle K website URL. Check both fuel and containing-site tags. Short legacy numbers and other brands remain separate namespaces; no assumed equivalence to current API IDs.

OSM Kwik Trip/Kwik Star: official locator URL store ID must match source number. Check fuel and site. Compound junction: every source route and exit must match; one matching exit alone insufficient.

## TA, TA Express, Petro

Source: `data/source_ta_locations.json`. Published location JSON-LD only; no prices or contacts.

```sh
python manage.py resolve_ta --input data/source_ta_locations.json --pbf local/osm-stations/roads.osm.pbf --output local/ta/evidence.csv --unresolved local/ta/unresolved.csv
```

Numbered source: exact chain and number; identity-only fallback labels source road unverified. Unnumbered source: exact full branch name, city/state, street or highway exit proof; no identity-only, route-only or road-geometry-only fallback. Both require state boundary and unique ownership. Compound junction needs every source route. Changed numbers stay unresolved. Petro Serve USA separate. Import rechecks raw operator record. No network calls.

## Road Ranger

```sh
python manage.py resolve_roadranger --input data/source_roadranger_locations.json --output local/roadranger/evidence.csv --unresolved local/roadranger/unresolved.csv
```

Pair billing and locator records by unique full street, city and state; compare ZIP when both publish it. Billing supplies store number and optional OPIS code; locator supplies point. Exact source number, city/state and matching published OPIS code when present required. Unique store number, address and point required. Identity-only evidence displays operator address and labels CSV road unverified. Raw fragments and both source URLs retained; import rechecks pair. `ROADRANGER` and `ROAD RANGERS` are literal source spelling variants. No network calls.

Love's literal source names `LOVES TRAVEL STOPS` and `LOVES TRAVE STOP` mean `LOVES`; no general fuzzy name match.

## RaceTrac, Rutter's, Thorntons

```sh
python manage.py resolve_racetrac --input data/source_racetrac_locations.json --output local/racetrac/evidence.csv --unresolved local/racetrac/unresolved.csv
python manage.py resolve_rutters --input data/source_rutters_locations.json --output local/rutters/evidence.csv --unresolved local/rutters/unresolved.csv
python manage.py resolve_thorntons --input data/source_thorntons_locations.json --output local/thorntons/evidence.csv --unresolved local/thorntons/unresolved.csv
```

Require exact source brand and number, city/state, published point in state and unique store/point ownership. RaceTrac and RaceWay stay distinct. Prefer street or road proof; identity-only fallback labels CSV address unverified. Raw selected fields retained for import recheck. RaceTrac branch name is not a numbered business name. No network calls.

Typed OSM routes with `ALT`, `ALTERNATE`, `BUS`, `BUSINESS`, `BYPASS`, `BYP`, `SPUR` or `TRUCK` qualifiers do not prove the unqualified route.

## Pump & Pantry

```sh
python manage.py resolve_pump_pantry --input data/source_pump_pantry_locations.json --output local/pump-pantry/evidence.csv --unresolved local/pump-pantry/unresolved.csv
```

Require exact numbered brand, city/state, source URL, published point inside state and unique store/point ownership. Keep nested raw locator record. Identity-only fallback labels CSV address unverified; import rechecks source and point. No derived source crosswalk or network call.

## SunStop, Toot'n Totum, Royal Farms

```sh
python manage.py resolve_sunstop --input data/source_sunstop_locations.json --output local/sunstop/evidence.csv --unresolved local/sunstop/unresolved.csv
python manage.py resolve_tootntotum --input data/source_tootntotum_locations.json --output local/toot/evidence.csv --unresolved local/toot/unresolved.csv
python manage.py resolve_royalfarms --input data/source_royalfarms_locations.json --output local/royal/evidence.csv --unresolved local/royal/unresolved.csv
```

Exact numbered source identity, city/state, boundary and unique ownership required. Raw published fields retained. Identity-only fallback labels CSV address unverified. Royal Farms display name generic; number remains separate. No network calls.

FindFuelStops may use `resolve_directory --pbf` with a compact OSM junction extract. Directory point stays unchanged; matching source name and full typed junction proof within one mile required. If source has a store number, published number must match. Multiple valid junctions: nearest proof, stable ID tie-break. OPIS PDF matching stays exact-address only.

## 7FLEET

```sh
python manage.py resolve_sevenfleet --input data/source_sevenfleet_locations.json --output local/sevenfleet/evidence.csv --unresolved local/sevenfleet/unresolved.csv
```

Match exact retailer prefix and number from published site name, matching marker title, city/state, state boundary and unique number/point. Preserve raw table brand; it may differ from retailer prefix. `STRIPES 7FLEET` source spelling means Stripes. Never map old numbers to different current numbers. Identity-only fallback labels CSV address unverified. No network calls.

## Tex-Best

```sh
python manage.py resolve_texbest --input data/source_texbest_locations.json --output local/texbest/evidence.csv --unresolved local/texbest/unresolved.csv
```

Require exact numbered brand, unambiguous published street/city/state, point in state, unique ownership and `coming_soon=false`. Identity-only fallback labels CSV address unverified. Ambiguous full-address parsing stays unresolved. No network calls.

## ASAP General Store

```sh
python manage.py resolve_asap --input data/source_asap_locations.json --output local/asap/evidence.csv --unresolved local/asap/unresolved.csv
```

Require exact numbered source brand, published pin, unambiguous street/city/state and unique store/point. Blank pin address needs same-number detail card. Identity-only fallback labels CSV address unverified. No operating-status claim or network call.

## Huck's

```sh
python manage.py resolve_hucks --input data/source_hucks_locations.json --output local/hucks/evidence.csv --unresolved local/hucks/unresolved.csv
```

Published location title supplies number; map ID is not a store number. Require exact source brand/number, city/state, point in state and unique store/point. Publisher names Huck's Food and Fuel and Huck's Market; source-only literal forms accepted. Co-branded multiple-number names stay unresolved. Identity-only fallback labels CSV address unverified. No network call.

## Jet Food

`python manage.py resolve_jetfood --input data/source_jetfood_locations.json --output local/jetfood/evidence.csv --unresolved local/jetfood/unresolved.csv`

Match published listing and marker IDs. Store number comes from listing label. Parse city and state only from published address. Require exact brand, number, city/state, point in state and unique store/point. Identity-only fallback labels CSV road details unverified.

Directory city suffix: numbered Quick Fuel and Toot N Totum names may use the exact published city suffix. Require matching number, city/state and independent address or highway evidence.

## Good 2 Go

```sh
python manage.py resolve_good2go --input data/source_good2go_locations.json --output local/good2go/evidence.csv --unresolved local/good2go/unresolved.csv
```

Require exact brand and number, matching published address fields, city/state, point in state and unique store/point. Identity-only fallback labels CSV road details unverified. Co-branded names with conflicting numbers stay unresolved. No network call.

## Spinx

```sh
python manage.py resolve_spinx --input data/source_spinx_locations.json --output local/spinx/evidence.csv --unresolved local/spinx/unresolved.csv
```

Require exact numbered source brand, published title, matching post/map IDs, street/city/state, point in state and unique store/point. Source number may follow a space or `#`. Permit literal source annotation `(DISCOUNT AVAILABLE)`. Identity-only fallback labels CSV road details unverified. No network call.

## Pete's

```sh
python manage.py resolve_petes --input data/source_petes_locations.json --output local/petes/evidence.csv --unresolved local/petes/unresolved.csv
```

Require matching marker and popup titles, marker ID in published popup endpoint, numbered source brand, published Kansas postal address, point in state and unique store/point. Source number may follow a space or `#`. Identity-only fallback labels CSV road details unverified. No network call.

## Duck Thru and Dandy

```sh
python manage.py resolve_duckthru --input data/source_duckthru_locations.json --output local/duckthru/evidence.csv --unresolved local/duckthru/unresolved.csv
python manage.py resolve_dandy --input data/source_dandy_locations.json --output local/dandy/evidence.csv --unresolved local/dandy/unresolved.csv
```

Require published numbered store label, exact source brand/number, city/state, point in state and unique store/point. Duck Thru title and detail path must agree. Locator IDs are not store numbers. Identity-only fallback labels CSV road details unverified.

Kwik Trip #748 Barron: only the two source groups in `data/approved_shared_operator_locations.json` may share the listed published point. Keep separate source groups and prices. Recheck both owners and native store.

## AMBEST network directory

```sh
python manage.py resolve_ambest --input data/source_ambest_locations.json --intersections data/source_ambest_intersections.json --output local/ambest/evidence.csv --unresolved local/ambest/unresolved.csv
```

Require full source business name and number, city/state, unique native record and point in state. Require full street or typed road/marker proof, or complete typed intersection on connected OSM ways within one mile. No directory identity-only fallback or facility-status claim. Import rechecks native asset, ownership and raw OSM evidence.

Road proof must cover all source location details. Unknown cross streets, untyped numbers and route qualifiers cannot disappear. In Wisconsin, explicit `CR-` letter references and `CTH` letter references use the same county-highway namespace. Sources: [WisDOT style guide](https://wisconsindot.gov/Pages/doing-bus/eng-consultants/cnslt-rsrces/tools/style.aspx), [Winnebago County highway permits](https://www.winnebagocountywi.gov/392/Permits---County-Highways).

Evidence city comparison treats only Mount Juliet and Mt. Juliet as the same spelling. No general Mount/Mt city alias. Operator evidence: Georgia Port Wentworth and Pt. Wentworth are equivalent; no general Port/Pt alias. Source: [Port Wentworth council packet](https://portwentworthga.gov/wp-content/uploads/2024/04/04-18-2024-Regular-City-Council-Agenda-Packet.pdf). Source: [City of Mt. Juliet records](https://www.mtjuliet-tn.gov/223/Records-Court-Unit).

Primary operator city spelling: WY Fort Bridger = Ft. Bridger; AR North Little Rock = N. Little Rock. No general Ft/Fort or N/North alias. State and all other proof still required. Sources: [Wyoming history](https://www.wyo.gov/about-wyoming/wyoming-history), [Arkansas published address list](https://www.transform.ar.gov/wp-content/uploads/Navitus-List.pdf).

Exit suffix `144-B` may compare as `144B`; ranges stay unsupported. Balanced parentheses around an explicit typed road preserve that required road. Unknown parenthetical text and qualified route branches remain distinct.

NE only: explicit `N-14` means SR-14. Other N routes and other states stay unsupported. Qualified routes stay distinct; plain routes sharing a way with an unrelated qualified route remain usable. Source: [NDOT highway reference log](https://govdocs.nebraska.gov/epubs/R6000/S002-2024.pdf).

## Onvo published branches

```sh
python manage.py resolve_onvo --input data/source_onvo_locations.json --output local/onvo/evidence.csv --unresolved local/onvo/unresolved.csv
```

Require the complete specific branch name, matching city/state, every source road and exit, unique published location and point in state. Retain published street and raw facts; display published street under `operator_branch_and_address`. No inferred store number or identity-only fallback. Onvo Express stays distinct.

## WEX network directory

```sh
python manage.py resolve_wex --input data/source_wex_locations.json --junctions data/source_wex_junctions.json --intersections data/source_wex_intersections.json --pbf local/roads.osm.pbf --output local/wex/evidence.csv --unresolved local/wex/unresolved.csv
```

Require Casey's numbered source identity, exact native brand and number, city/state, unique native ID and point in state. Other businesses: every source name must match the full native business name after case, whitespace and punctuation normalization; preserve every letter and digit. Native fuel brand does not prove identity. Require complete independent street or road proof. Optional PBF: local compact extract, at most 256 MiB; one decode worker. WEX site ID is not OPIS. No directory identity-only fallback. Import rechecks the complete native asset and raw road evidence.


## Parker's

```sh
python manage.py resolve_parkers --input data/source_parkers_locations.json --output local/parkers/evidence.csv --unresolved local/parkers/unresolved.csv
```

Require matching numbered heading and detail name, native directions point, exact source brand/number, city/state, state boundary and unique store/point. Reject malformed catalog. Identity-only: show operator street; mark CSV road details unverified. No city aliases.


## Kent Kwik

```sh
python manage.py resolve_kentkwik --input data/source_kentkwik_locations.json --output local/kentkwik/evidence.csv --unresolved local/kentkwik/unresolved.csv
```

Bind popup ID, heading and coordinates to native marker. Hold owners of duplicate Kent numbers or points. Require exact source brand/number, city/state and state boundary. Identity-only: show operator street; mark CSV road details unverified. No city aliases.

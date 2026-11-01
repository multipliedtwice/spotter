# Source assets

- `gazetteer.csv`: US Census 2026 National Places Gazetteer. Representative city points; never station points. Puerto Rico excluded. Geographic-name suffixes removed for city lookup.
  Override: Boston MA and San Francisco CA. Census points (42.332735,-71.013513 and 37.727239,-123.032229) sit in water outside cartographic boundary. Replaced with Census Geocoder city hall address matches (Public_AR_Current, checked 2026-11-01): 1 CITY HALL AVE Boston -> 42.357793,-71.059196; 1 DR CARLTON P GOODLETT PL San Francisco -> 37.778536,-122.41831.
  Source: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip
- `us_boundary.geojson`: US Census 2025 state cartographic boundaries, 1:500,000 KML converted to GeoJSON. 50 states + DC. Territory features excluded. Generalized boundary; near-border/coast precision limited.
  Source: https://www2.census.gov/geo/tiger/GENZ2025/kml/cb_2025_us_state_500k.zip
- `station_sample.csv`: supplied assessment rows, selected across US states, chains, exit/street/intersection address forms. Source prices unchanged.
- `station_evidence.csv`: independently identified operator locations. Each row links source station group to matched name/store number, address/exit, coordinates, public source URL. Prices always from supplied CSV.
- `pilot_unresolved.csv`: candidate Pilot records. Independent address/exit evidence required before eligibility; retained coordinates and source links alone insufficient. Excluded from planning.
- `source_loves_locations.json`: public operator locator metadata, restricted to store number, coordinates, address, city/state, highway/exit, store type. Operator prices and contacts excluded. Source fields support independent identity/location matching; never replace supplied CSV prices.
  Source: https://www.loves.com/api/fetch_stores
  Sample corroboration: https://www.loves.com/locations/il/atkinson/loves-travel-stop-atkinson-766
- `osm_evidence.csv`, `osm_unresolved.csv`: offline results from the local Geofabrik US OSM PBF. The strict resolver reads fuel nodes only; ways and relations are excluded. It requires independently matched station identity and address or road marker. Unmatched and ambiguous groups remain unresolved. Source: https://download.geofabrik.de/north-america/us.html
- Operator location license unknown. Store identity and location only; no prices.
- Geoapify response assets: retain independent returned fields + source provenance; no API key. OSM-derived data requires OpenStreetMap attribution and applicable ODbL terms.
  Terms: https://www.openstreetmap.org/copyright

Station coordinates identify source-backed locations. No live operating-status or fuel-product guarantee. Assessment CSV has no fuel-grade field or price date.

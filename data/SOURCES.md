# Source assets

- `gazetteer.csv`: US Census 2026 National Places Gazetteer. Representative city points; never station points. Puerto Rico excluded. Geographic-name suffixes removed for city lookup.
  Override: Boston MA and San Francisco CA. Census points (42.332735,-71.013513 and 37.727239,-123.032229) sit in water outside cartographic boundary. Replaced with Census Geocoder city hall address matches (Public_AR_Current, checked 2026-11-01): 1 CITY HALL AVE Boston -> 42.357793,-71.059196; 1 DR CARLTON P GOODLETT PL San Francisco -> 37.778536,-122.41831.
  Override: 19 more coastal places whose Census points sit in water outside cartographic boundary use USGS GNIS Populated Place primary points (DomesticNames state text files, downloaded 2026-11-01): Chignik AK 1400269, Klawock AK 1423100, Valdez AK 1412465, Coronado CA 1660513, Manhattan Beach CA 1660985, Monterey CA 1659762, Santa Monica CA 1652792, South San Francisco CA 277618, Niantic CT 209276, Stonington CT 211209, Tokeneke CT 212575, Atlantic Beach FL 277982, Dunedin FL 281860, Neptune Beach FL 287587, Yankeetown FL 293564, Portland ME 573692, Grand Marais MI 627096, Keansburg NJ 882484, Ocracoke NC 1021718. Each point checked inside boundary and within 72 m of OSRM road. Full scan after override: no gazetteer point outside boundary.
  GNIS source: https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/
  Source: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip
- `us_boundary.geojson`: US Census 2025 state cartographic boundaries, 1:500,000 KML converted to GeoJSON. 50 states + DC. Territory features excluded. Generalized boundary; near-border/coast precision limited.
  Source: https://www2.census.gov/geo/tiger/GENZ2025/kml/cb_2025_us_state_500k.zip
- `station_sample.csv`: supplied assessment rows, selected across US states, chains, exit/street/intersection address forms. Source prices unchanged.
- `station_evidence.csv`: independently identified operator locations. Each row links source station group to matched name/store number, address/exit, coordinates, public source URL. Prices always from supplied CSV.
- `pilot_unresolved.csv`: candidate Pilot records. Independent address/exit evidence required before eligibility; retained coordinates and source links alone insufficient. Excluded from planning.
- `source_loves_locations.json`: public operator locator metadata, restricted to store number, coordinates, address, city/state, highway/exit, store type. Operator prices and contacts excluded. Source fields support independent identity/location matching; never replace supplied CSV prices.
  Source: https://www.loves.com/api/fetch_stores
  Sample corroboration: https://www.loves.com/locations/il/atkinson/loves-travel-stop-atkinson-766
- `osm_evidence.csv`, `osm_unresolved.csv`: station crosswalk and unresolved source groups from local Geofabrik US OSM data. Fuel nodes, closed ways and multipolygon relations supported. Named retail/services areas may identify contained fuel features. Other business sites require exact source store reference. Canonical identity plus street or typed highway exit/intersection evidence required; ambiguous groups stay unresolved. Prices remain from assessment CSV. `osm_evidence` retains original tags, geometry, and supporting site/junction/road/ramp references for import checks. Source: https://download.geofabrik.de/north-america/us.html
- `station_evidence.csv`: merged accepted evidence. Existing operator coordinates retained when OSM also matches a group. OSM unresolved rows may already have operator evidence; their count differs from total unlocated stations.
- Operator location license unknown. Store identity and location only; no prices.
- Geoapify response assets: retain independent returned fields + source provenance; no API key. OSM-derived data requires OpenStreetMap attribution and applicable ODbL terms.
  Terms: https://www.openstreetmap.org/copyright

Station coordinates identify source-backed locations. No live operating-status or fuel-product guarantee. Assessment CSV has no fuel-grade field or price date.

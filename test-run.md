# Latest full suite

- Date: 2026-11-01.
- Command: `taskpolicy -b nice -n 19 env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python manage.py test`
- Result: PASS. 137 tests; 0 failures, 0 errors, 0 skips. Includes legacy-exit `old_ref` resolver and import-validation tests.
- Scope: complete Django discovery; no filters or fail-fast.
- Source: `/Users/danilt/spotter.ai`; Git `61ad6448b2fecdb92f3cdf45c3a6230ca1851088` plus uncommitted changes in `data/osm_evidence.csv`, `data/osm_unresolved.csv`, `data/station_evidence.csv`, `planner/core.py`, `planner/evidence.py`, `planner/locations.py`, `planner/management/commands/load_data.py`, `planner/management/commands/resolve_osm.py`, `planner/planning.py`, `planner/providers.py`, `planner/tests/test_core.py`, `planner/tests/test_imports.py`, `planner/tests/test_osm.py`, `planner/tests/test_search.py`, `planner/tests/test_views.py`, `planner/views.py`, and `postman_collection.json`; untracked source `planner/management/commands/select_osm_sites.py` and `planner/osm_evidence.py`. Requirements and test settings unchanged; unrelated documentation excluded.
- Configuration: `fuelroute.settings`; Django 6.1.2; Python 3.13.2; osmium 4.3.2; SQLite test database; providers mocked; tiny local OSM fixtures; gazetteer regression reads bundled `data/gazetteer.csv` and `data/us_boundary.geojson`.

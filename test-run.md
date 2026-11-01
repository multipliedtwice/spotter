# Latest full suite

- Date: 2026-11-02.
- Command: `taskpolicy -b nice -n 19 env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python manage.py test`
- Result: PASS. 140 tests; 0 failures, 0 errors, 0 skips. Includes two cache-hit regressions: coordinate input, and station_id input with zero starting fuel (plan reused, no new routing call, no unbounded station query, station_id revalidation and zero-fuel normalization still run).
- Scope: complete Django discovery; no filters or fail-fast.
- Source: `/Users/danilt/spotter.ai`; Git `4758c9e43f75443d36bc763869146d597419862e` plus uncommitted changes in `planner/views.py`, `planner/tests/test_views.py`, `postman_collection.json`. Requirements and test settings unchanged.
- Configuration: `fuelroute.settings`; Django 6.1.2; Python 3.13.2; osmium 4.3.2; SQLite test database; providers mocked; tiny local OSM fixtures; gazetteer regression reads bundled `data/gazetteer.csv` and `data/us_boundary.geojson`.

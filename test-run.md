# Latest full suite

- Date: 2026-11-01.
- Command: `taskpolicy -b nice -n 19 env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python manage.py test`
- Result: PASS. 138 tests; 0 failures, 0 errors, 0 skips. Includes zero-margin variant regression (both range-margin variants ranked within the three-call budget).
- Scope: complete Django discovery; no filters or fail-fast.
- Source: `/Users/danilt/spotter.ai`; Git `7c641eae06b1238f8f70cc55a7e617af61132a95` plus uncommitted changes in `planner/planning.py`, `planner/tests/test_search.py`, `planner/tests/test_views.py`; untracked `planner/tests/helpers.py`. Requirements and test settings unchanged.
- Configuration: `fuelroute.settings`; Django 6.1.2; Python 3.13.2; osmium 4.3.2; SQLite test database; providers mocked; tiny local OSM fixtures; gazetteer regression reads bundled `data/gazetteer.csv` and `data/us_boundary.geojson`.

# Latest full suite

- Date: 2026-10-31.
- Command: `taskpolicy -b nice -n 19 .venv/bin/python manage.py test`
- Result: PASS. 98 tests; 0 failures, 0 errors, 0 skips.
- Scope: complete Django discovery; no filters or fail-fast.
- Source: `/Users/danilt/spotter.ai`; unversioned local workspace, no Git revision available. Includes public OSRM default, failed-leg repair, optional starting fuel, deduplicated simplified response geometry, bounded-segment simplifier, legacy map normalization, 1e-3 display tolerance in plan cache identity.
- Configuration: `fuelroute.settings`; Django 6.1.2; Python 3.13.2; SQLite test database; providers mocked.

# Loom outline — under 5 minutes

- 0:00–0:30: State snapshot prices, 50-gallon tank and 10 mpg. No live prices.
- 0:30–1:45: Send Postman "Dallas to Los Angeles": `"Dallas, TX"` to `"Los Angeles, CA"`, `start_fuel_gallons` 20. Show purchase-only cost; starting fuel valued at $0. Reference check 2026-11-01: baseline verified 1,453.6 miles, $368.39. Recommended second proposal: same four purchases (QuikTrip Abilene TX, Circle K El Paso TX, QuikTrip Tucson AZ, Flyers Phoenix AZ), one fewer pass-through, 1,453.4 miles, 125.34 gallons, $368.34; comparison `compared`, savings $0.05. Send again for cached response. Re-run before recording; road and station data change.
- 1:45–2:30: Open map. Show numbered driven waypoints, purchases and pass-throughs. Show fuel balances and lowest-fuel points.
- 2:30–3:30: Show `optimize()` (fixed-sequence optimizer), `cost_proposal` / `progress_proposal`, and routed-leg verification. Explain bounded search and shared three-routing-call budget. Optional Jackson–Dickson comparison (`63724` to `67420`, starting fuel `0`): rerun first; show savings only when both candidates verified.
- 3:30–4:30: Explain plan cache and invalidation. State latest completed full-suite result and remaining verification gates; rerun after relevant changes.
- 4:30–5:00: State 1,214 eligible groups across 43 states; 5,412 remain unlocated. Existing 356 operator locations preserved; 858 OSM matches added. Explain source-backed coordinates and unresolved address/identity cases. Operator-data redistribution terms remain unresolved. Regional local graphs only; public routing default. Unit boundary tests use mocked data.

Publishing and recording deferred. If a route cannot be verified, show its unavailable status and null cost; do not invent a plan.

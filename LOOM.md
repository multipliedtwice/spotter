# Loom outline — under 5 minutes

- 0:00–0:30: State snapshot prices, 50-gallon tank and 10 mpg. No live prices.
- 0:30–1:45: Send Postman "Dallas to Los Angeles": `"Dallas, TX"` to `"Los Angeles, CA"`, `start_fuel_gallons` 20. Show `start_fuel_gallons` and `cost_basis` in the response: cost is fuel purchased during the journey, starting fuel valued at $0. Show 1,453.9 miles, five purchase stops (Baird TX, El Paso TX, Las Cruces NM, Benson AZ, Eloy AZ), 125.39 gallons, $393.99. Show baseline $419.61 and savings $25.62 for 1.71 extra miles and about 10 minutes. Send again to show the cached response. Live result 2026-10-31; re-run before recording, numbers change with OSRM and station data.
- 1:45–2:30: Open map. Show numbered driven waypoints, purchases and pass-throughs. Show fuel balances and lowest-fuel points.
- 2:30–3:30: Show `optimize()` (fixed-sequence optimizer), `cost_proposal` / `progress_proposal`, and routed-leg verification. Explain bounded search and shared three-routing-call budget. Secondary: Jackson–Dickson comparison (`63724` to `67420`, starting fuel `0`): baseline $27.03, recommended $25.88, save $1.15 for 0.82 extra miles.
- 3:30–4:30: Explain plan cache and invalidation. State latest completed full-suite result and remaining verification gates; rerun after relevant changes.
- 4:30–5:00: State 356 eligible Love's groups across 41 states, partial coverage and unknown operator-data license. DC and Jackson–Dickson graphs are regional. National graph out of scope; public routing default. Trips over 500 miles, such as Dallas to Los Angeles, use public routing. Unit boundary tests use mocked data; never label public routing as native USA.

Publishing and recording deferred. If a route cannot be verified, show its unavailable status and null cost; do not invent a plan.

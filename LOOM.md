# Loom outline — under 5 minutes

- 0:00–0:30: State snapshot prices, 50-gallon tank and 10 mpg. No live prices.
- 0:30–1:45: Send Postman "Dallas to Los Angeles": `"Dallas, TX"` to `"Los Angeles, CA"`, `start_fuel_gallons` 20. Show purchase-only cost; starting fuel valued at $0. Send again for cached response. Rerun before recording; road and station data change.
- 1:45–2:30: Open map. Show numbered driven waypoints, purchases and pass-throughs. Show fuel balances and lowest-fuel points.
- 2:30–3:30: Show `optimize()` (fixed-sequence optimizer), `cost_proposal` / `progress_proposal`, and routed-leg verification. Explain bounded search and shared three-routing-call budget. Optional Jackson–Dickson comparison (`63724` to `67420`, starting fuel `0`): rerun first; show savings only when both candidates verified.
- 3:30–4:30: Explain plan cache and invalidation. State latest completed full-suite result and remaining verification gates; rerun after relevant changes.
- 4:30–5:00: State 3,392 eligible groups across 48 states; 3,234 remain unlocated. Explain source-backed coordinates and identity-only matches whose CSV road details remain unverified. Operator-data redistribution terms remain unresolved. Regional local graphs only; public routing default. Unit boundary tests use mocked data.

Publishing and recording deferred. If a route cannot be verified, show its unavailable status and null cost; do not invent a plan.

# Loom outline — under 5 minutes

- 0:00–0:30: State snapshot prices, 50-gallon tank and 10 mpg. No live prices.
- 0:30–1:45: Send Postman Jackson–Dickson comparison: station `63724` Jackson to `67420` Dickson, starting fuel `0`. Use the Jackson–Dickson corridor graph or explicit public validation on port `8001`. Show snapshot baseline $27.03 and recommendation $25.88: save $1.15 for 0.82 extra miles and 298.6 seconds (about 5 minutes). Recommendation minimizes fuel purchase cost; time has no assigned value.
- 1:45–2:30: Open map. Show numbered driven waypoints, purchases and pass-throughs. Show fuel balances and lowest-fuel points.
- 2:30–3:30: Show fixed-sequence optimizer and routed-leg verification. The 78.1-mile trip starts empty and demonstrates cheaper refills, not the 500-mile tank boundary. Explain bounded search and shared three-routing-call budget.
- 3:30–4:30: Explain plan cache and invalidation. State latest completed full-suite result and remaining verification gates; rerun after relevant changes.
- 4:30–5:00: State 356 eligible Love's groups across 41 states, partial coverage and unknown operator-data license. DC and Jackson–Dickson graphs are regional. National graph out of scope; public routing default. A trip over 500 miles, such as `63724` to `1516` Amarillo, uses public routing. Unit boundary tests use mocked data; never label public routing as native USA.

Publishing and recording deferred. If a route cannot be verified, show its unavailable status and null cost; do not invent a plan.

# v2.4 validation

Source baseline: `75da4825abe7740eee5491b2bb2f1fe40c7f7d43` (v2.3).

The original suite passed 943 tests and 13 subtests before changes.

The final v2.4 suite passed 1,021 tests and 13 subtests. The source launcher self-test passed, including its spawned worker and persistent connection fixture.

The added checks cover mining recovery, ore defense, production budgets, reachable flank routes, assault continuation, emergency withdrawal, stale visibility and cooperation between defenders and attackers.

Geometric multi-step scenarios apply movement commands to subsequent observations. They do not simulate engine damage, harvesting yield or full production. They are behavior checks, not match results.

No new full-engine matches were run for v2.4 in this environment: the earlier OpenRA runtime and benchmark adapter were unavailable. `BENCHMARK.md` and `BENCHMARK_RESULTS.json` describe historical versions and must not be used as v2.4 win-rate evidence.

The Windows release workflow runs the full test suite, builds a native x64 EXE and tests the actual executable, spawned worker and persistent connection using offline fixtures. Build identity and checks are included in `build-info.json`, `self-test.json` and `SHA256SUMS.txt`.

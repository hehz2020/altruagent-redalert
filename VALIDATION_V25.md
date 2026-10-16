# v2.5 validation

Source baseline: `e264fce0d48da86110c896cf39a720fdc52b02ba` (v2.4).

## Implemented behavior

- Separate incidents receive bounded local defenders; a small escort remains on the mine road for at most 18 seconds after contact disappears. A large base attack can use more defenders.
- Harvester protection accumulates sustained damage across observations, including 5 Hz small hits, while allowing nearby mining to resume after danger passes.
- Limited raids consider visible economic targets, reachable firing positions, recent observed guards, tower exposure, kill time and remaining time. They preserve the main army's needed strength and recall when an opportunity becomes unsafe.
- Main objectives account for resistance, and brief mobile/static threat memory prevents treating fog as proof of destruction. Invisible actors are never targeted by ID.
- A clear kill-cost lead of at least 1,500 in the final 90 seconds consolidates the army and replaces existing outward orders. Losing the lead resumes normal pressure; immediate defense still takes priority.

## Checks

Local command: `python -m pytest tests redalert_bot_tests windows/tests -q`.

Final local result: **1,075 tests and 15 subtests passed**. The 41 warnings concern the existing MCP library's deprecated transport interface.

New scenario suites cover multi-mine defense, sustained damage, safe economic opportunities, role allocation, recent fog contacts, late-game order replacement and independent adversarial review cases. The three independent review cases verify remembered tower withdrawal, memory expiry and preservation of tanks needed for the main fight.

`python -m windows.entry --self-test --no-pause` passed on Linux, including controller loading, a spawned worker and an offline persistent MCP fixture. This source check is distinct from testing the Windows executable. The Windows build workflow independently repeats the full suite, builds a native x64 executable, then tests that actual executable and its spawned worker; inspect its `self-test.json` and `build-info.json` for the completed build's evidence.

Decision cost was measured with synthetic 96×96 terrain, 24/80 friendly units, 15 enemies and eight candidate structures. With objective/raid caching, warmed medians were approximately 11/50 ms and warmed maxima 96/191 ms in this environment; first observations took approximately 345/440 ms while constructing navigation. These are representative measurements, not a hard latency guarantee. A separate difficult raid-routing case fell from approximately 241–302 ms to 126–131 ms after sharing a 7,000-node search budget across targets. Cached unchanged raid observations took below 1 ms. Geometry, damage, visibility and threat changes invalidate raid reuse.

## Limits and next evidence

No full OpenRA engine matches were run for this version. The available engine needs an independently implemented platform/seat adapter before this bot can be tested fairly against complete opponent programs. The seven public repositories were read and analyzed, not executed or contacted.

The tests use explicit observations and, in existing integration fixtures, geometric movement. They do not reproduce engine damage, production income, fog, collision or a complete opponent. **No win rate against these seven bots has been established.** Historical `BENCHMARK.md` results are for older versions and are not v2.5 match evidence.

The private research record `docs/TACTICAL_RESEARCH_V25.md` pins opponent commits, separates code facts from hypotheses, and lists the paired full-engine matches still needed. Opponent identities are not used as gameplay branches; the controller responds to observed behavior and legal game state.

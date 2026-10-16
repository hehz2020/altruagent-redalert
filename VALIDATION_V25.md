# v2.5 validation

Source baseline: `e264fce0d48da86110c896cf39a720fdc52b02ba` (v2.4).

The release improves threat-responsive production, mining recovery, simultaneous defense, capture interception, attack target selection and sustained map searches. Existing flank routing and commitment to a favorable assault remain in place.

## Scenario and execution checks

The final Python suite passed 1,098 tests and 13 subtests. It covers concurrent mining raids, capture threats, local air defense, siege production, reachable ore, failed orders and command limits. Independently written integration scenarios distinguish the new behavior from the v2.4 baseline. Multi-frame regressions also check that fighting or withdrawing an entire squad pauses search timers, while a genuinely blocked advance can still switch search areas. These checks are not full matches or win-rate estimates.

The source launcher also passed its offline worker and persistent MCP connection self-test. No live platform credentials or competing agent connection were used.

## Decision cost

A local benchmark used 64 friendly tanks against 40 enemy tanks, two defenses and one factory, with three cold and thirty warm observations per map size. Approximate medians in milliseconds:

| Map size | v2.4 cold | Earlier v2.5 candidate cold | v2.4 warm | Earlier v2.5 candidate warm |
| --- | ---: | ---: | ---: | ---: |
| 96 × 96 | 473 | 231 | 326 | 206 |
| 256 × 256 | 2,139 | 627 | 335 | 211 |

This isolates local decision work; it excludes platform and network latency. These are earlier development measurements after the cache and integer-coordinate changes, before the search repairs; they are not a fresh measurement of frozen F. They do not measure playing strength.

## Full-match comparison

Three first-stage candidates were compared on four development conditions, together with module ablations. Candidate A was rejected after three losses; candidate C was rejected after lower completion performance and a reproducible lone-guard role-allocation defect. Candidate B was selected before an independent twelve-condition comparison.

In that independent first stage, v2.4 finished with 4 wins, 5 losses and 3 censored games; B had 1 win, 4 losses and 7 censored games. B was not released. Trace inspection then identified a general cleanup defect: timed revisits to the enemy starting location interrupted unfinished map searches. The subsequent development stage treats all previously inspected cases as development evidence and uses newly declared conditions for independent validation.

The first search repair, candidate D, won the inspected cleanup case in 560.56 seconds but changed two previous development wins into censored games. It was also rejected. Comparing the earliest action differences found that its search timeout ran while the army was still regrouping and had not started moving toward the target. The narrower repair preserves the first main-force visit to the enemy start and pauses search timeouts during other army modes.

Candidate E restored B's results on all four original development cases and completed the inspected cleanup case in 1,041.04 seconds. Candidate F additionally paused search timers when every available unit was firing or withdrawing. Four multi-frame regression scenarios failed against frozen E and passed against F; all five full-match development results remained identical between E and F. This last fix is supported by the regressions, not a claimed additional match win.

F was selected and frozen before running eight newly reserved paired conditions. No strategy changes were made during those sixteen matches:

| Policy | Wins | Losses | Censored at 1,200 seconds |
| --- | ---: | ---: | ---: |
| Released v2.4 | 3 | 2 | 3 |
| Final v2.5 / F | 4 | 0 | 4 |

One v2.4 loss became an F win and another became censored. Two v2.4 censored games became F wins, while two v2.4 wins became censored. The remaining two outcomes were unchanged. This small sample supports releasing F as a measured iteration, not a universal improvement: finishing speed remains a weakness, and the original development_4 regression remains unresolved. Zero losses in eight local conditions does not establish a zero-loss rate on the platform.

The full record contains 80 local matches across development, ablations and two separate independent evaluation stages. These matches are not pooled into a single win-rate figure.

Frozen policies, all development failures and ablations, evaluation conditions, engine instrumentation and reproduction instructions are retained in [benchmarks/v25_engine](https://github.com/hehz2020/altruagent-redalert/tree/main/benchmarks/v25_engine). The local engine exposes only the controlled seat's visible observations plus public static map/rules to the policy. Stock opponents may use privileged engine information.

Terminal engine results determine wins and losses. A match still running at 1,200 simulated seconds is censored, not a draw or a score-based win. Development matches and independent validation are reported separately. This is a local engine comparison, not an official platform win-rate measurement; adapter and runtime limitations are documented in the benchmark folder.

## Windows artifact

The release workflow runs the full test suite and tests the actual native Windows executable, spawned worker and persistent connection using offline fixtures. Build identity is recorded in `build-info.json`, `self-test.json` and `SHA256SUMS.txt`.

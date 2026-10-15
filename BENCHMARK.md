# Red Alert v2.3 evaluation

Date: 2026-10-15 UTC. Machine-readable aggregates: `BENCHMARK_RESULTS.json`. Earlier testing remains in the [v2.2 benchmark archive](https://github.com/hehz2020/altruagent-redalert/blob/main/benchmarks/v2_2.md). These are local instrumented-engine matches, not official platform results.

Frozen v2.3 won **11/16 fresh conditions**, versus **9/16 for v2.2**. Across the paired conditions, 5 improved, 3 regressed and 8 had the same outcome. v2.3's wins comprise 8 engine wins and 3 local time-limit score wins; v2.2's comprise 7 and 2, respectively. These small, fixed local tests do not establish a universally stronger bot, SOTA status or guaranteed wins. Development results used for selection are kept separate below.

## Design and result sources

All twelve previously observed conditions are now **development** data, including the eight conditions formerly used as v2.2 holdout. Candidates were compared on the same set. Selection prioritizes wins plus half draws across twelve conditions. The initial plan named matched outcomes and cost exchange as generic tie-breaks. After F completed and before G results were inspected for selection, the tie-break order was recorded at 04:28:28 UTC on October 15: fewer v2.2 win-to-loss regressions, then higher summed own net destroyed cost over all twelve conditions, then lower median win time. This detailed order was not specified from the start. Longer survival alone is not a win.

Fresh validation was declared before the final candidate was selected: sixteen new conditions, seeds 401–416, crossing two own factions, two seats, two opposing factions and two stock AI types, with three maps rotated. The frozen final policy and v2.2 reference each run all sixteen. These results must not be pooled with development. Rotating maps and fixed seeds still limit causal or general-performance claims.

Engine outcomes come from the own player's terminal `WinState`. At the 1200-second cap, a separate local referee applies the [public scoring rule](https://platform.altruagent-game.com/skill/redalert): compare net destroyed cost, then remaining assets if tied; complete equality is a draw. Referee telemetry is read only after the policy loop and never supplied to the policy. Its same-tick statistics can differ from the platform's latest-observation sampling, so a local score result is not an official platform-returned result. K/D below are the own seat's destroyed/lost cost, not unit counts or the opponent's score.

Every condition uses 5000 cash, MCV only, initially unexplored terrain, fog and crates enabled, kill bounties disabled and short game enabled. Both RNGs use the condition seed. The calibrated adapter uses nearest integer-percent HP and observations every five ticks (0.2 simulated seconds). Exact platform HP rounding is unavailable. Direct gRPC omits real network latency, MCP grants/leases, observation truncation and faithful delayed per-command acknowledgements.

**Known calibration difference:** after the construction yard is gone, the public guide describes a center-of-buildings, then center-of-units fallback for `base_center`; this adapter instead uses the first remaining building or unit. The `base_center` coordinates matched in all 164 captured platform observations that had a yard; this is not a claim that every observation field was calibrated. The exposure audit covers development candidates A–E, not F, G or fresh validation. Its distances use the arithmetic mean as the audit reference; the guide's exact fallback formula has not been verified. The audit recorded no difference over one cell in A's seven development wins. Four A losses were exposed for their last roughly 9–24 seconds; one had 142.6 seconds of exposure with at most 1.8 cells of drift. This does not establish that outcomes are unaffected. The calibration remains unchanged for this comparison, and future corrected-adapter results must be distinguished. Per-run audited exposures are retained in the JSON.

Only own-seat fog-filtered observations and public static rules enter policy decisions. Stock Normal/Rush AI can have privileged engine information. Results do not establish performance against strong community or platform entrants.

## Development results

| Policy | Completed / planned | Engine W–L | Local-score W–L | Draws | Total W–L |
|---|---:|---:|---:|---:|---:|
| final_v22 | 12 / 12 | 5–7 | 0–0 | 0 | 5–7 |
| attack_move_v3 | 12 / 12 | 0–12 | 0–0 | 0 | 0–12 |
| cohesive_combat_v3 | 12 / 12 | 5–5 | 1–1 | 0 | 6–6 |
| crush_micro_v3 | 12 / 12 | 6–6 | 0–0 | 0 | 6–6 |
| pressure_rush_v3 | 12 / 12 | 3–9 | 0–0 | 0 | 3–9 |
| tank_cohesive_screen_v3 | 12 / 12 | 7–2 | 3–0 | 0 | 10–2 |
| tank_cohesive_v3 | 12 / 12 | 5–2 | 4–1 | 0 | 9–3 |
| tank_timing_v3 | 12 / 12 | 5–5 | 2–0 | 0 | 7–5 |

Candidate definitions (combinations are evaluated as whole policies, not proof of a single causal change):

| Label | Policy | Change from v2.2 |
|---|---|---|
| A | tank_timing_v3 | Two-refinery economic opening, earlier sustained tank production and a three-tank opening attack requirement. |
| B | pressure_rush_v3 | First-wave light vehicles and infantry before expansion; combat controller unchanged. |
| C | cohesive_combat_v3 | Six-cell group advances, recovery of exposed vehicles and limited range-based vehicle kiting; economy unchanged. |
| D | attack_move_v3 | Engine attack-move redesign, removing explicit local targeting/retreat/split roles and changing readiness thresholds. |
| E | crush_micro_v3 | Conditional short movement through visible clustered infantry by healthy tracked vehicles; economy unchanged. |
| F | tank_cohesive_v3 | A's economy and opening requirement plus C's cohesion, with fixes for an observed unreachable waypoint and conflicting standoff movement/fire. |
| G | tank_cohesive_screen_v3 | F with an economic priority change: after three observed main tanks, keep the fourth harvester priority, then replenish three rifles and one suitable screening vehicle before pursuing six tanks. |

F is a new combined candidate, not a replacement of C's recorded results. Its comparison cannot isolate the effect of any one combined change. G changes only F's economy file; queued tanks do not satisfy its initial three-tank milestone. Neither includes E's crush change.

The four Sidestep reference rows reuse `recovery_v26` with their actual original hashes; it differs from released `final_v22` only in the package version string. The other eight reference rows use the release hash. The planned exact-hash refill was cancelled without running; it adds no samples.

The final v2.3 policy was frozen on October 15 at 04:31:40 UTC as `final_v23`, identical to G (`tank_cohesive_screen_v3`). G scored 10/12 development points, versus F's 9/12 and v2.2's 5/12, so no tie-break was needed for first place. Its ten wins comprised seven engine wins and three local score wins. Selection occurred before fresh results were seen; the policy was then held fixed. Full policy SHA-256: `a7934b626ad3aaa93277f789404883afb57df04e8831960806806a07d482033a`.

| Policy | Condition | Map | Side | Own / enemy faction | AI | Seed | Outcome / source | Seconds | K | D | Actual policy hash |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---|
| final_v22 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | loss / engine | 1039.48 | 40000 | 50300 | `a5d698ad7662` |
| final_v22 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | loss / engine | 1137.08 | 42450 | 52750 | `a5d698ad7662` |
| final_v22 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | win / engine | 836.48 | 61200 | 12900 | `a5d698ad7662` |
| final_v22 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | win / engine | 576.28 | 30500 | 9650 | `a5d698ad7662` |
| final_v22 | development_05 | trapped | Multi0 | russia / england | normal | 101 | win / engine | 783.48 | 34250 | 11700 | `dabc39191f01` |
| final_v22 | development_06 | trapped | Multi1 | england / russia | normal | 102 | loss / engine | 660.08 | 7400 | 26650 | `dabc39191f01` |
| final_v22 | development_07 | trapped | Multi0 | russia / england | rush | 103 | win / engine | 633.08 | 37350 | 3200 | `dabc39191f01` |
| final_v22 | development_08 | trapped | Multi1 | england / russia | rush | 104 | loss / engine | 433.28 | 2750 | 19150 | `dabc39191f01` |
| final_v22 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | loss / engine | 886.08 | 19450 | 37400 | `dabc39191f01` |
| final_v22 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | loss / engine | 730.88 | 16950 | 35450 | `dabc39191f01` |
| final_v22 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | win / engine | 836.28 | 58950 | 10100 | `dabc39191f01` |
| final_v22 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | loss / engine | 705.08 | 14100 | 34300 | `dabc39191f01` |
| attack_move_v3 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | loss / engine | 763.28 | 12450 | 43250 | `d06d04445827` |
| attack_move_v3 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | loss / engine | 719.48 | 11350 | 42100 | `d06d04445827` |
| attack_move_v3 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | loss / engine | 718.28 | 18000 | 32750 | `d06d04445827` |
| attack_move_v3 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | loss / engine | 644.68 | 15450 | 36350 | `d06d04445827` |
| attack_move_v3 | development_05 | trapped | Multi0 | russia / england | normal | 101 | loss / engine | 710.28 | 8650 | 31350 | `d06d04445827` |
| attack_move_v3 | development_06 | trapped | Multi1 | england / russia | normal | 102 | loss / engine | 680.88 | 3800 | 32500 | `d06d04445827` |
| attack_move_v3 | development_07 | trapped | Multi0 | russia / england | rush | 103 | loss / engine | 470.68 | 3800 | 21550 | `d06d04445827` |
| attack_move_v3 | development_08 | trapped | Multi1 | england / russia | rush | 104 | loss / engine | 407.28 | 1500 | 13700 | `d06d04445827` |
| attack_move_v3 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | loss / engine | 600.48 | 2450 | 31900 | `d06d04445827` |
| attack_move_v3 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | loss / engine | 654.28 | 3800 | 32700 | `d06d04445827` |
| attack_move_v3 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | loss / engine | 626.08 | 7700 | 34450 | `d06d04445827` |
| attack_move_v3 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | loss / engine | 781.68 | 18200 | 34200 | `d06d04445827` |
| cohesive_combat_v3 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | win / local score | 1200.00 | 53250 | 45350 | `e47625af5518` |
| cohesive_combat_v3 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | win / engine | 1168.88 | 55400 | 9300 | `e47625af5518` |
| cohesive_combat_v3 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | loss / engine | 923.28 | 32650 | 46100 | `e47625af5518` |
| cohesive_combat_v3 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | win / engine | 1018.08 | 25600 | 9500 | `e47625af5518` |
| cohesive_combat_v3 | development_05 | trapped | Multi0 | russia / england | normal | 101 | loss / local score | 1200.00 | 33850 | 48450 | `e47625af5518` |
| cohesive_combat_v3 | development_06 | trapped | Multi1 | england / russia | normal | 102 | loss / engine | 1150.68 | 38250 | 46050 | `e47625af5518` |
| cohesive_combat_v3 | development_07 | trapped | Multi0 | russia / england | rush | 103 | loss / engine | 587.88 | 7350 | 26000 | `e47625af5518` |
| cohesive_combat_v3 | development_08 | trapped | Multi1 | england / russia | rush | 104 | loss / engine | 587.48 | 9550 | 19550 | `e47625af5518` |
| cohesive_combat_v3 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | win / engine | 1013.88 | 67250 | 13400 | `e47625af5518` |
| cohesive_combat_v3 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | loss / engine | 1188.08 | 43950 | 53250 | `e47625af5518` |
| cohesive_combat_v3 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | win / engine | 802.08 | 52650 | 6750 | `e47625af5518` |
| cohesive_combat_v3 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | win / engine | 642.48 | 30200 | 8000 | `e47625af5518` |
| crush_micro_v3 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | loss / engine | 1039.48 | 40000 | 50300 | `1d4e0152d9de` |
| crush_micro_v3 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | win / engine | 1187.48 | 85600 | 33300 | `1d4e0152d9de` |
| crush_micro_v3 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | win / engine | 836.48 | 61200 | 12900 | `1d4e0152d9de` |
| crush_micro_v3 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | win / engine | 576.28 | 30500 | 9650 | `1d4e0152d9de` |
| crush_micro_v3 | development_05 | trapped | Multi0 | russia / england | normal | 101 | win / engine | 783.48 | 34250 | 11700 | `1d4e0152d9de` |
| crush_micro_v3 | development_06 | trapped | Multi1 | england / russia | normal | 102 | loss / engine | 660.08 | 7400 | 26650 | `1d4e0152d9de` |
| crush_micro_v3 | development_07 | trapped | Multi0 | russia / england | rush | 103 | win / engine | 633.08 | 37350 | 3200 | `1d4e0152d9de` |
| crush_micro_v3 | development_08 | trapped | Multi1 | england / russia | rush | 104 | loss / engine | 433.28 | 2750 | 19150 | `1d4e0152d9de` |
| crush_micro_v3 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | loss / engine | 886.08 | 19450 | 37400 | `1d4e0152d9de` |
| crush_micro_v3 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | loss / engine | 730.88 | 16950 | 35450 | `1d4e0152d9de` |
| crush_micro_v3 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | win / engine | 836.28 | 58950 | 10100 | `1d4e0152d9de` |
| crush_micro_v3 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | loss / engine | 705.08 | 14100 | 34300 | `1d4e0152d9de` |
| pressure_rush_v3 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | loss / engine | 839.08 | 19350 | 40050 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | win / engine | 257.28 | 10250 | 700 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | loss / engine | 802.68 | 10600 | 37250 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | loss / engine | 915.28 | 23600 | 44800 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_05 | trapped | Multi0 | russia / england | normal | 101 | loss / engine | 1135.08 | 18750 | 37900 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_06 | trapped | Multi1 | england / russia | normal | 102 | loss / engine | 794.88 | 7450 | 28950 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_07 | trapped | Multi0 | russia / england | rush | 103 | win / engine | 381.08 | 22000 | 1100 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_08 | trapped | Multi1 | england / russia | rush | 104 | loss / engine | 434.48 | 3800 | 12700 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | loss / engine | 584.48 | 2900 | 21900 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | loss / engine | 647.48 | 8950 | 28350 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | win / engine | 386.48 | 18150 | 1200 | `67fe2ee90a5f` |
| pressure_rush_v3 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | loss / engine | 357.88 | 3100 | 11400 | `67fe2ee90a5f` |
| tank_cohesive_screen_v3 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | win / engine | 1033.28 | 27050 | 3150 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | win / engine | 809.28 | 48850 | 15050 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | win / local score | 1200.00 | 100600 | 31400 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | win / engine | 836.08 | 49350 | 17300 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_05 | trapped | Multi0 | russia / england | normal | 101 | win / engine | 1138.28 | 36600 | 11450 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_06 | trapped | Multi1 | england / russia | normal | 102 | loss / engine | 1016.88 | 26750 | 45500 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_07 | trapped | Multi0 | russia / england | rush | 103 | loss / engine | 564.88 | 10800 | 24150 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_08 | trapped | Multi1 | england / russia | rush | 104 | win / engine | 963.28 | 69450 | 10550 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | win / engine | 1112.48 | 73200 | 12750 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | win / local score | 1200.00 | 73650 | 45400 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | win / engine | 1052.68 | 76800 | 12250 | `a7934b626ad3` |
| tank_cohesive_screen_v3 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | win / local score | 1200.00 | 85050 | 23950 | `a7934b626ad3` |
| tank_cohesive_v3 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | win / engine | 1043.88 | 59650 | 7650 | `66978fbc5514` |
| tank_cohesive_v3 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | win / engine | 880.48 | 45850 | 12250 | `66978fbc5514` |
| tank_cohesive_v3 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | win / local score | 1200.00 | 99850 | 17450 | `66978fbc5514` |
| tank_cohesive_v3 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | win / engine | 639.88 | 31950 | 9350 | `66978fbc5514` |
| tank_cohesive_v3 | development_05 | trapped | Multi0 | russia / england | normal | 101 | win / engine | 525.28 | 26150 | 4700 | `66978fbc5514` |
| tank_cohesive_v3 | development_06 | trapped | Multi1 | england / russia | normal | 102 | win / local score | 1200.00 | 69800 | 29550 | `66978fbc5514` |
| tank_cohesive_v3 | development_07 | trapped | Multi0 | russia / england | rush | 103 | loss / engine | 469.08 | 7000 | 20900 | `66978fbc5514` |
| tank_cohesive_v3 | development_08 | trapped | Multi1 | england / russia | rush | 104 | win / local score | 1200.00 | 53950 | 10100 | `66978fbc5514` |
| tank_cohesive_v3 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | loss / local score | 1200.00 | 58600 | 59100 | `66978fbc5514` |
| tank_cohesive_v3 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | loss / engine | 1097.28 | 39150 | 59300 | `66978fbc5514` |
| tank_cohesive_v3 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | win / local score | 1200.00 | 81700 | 24650 | `66978fbc5514` |
| tank_cohesive_v3 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | win / engine | 818.08 | 49800 | 6150 | `66978fbc5514` |
| tank_timing_v3 | development_01 | sidestep | Multi0 | russia / russia | normal | 2 | loss / engine | 986.68 | 26800 | 49450 | `f9ecd65db290` |
| tank_timing_v3 | development_02 | sidestep | Multi1 | russia / russia | normal | 3 | win / local score | 1200.00 | 64350 | 43650 | `f9ecd65db290` |
| tank_timing_v3 | development_03 | sidestep | Multi0 | russia / russia | rush | 2 | win / engine | 1043.08 | 84400 | 20750 | `f9ecd65db290` |
| tank_timing_v3 | development_04 | sidestep | Multi1 | russia / russia | rush | 3 | win / engine | 570.08 | 26250 | 7650 | `f9ecd65db290` |
| tank_timing_v3 | development_05 | trapped | Multi0 | russia / england | normal | 101 | loss / engine | 1170.28 | 40800 | 54950 | `f9ecd65db290` |
| tank_timing_v3 | development_06 | trapped | Multi1 | england / russia | normal | 102 | win / local score | 1200.00 | 68150 | 43700 | `f9ecd65db290` |
| tank_timing_v3 | development_07 | trapped | Multi0 | russia / england | rush | 103 | loss / engine | 792.28 | 19850 | 36350 | `f9ecd65db290` |
| tank_timing_v3 | development_08 | trapped | Multi1 | england / russia | rush | 104 | loss / engine | 905.88 | 30300 | 47500 | `f9ecd65db290` |
| tank_timing_v3 | development_09 | shadowfiend-ii | Multi0 | russia / england | normal | 111 | loss / engine | 990.08 | 29150 | 45400 | `f9ecd65db290` |
| tank_timing_v3 | development_10 | shadowfiend-ii | Multi1 | england / russia | normal | 112 | win / engine | 675.68 | 42350 | 13850 | `f9ecd65db290` |
| tank_timing_v3 | development_11 | shadowfiend-ii | Multi0 | russia / england | rush | 113 | win / engine | 899.68 | 60350 | 9600 | `f9ecd65db290` |
| tank_timing_v3 | development_12 | shadowfiend-ii | Multi1 | england / russia | rush | 114 | win / engine | 651.28 | 40400 | 9200 | `f9ecd65db290` |

## Infrastructure replay retained as one condition

Candidate A (`tank_timing_v3`), Trapped / Normal / seed 101 / Multi0, first hit a headless GPS screen-render null error. The original error record remains. A display-only guard skips screen-space effect indexing when no renderer exists; GPS timing, map reveal and combat logic are unchanged. The same frozen policy and condition were replayed after that fix. The first **5839 observations and decisions, through tick 29192**, matched after excluding session identity. The replay passed the old failure point and reached an engine loss at 1170.28 seconds.

The original error and resolved replay are one development condition, not two independent samples. Replay metadata initially listed the first three instrumentation patches because the display patch's provenance manifest was written just after launch; an explicitly dated supplement records the fourth patch without rewriting the original snapshot. This provides a matched pre-crash prefix, not proof of equivalence to every rendered-engine execution.

## Fresh validation

Status: 32/32 completed runs; sixteen conditions per policy.

| Policy | Completed / planned | Engine W–L | Local-score W–L | Draws | Total W–L |
|---|---:|---:|---:|---:|---:|
| final_v22 | 16 / 16 | 7–7 | 2–0 | 0 | 9–7 |
| final_v23 | 16 / 16 | 8–5 | 3–0 | 0 | 11–5 |

The overall gain is concentrated against the Rush opponent; it is not an improvement in every opponent category. These eight-condition subgroups are descriptive, not independent confirmatory tests.

| Stock opponent | v2.2 wins / conditions | v2.3 wins / conditions |
|---|---:|---:|
| Normal | 5 / 8 | 4 / 8 |
| Rush | 4 / 8 | 7 / 8 |

The v2.2 win → v2.3 loss regressions are `fresh3_01` (sidestep, normal, own russia, seed 401, Multi0); `fresh3_05` (trapped, normal, own russia, seed 405, Multi1); `fresh3_13` (sidestep, normal, own england, seed 413, Multi1). All five v2.3 losses remain in the table.

| Policy | Condition | Map | Side | Own / enemy faction | AI | Seed | Outcome / source | Seconds | K | D | Actual policy hash |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---|
| final_v22 | fresh3_01 | sidestep | Multi0 | russia / russia | normal | 401 | win / local score | 1200.00 | 54150 | 37800 | `dabc39191f01` |
| final_v23 | fresh3_01 | sidestep | Multi0 | russia / russia | normal | 401 | loss / engine | 839.28 | 25550 | 44650 | `a7934b626ad3` |
| final_v22 | fresh3_02 | trapped | Multi0 | russia / england | normal | 402 | loss / engine | 866.88 | 23100 | 36700 | `dabc39191f01` |
| final_v23 | fresh3_02 | trapped | Multi0 | russia / england | normal | 402 | win / engine | 809.68 | 32200 | 6550 | `a7934b626ad3` |
| final_v22 | fresh3_03 | shadowfiend-ii | Multi0 | russia / russia | rush | 403 | loss / engine | 1180.68 | 64750 | 53650 | `dabc39191f01` |
| final_v23 | fresh3_03 | shadowfiend-ii | Multi0 | russia / russia | rush | 403 | win / local score | 1200.00 | 61500 | 9700 | `a7934b626ad3` |
| final_v22 | fresh3_04 | sidestep | Multi0 | russia / england | rush | 404 | win / engine | 732.48 | 40700 | 10600 | `dabc39191f01` |
| final_v23 | fresh3_04 | sidestep | Multi0 | russia / england | rush | 404 | win / engine | 881.08 | 58550 | 12350 | `a7934b626ad3` |
| final_v22 | fresh3_05 | trapped | Multi1 | russia / russia | normal | 405 | win / engine | 764.08 | 33700 | 8250 | `dabc39191f01` |
| final_v23 | fresh3_05 | trapped | Multi1 | russia / russia | normal | 405 | loss / engine | 1026.08 | 27350 | 48750 | `a7934b626ad3` |
| final_v22 | fresh3_06 | shadowfiend-ii | Multi1 | russia / england | normal | 406 | win / local score | 1200.00 | 77100 | 44400 | `dabc39191f01` |
| final_v23 | fresh3_06 | shadowfiend-ii | Multi1 | russia / england | normal | 406 | win / local score | 1200.00 | 91750 | 29250 | `a7934b626ad3` |
| final_v22 | fresh3_07 | sidestep | Multi1 | russia / russia | rush | 407 | loss / engine | 963.68 | 29200 | 48950 | `dabc39191f01` |
| final_v23 | fresh3_07 | sidestep | Multi1 | russia / russia | rush | 407 | win / engine | 930.88 | 40600 | 6500 | `a7934b626ad3` |
| final_v22 | fresh3_08 | trapped | Multi1 | russia / england | rush | 408 | win / engine | 912.08 | 54500 | 16900 | `dabc39191f01` |
| final_v23 | fresh3_08 | trapped | Multi1 | russia / england | rush | 408 | win / engine | 531.48 | 22500 | 2400 | `a7934b626ad3` |
| final_v22 | fresh3_09 | shadowfiend-ii | Multi0 | england / russia | normal | 409 | win / engine | 743.88 | 46700 | 13800 | `dabc39191f01` |
| final_v23 | fresh3_09 | shadowfiend-ii | Multi0 | england / russia | normal | 409 | win / local score | 1200.00 | 99000 | 31450 | `a7934b626ad3` |
| final_v22 | fresh3_10 | sidestep | Multi0 | england / england | normal | 410 | loss / engine | 593.88 | 2100 | 12200 | `dabc39191f01` |
| final_v23 | fresh3_10 | sidestep | Multi0 | england / england | normal | 410 | loss / engine | 450.88 | 4400 | 22500 | `a7934b626ad3` |
| final_v22 | fresh3_11 | trapped | Multi0 | england / russia | rush | 411 | loss / engine | 547.48 | 6400 | 21050 | `dabc39191f01` |
| final_v23 | fresh3_11 | trapped | Multi0 | england / russia | rush | 411 | loss / engine | 942.28 | 26600 | 45850 | `a7934b626ad3` |
| final_v22 | fresh3_12 | shadowfiend-ii | Multi0 | england / england | rush | 412 | win / engine | 651.28 | 40000 | 8550 | `dabc39191f01` |
| final_v23 | fresh3_12 | shadowfiend-ii | Multi0 | england / england | rush | 412 | win / engine | 455.08 | 25600 | 2250 | `a7934b626ad3` |
| final_v22 | fresh3_13 | sidestep | Multi1 | england / russia | normal | 413 | win / engine | 609.08 | 29650 | 7450 | `dabc39191f01` |
| final_v23 | fresh3_13 | sidestep | Multi1 | england / russia | normal | 413 | loss / engine | 1117.08 | 50100 | 57150 | `a7934b626ad3` |
| final_v22 | fresh3_14 | trapped | Multi1 | england / england | normal | 414 | loss / engine | 1198.88 | 24050 | 56600 | `dabc39191f01` |
| final_v23 | fresh3_14 | trapped | Multi1 | england / england | normal | 414 | win / engine | 532.68 | 24900 | 4450 | `a7934b626ad3` |
| final_v22 | fresh3_15 | shadowfiend-ii | Multi1 | england / russia | rush | 415 | loss / engine | 291.08 | 1250 | 10400 | `dabc39191f01` |
| final_v23 | fresh3_15 | shadowfiend-ii | Multi1 | england / russia | rush | 415 | win / engine | 1034.28 | 75900 | 21700 | `a7934b626ad3` |
| final_v22 | fresh3_16 | sidestep | Multi1 | england / england | rush | 416 | win / engine | 434.28 | 20700 | 500 | `dabc39191f01` |
| final_v23 | fresh3_16 | sidestep | Multi1 | england / england | rush | 416 | win / engine | 480.48 | 31500 | 1900 | `a7934b626ad3` |


## Local referee scores

| Policy / condition | Phase | Own (net cost, assets) | Opponent (net cost, assets) | Tick | Local outcome |
|---|---|---|---|---:|---|
| cohesive_combat_v3 / development_01 | development | (7900, 9800) | (-7900, 64050) | 30000 | win |
| cohesive_combat_v3 / development_05 | development | (-14600, 4700) | (14600, 74850) | 30000 | loss |
| tank_cohesive_screen_v3 / development_03 | development | (69200, 37200) | (-69200, 28650) | 30000 | win |
| tank_cohesive_screen_v3 / development_10 | development | (28250, 18750) | (-28350, 40350) | 30000 | win |
| tank_cohesive_screen_v3 / development_12 | development | (61100, 38650) | (-61100, 6500) | 30000 | win |
| tank_cohesive_v3 / development_03 | development | (82400, 43600) | (-82400, 2450) | 30000 | win |
| tank_cohesive_v3 / development_06 | development | (40250, 32250) | (-40750, 39400) | 30000 | win |
| tank_cohesive_v3 / development_08 | development | (43850, 52550) | (-43850, 3500) | 30000 | win |
| tank_cohesive_v3 / development_09 | development | (-500, 8900) | (400, 73550) | 30000 | loss |
| tank_cohesive_v3 / development_11 | development | (57050, 40250) | (-57050, 7800) | 30000 | win |
| tank_timing_v3 / development_02 | development | (20700, 16700) | (-20800, 42400) | 30000 | win |
| tank_timing_v3 / development_06 | development | (24450, 19050) | (-24450, 50600) | 30000 | win |
| final_v22 / fresh3_01 | fresh_validation | (16350, 19150) | (-16350, 19050) | 30000 | win |
| final_v23 / fresh3_03 | fresh_validation | (51800, 63000) | (-51800, 2000) | 30000 | win |
| final_v22 / fresh3_06 | fresh_validation | (32700, 16800) | (-32700, 32750) | 30000 | win |
| final_v23 / fresh3_06 | fresh_validation | (62500, 36600) | (-62500, 17900) | 30000 | win |
| final_v23 / fresh3_09 | fresh_validation | (67550, 38550) | (-67550, 12300) | 30000 | win |

## Engine and policy provenance

Base engine: [`9b271c1a5562a07deeb1c3f81d9a556cd563a676`](https://github.com/yxc20089/OpenRA/tree/9b271c1a5562a07deeb1c3f81d9a556cd563a676). Instrumentation reports the own player's already-determined terminal result, seeds local RNG, emits referee-only post-cutoff statistics, and guards display indexing in headless GPS effects. No patch changes unit statistics, combat rules, physics or visibility. Per-run initial patch lists and any explicit supplement are retained in the aggregate JSON.

| Patch | SHA-256 |
|---|---|
| own-seat terminal reporting | `56dc0653b1768ce11f63688b33adb0d7d33faa623432e3922f92eb74701d94ee` |
| optional local RNG seed for repeatable evaluation | `70a369a10e8fbfb92ed4dade638b387958db7144672ab9e6c1beeec9b81bb60d` |
| post-cutoff referee-only stderr telemetry | `ff798bc53171679977a3f55ffd25500fd2a19099b4cec6827bee9352b5fa7c20` |
| headless rendering null guard | `ccf6d6e65d17c44dbc33940c62ea7d8b829461c0267834fa417302b2010a4c47` |

The public v2.2 source baseline is [`85c6c9493aa1a5abb61e8b5a737a62ba7a411a6d`](https://github.com/hehz2020/altruagent-redalert/tree/85c6c9493aa1a5abb61e8b5a737a62ba7a411a6d). Policy fingerprints concatenate each sorted `altru_redalert/*.py` filename and file bytes into SHA-256. These are policy-file hashes, not executable or whole-repository hashes; release build metadata identifies the packaged source commit.

| Policy | Full SHA-256 |
|---|---|
| final_v22 | `dabc39191f013d31b6b09ca0e816ec98f80aa34f1035c07e79d4bcfeb9bb81ba` |
| attack_move_v3 | `d06d044458274e7d9ff6f51b48b7d4cfc1493efeac5f2adad7f74a8d0279f6f3` |
| cohesive_combat_v3 | `e47625af5518d55bc910d30f17240418e9d36795552d28e626444eff360e22af` |
| crush_micro_v3 | `1d4e0152d9de989a6d9dff98ed1d875ec53fcdc0d6e100299846cbb72fc69a9d` |
| pressure_rush_v3 | `67fe2ee90a5fb030062e77ee1de8a7d83ad789804f8751c125e0837ec651e69a` |
| tank_cohesive_screen_v3 | `a7934b626ad3aaa93277f789404883afb57df04e8831960806806a07d482033a` |
| tank_cohesive_v3 | `66978fbc5514ab6850cefbd677434f51674e554c4a1bc39b9866eedc93e9f231` |
| tank_timing_v3 | `f9ecd65db2900413b7ca57afe2913262333375cd41be7332d374d4e41330fd43` |
| recovery_v26 | `a5d698ad7662e87b3380034483e9c938082a0a456d260468f9bc2906761ba35a` |
| final_v23 | `a7934b626ad3aaa93277f789404883afb57df04e8831960806806a07d482033a` |

Every completed row is cross-checked against per-match metadata and summary, frozen policy files, its condition and the development aggregate; available execution-suite result records are checked too. The public JSON exports only whitelisted aggregate and provenance fields. Full traces, local paths, session identities and credentials are excluded. All completed wins and losses remain visible. Earlier floating-point-HP explorations are not pooled with this calibrated dataset.

Initial-observation metadata exception: tank_cohesive_v3 / development_11 omitted its initial-observation metadata fields. An explicit supplement reconstructs the faction from the first authorized observation at tick 2, whose session identity matches the original metadata; the faction also matches the frozen map. The cause of the missing fields is unknown. The original metadata remains unchanged, with its SHA-256 and supplement provenance retained in the public JSON.

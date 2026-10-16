# v2.5 engine evaluation results

W/L/C means terminal wins, terminal losses, and censored runs still undecided at the 1,200-second limit. C is not a draw. Every result comes from the controlled seat in a locally instrumented OpenRA engine; none is an official platform result.

The final candidate is candidate_b. It was selected from development results before any held-out result existed; selection-freeze.json records the decision and known development regression. No policy was adjusted using the held-out results. Development and ablation outcomes must not be pooled with the held-out outcomes.

## Held-out paired results

| Policy | Completed / planned | W/L/C |
|---|---:|---:|
| released_v24 | 12 / 12 | 4/5/3 |
| candidate_b | 12 / 12 | 1/4/7 |

| Condition | Map | Own / enemy faction | Seat | AI / seed | v2.4 | Final B |
|---|---|---|---|---|---|---|
| 1 | sidestep | russia / england | Multi0 | normal / 3501 | L 1016.80s | L 1060.24s |
| 2 | trapped | england / russia | Multi1 | rush / 3502 | L 581.92s | L 802.48s |
| 3 | sidestep | england / russia | Multi1 | normal / 3503 | C 1200.04s | C 1200.04s |
| 4 | trapped | russia / england | Multi0 | rush / 3504 | L 850.00s | L 747.52s |
| 5 | shadowfiend-ii | russia / russia | Multi0 | normal / 4501 | C 1200.04s | C 1200.04s |
| 6 | shadowfiend-ii | england / england | Multi1 | rush / 4502 | W 981.76s | C 1200.04s |
| 7 | shadowfiend-ii | england / russia | Multi0 | normal / 4503 | W 577.36s | C 1200.04s |
| 8 | shadowfiend-ii | russia / england | Multi1 | rush / 4504 | L 986.08s | C 1200.04s |
| 9 | sidestep | england / england | Multi0 | rush / 4505 | C 1200.04s | L 1146.16s |
| 10 | sidestep | russia / russia | Multi1 | normal / 4506 | W 639.28s | W 635.44s |
| 11 | trapped | england / england | Multi0 | normal / 4507 | W 855.52s | C 1200.04s |
| 12 | trapped | russia / russia | Multi1 | rush / 4508 | L 1004.08s | C 1200.04s |

Paired transitions list the baseline outcome followed by the candidate outcome. W → L and L → W are direct terminal regressions and improvements; transitions involving C leave at least one outcome unresolved.

| Transition | Conditions |
|---|---|
| C → C | 3, 5 |
| C → L | 9 |
| L → C | 8, 12 |
| L → L | 1, 2, 4 |
| W → C | 6, 7, 11 |
| W → W | 10 |

## Held-out subgroups

| Dimension | Group | v2.4 W/L/C | Final B W/L/C |
|---|---|---:|---:|
| map | shadowfiend-ii | 2/1/1 | 0/0/4 |
| map | sidestep | 1/1/2 | 1/2/1 |
| map | trapped | 1/3/0 | 0/2/2 |
| own_faction | england | 3/1/2 | 0/2/4 |
| own_faction | russia | 1/4/1 | 1/2/3 |
| opponent | normal | 3/1/2 | 1/1/4 |
| opponent | rush | 1/4/1 | 0/3/3 |
| own_side | Multi0 | 2/2/2 | 0/3/3 |
| own_side | Multi1 | 2/3/1 | 1/1/4 |

## Development and ablations

These conditions were inspected during iteration and used for selection. The incomplete ablation sets are intentional. They provide diagnostics, not an independent estimate of performance.

| Policy | Development 1 | Development 2 | Development 3 | Development 4 | W/L/C |
|---|---|---|---|---|---:|
| released_v24 | C 1200.04s | W 738.40s | C 1200.04s | W 1130.08s | 2/0/2 |
| candidate_a | L 942.88s | W 587.92s | L 1000.72s | L 954.88s | 1/3/0 |
| candidate_b | W 782.80s | W 556.48s | W 1135.84s | L 1013.92s | 3/1/0 |
| candidate_c | C 1200.04s | W 636.40s | C 1200.04s | L 836.56s | 1/1/2 |
| ablation_old_combat | C 1200.04s | not run | not run | W 1130.08s | 1/0/1 |
| ablation_old_defense | W 1167.76s | not run | not run | L 854.80s | 1/1/0 |
| ablation_old_economy | L 1001.20s | not run | not run | L 954.88s | 0/2/0 |
| ablation_old_goal | W 1101.76s | not run | not run | L 732.40s | 1/1/0 |
| ablation_old_goal_defense | not run | not run | not run | W 1130.08s | 1/0/0 |

Candidate A regressed badly and was rejected. A blocked scout destination optimization had changed tie ordering; B restored the previous sweep behavior. Candidate C reserved ordinary scouts before defense and was rejected after worse development results and a lone-guard scouting regression.

Development 4 exposes an unresolved interaction: B lost where v2.4 won. Replacing only the old goal selection or only the old defense/scout order still lost; replacing both restored the v2.4 win. This does not establish that the first observed command divergence alone caused the loss. The known regression was recorded before held-out evaluation.

## Reproducibility and limits

All completed reports are retained in records, including rejected candidates and losses. The exact source deltas, file manifests, engine patch, map package hashes, declarations and final selection freeze are included. Four early reports lack the later source-hash fields; README.md identifies them and explains the retrospective evidence. The remaining reports include a source fingerprint and an unchanged-during-run check.

The controlled policy receives only its fog-filtered seat observation plus public static map/rule data. Stock AI may use privileged engine information. The local adapter approximates the current platform schema and lacks exact per-command acknowledgments. Terminal detection and deterministic local randomness were instrumented; no game balance changes were made. See ADAPTER_CALIBRATION.md for specific differences.

Remaining tactical limitation: a read-only inspection of held-out condition 1 found both versions sending infantry directly at a visible gun turret while their tanks were still approaching with attack-move orders. Another gun turret then became visible, creating overlapping fire. This suggests formation timing and turret engagement remain weak; it is an observation, not proof of the sole cause of defeat. No fix was made from this held-out inspection.

Twelve paired conditions are a small fixed sample across three maps and two stock AI configurations. Counts describe this suite only and do not demonstrate platform win rate, general dominance, SOTA status, or guaranteed wins. No score-based winner was fabricated for censored runs.

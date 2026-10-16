# v2.5 local engine evaluation

The independently evaluated second-stage candidate is candidate_f. Eight new conditions were declared before their results existed and the candidate was selected and frozen before these matches. Stage-1 results were used for subsequent diagnosis and are not counted as independent evidence for this candidate.

W/L/C means terminal wins, terminal losses, and runs still undecided at the 1,200-second limit. C is censored, not a draw. All matches are local instrumented OpenRA tests against stock AI, not official platform matches.

## Stage 2: independent paired evaluation

| Policy | Completed / planned | W/L/C |
|---|---:|---:|
| released_v24 | 8 / 8 | 3/2/3 |
| candidate_f | 8 / 8 | 4/0/4 |

| Condition | Map | Own / enemy faction | Seat | AI / seed | v2.4 | Candidate |
|---|---|---|---|---|---|---|
| 1 | sidestep | russia / england | Multi0 | normal / 5501 | W 1010.80s | C 1200.04s |
| 2 | sidestep | england / russia | Multi1 | rush / 5502 | W 543.76s | W 591.04s |
| 3 | sidestep | england / england | Multi0 | normal / 5503 | C 1200.04s | W 703.36s |
| 4 | trapped | russia / russia | Multi1 | rush / 5504 | C 1200.04s | W 860.80s |
| 5 | trapped | england / russia | Multi0 | rush / 5505 | W 925.60s | C 1200.04s |
| 6 | trapped | russia / england | Multi1 | normal / 5506 | C 1200.04s | C 1200.04s |
| 7 | shadowfiend-ii | russia / russia | Multi0 | rush / 5507 | L 674.32s | W 717.28s |
| 8 | shadowfiend-ii | england / england | Multi1 | normal / 5508 | L 882.64s | C 1200.04s |

Transitions show v2.4 followed by the candidate. L → W and W → L are direct terminal improvements and regressions. Any transition involving C leaves at least one outcome unresolved.

| Transition | Conditions |
|---|---|
| C → C | 6 |
| C → W | 3, 4 |
| L → C | 8 |
| L → W | 7 |
| W → C | 1, 5 |
| W → W | 2 |

| Dimension | Group | v2.4 W/L/C | Candidate W/L/C |
|---|---|---:|---:|
| map | shadowfiend-ii | 0/2/0 | 1/0/1 |
| map | sidestep | 2/0/1 | 2/0/1 |
| map | trapped | 1/0/2 | 1/0/2 |
| own_faction | england | 2/1/1 | 2/0/2 |
| own_faction | russia | 1/1/2 | 2/0/2 |
| opponent | normal | 1/1/2 | 1/0/3 |
| opponent | rush | 2/1/1 | 3/0/1 |
| own_side | Multi0 | 2/1/1 | 2/0/2 |
| own_side | Multi1 | 1/1/2 | 2/0/2 |

## Stage 2: development

These inspected conditions informed selection. The fifth column reuses first-stage held-out condition 7 under a new explicit development ID and the identical frozen map. Its old v2.4/B reports are included here only as diagnostic references, not new independent observations.

| Policy | Original dev 1 | Original dev 2 | Original dev 3 | Original dev 4 | Reused condition 7 |
|---|---|---|---|---|---|
| released_v24 | C 1200.04s | W 738.40s | C 1200.04s | W 1130.08s | W 577.36s |
| candidate_b | W 782.80s | W 556.48s | W 1135.84s | L 1013.92s | C 1200.04s |
| candidate_d | C 1200.04s | C 1200.04s | W 640.00s | L 826.00s | W 560.56s |
| candidate_e | W 782.80s | W 556.48s | W 1135.84s | L 1013.92s | W 1041.04s |
| candidate_f | W 782.80s | W 556.48s | W 1135.84s | L 1013.92s | W 1041.04s |

## Preserved first stage

The original twelve reserved conditions evaluated unchanged B: v2.4 finished 4W/5L/3C and B finished 1W/4L/7C. B did not establish stronger performance and was rejected for release. A and C were also rejected. Their full results, every ablation and the historical first-stage paired/subgroup tables remain in SUMMARY.phase1.md, results.phase1.json and records. They are not pooled with the eight new pairs.

## Scope and remaining limits

The engine receives real unit orders and supplies the controlled seat’s fog-filtered observations. Public static rules/maps are allowed; the spatial tensor and enriched enemy fields are excluded. Stock AI may use privileged engine information. The adapter approximates the current platform schema, reconstructs events and does not provide faithful per-order acknowledgments. See ADAPTER_CALIBRATION.md.

Source manifests/deltas, original declarations, phase-specific selection freezes, map hashes, raw-report bodies and trace hashes are retained. Four early first-stage reports lack in-run fingerprints and are documented. Later runtime fingerprints verify unchanged policy files. D’s development manifest explicitly records its delayed creation after a digest-format mismatch; it was not backdated.

Formation timing and attacks into overlapping turrets remain tactical limitations seen in first-stage condition 1. The search revisions do not claim to repair that engagement behavior. Known development regressions remain visible in the table above.

DIAGNOSTICS_STAGE2.md and stage2-diagnostics.json retain each condition’s terminal time, destroyed/lost cost, remaining assets and own-harvester observations. These diagnostics are not converted into wins for censored games.

Eight paired conditions provide only a small fixed sample. They cannot establish platform win rate, general dominance, SOTA status or guaranteed wins. Censored games are not converted into score-based wins, and losses and rejected versions remain in the record.

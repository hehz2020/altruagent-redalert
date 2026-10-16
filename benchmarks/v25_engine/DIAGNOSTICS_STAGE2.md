# Stage 2 own-seat diagnostics

Own-seat observation and report diagnostics only. These do not change terminal outcomes.

All monetary values below are engine-reported unit/building cost totals or remaining assets. Censored outcomes stay censored. Mining fields are descriptive observations, not inferred income or a replacement winner calculation.

| Case | Policy | Outcome / seconds | Destroyed / lost cost | Assets | Max / last observed harvesters | First four | First HP drop | First disappearance | Idle samples |
|---|---|---|---:|---:|---:|---|---|---|---:|
| 1 | released_v24 | win / 1010.80 | 73400 / 24600 | 30250 | 4 / 4 | 291.28s | none observed | none observed | 0.03% |
| 1 | candidate_f | censored / 1200.04 | 71350 / 50400 | 10100 | 4 / 4 | 291.28s | 680.56s | none observed | 0.58% |
| 2 | released_v24 | win / 543.76 | 25550 / 10200 | 24750 | 4 / 4 | 266.08s | 352.00s | none observed | 0.36% |
| 2 | candidate_f | win / 591.04 | 27900 / 9650 | 28950 | 4 / 4 | 266.08s | 355.60s | none observed | 0.20% |
| 3 | released_v24 | censored / 1200.04 | 53650 / 21000 | 38350 | 4 / 4 | 269.44s | none observed | none observed | 0.00% |
| 3 | candidate_f | win / 703.36 | 46100 / 7150 | 37350 | 5 / 5 | 269.44s | none observed | none observed | 0.00% |
| 4 | released_v24 | censored / 1200.04 | 60400 / 14850 | 44850 | 4 / 4 | 311.44s | 832.00s | none observed | 0.00% |
| 4 | candidate_f | win / 860.80 | 38550 / 16250 | 30000 | 4 / 4 | 311.44s | none observed | none observed | 0.00% |
| 5 | released_v24 | win / 925.60 | 51550 / 14900 | 34350 | 4 / 4 | 276.40s | 362.80s | none observed | 0.18% |
| 5 | candidate_f | censored / 1200.04 | 31000 / 13100 | 48600 | 4 / 4 | 276.40s | 363.76s | none observed | 0.21% |
| 6 | released_v24 | censored / 1200.04 | 64400 / 42650 | 20350 | 4 / 4 | 318.16s | 569.44s | none observed | 0.00% |
| 6 | candidate_f | censored / 1200.04 | 54650 / 10850 | 49250 | 4 / 4 | 318.16s | none observed | none observed | 0.00% |
| 7 | released_v24 | lose / 674.32 | 16500 / 22700 | 0 | 4 / 3 | 287.68s | 322.24s | 350.56s | 1.97% |
| 7 | candidate_f | win / 717.28 | 37650 / 7850 | 36350 | 5 / 5 | 287.68s | 322.00s | none observed | 2.24% |
| 8 | released_v24 | lose / 882.64 | 28200 / 46950 | 0 | 4 / 4 | 274.96s | 810.88s | none observed | 0.73% |
| 8 | candidate_f | censored / 1200.04 | 62300 / 39150 | 28150 | 4 / 4 | 274.96s | 1084.24s | none observed | 0.14% |

A disappearance is not independently certified death; unit ownership or representation can change. HP percentages are rounded and observed at decision intervals. The final terminal cleanup is not inserted into the trace, while the final report can show zero actors after defeat. Idle=true measures the exposed flag, not productive mining time. Full definitions, cash/ore snapshots, order counts and trace hashes are in stage2-diagnostics.json.

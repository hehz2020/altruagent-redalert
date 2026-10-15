# Local Red Alert benchmark

Date: 2026-10-15 UTC. This reports a local development and held-out comparison, not an AltruAgent tournament result or a claim of the strongest publicly available bot. Machine-readable aggregate results accompany this report in `BENCHMARK_RESULTS.json`.

## Selection and main findings

On the eight held-out conditions, the frozen v2.2 policy won 3 and lost 5; v2.1 won 2 and lost 6. All were engine terminal outcomes. One paired condition changed from loss to win (Trapped / Normal / seed 101 / Multi0); the other seven had the same win/loss outcome. Both policies lost all four England/Multi1 cases; faction, side and seed are coupled, so this cannot establish a faction-specific cause. The result does not establish a general improvement, reliable winning, or strongest-bot status.

The v2.1 baseline lost all four training cases. The later `combined_v24` and `muster_v25` each won two: v24 won both Rush cases and lost both Normal cases; v25 did the reverse. The selected base was v24 because v25 also suffered a 317-second Rush loss. This choice was recorded before holdout began; v24 was not uniquely best on the training win count.

The final v2.2 policy adds only a confirmed last-harvester income-reserve correction to v24. Its `recovery_v26` check reproduced the same outcomes, durations and military summary statistics in all four training conditions, including both Normal losses. `final_v22` is that frozen logic with only the package version string changed. No further strategy tuning used the holdout outcomes.

## Conditions and interpretation

- Engine base: the platform-observed commit [`9b271c1a5562a07deeb1c3f81d9a556cd563a676`](https://github.com/yxc20089/OpenRA/tree/9b271c1a5562a07deeb1c3f81d9a556cd563a676). This is an instrumented local build.
- Starting conditions: 5000 cash, MCV only, unexplored map, fog enabled, crates enabled, kill bounties disabled, short game enabled; 25 ticks per simulated second. Both shared and local RNG use the listed seed.
- The policy sees only its own fog-filtered seat observations and public static rules. Referee statistics are read only after the policy loop stops and never enter policy input. Stock engine AI may have privileged information.
- Every tabulated run uses nearest integer-percent HP. Platform observations contained integer HP, but the exact upstream rounding formula was unavailable.
- Requested advancement is 4 ticks; the bridge advances request+1, yielding observations every 0.2 simulated seconds. Direct local gRPC has no live network latency, MCP grants/leases, platform truncation, or faithful delayed per-command acknowledgements. These results do not measure live server responsiveness.
- Training uses Sidestep with Russia versus Russia: seed 2/Multi0 starts at (23,44), seed 3/Multi1 at (74,53). Holdout uses Trapped and Shadowfiend-II, with Multi0 Russia and Multi1 England. Seed, side and faction are coupled conditions, not a full factorial randomized tournament.
- Stock Normal/Rush opponents do not establish performance against strong community bots, platform entrants or Spearhead. Small, selected development samples cannot establish SOTA or a future win probability.

**Result sources.** Engine wins/losses come from the own player's terminal `WinState`. Time-limit results, when available, are separate local referee decisions using the [public scoring rule](https://platform.altruagent-game.com/skill/redalert): compare net destroyed cost (`kills_cost - deaths_cost`), then remaining assets if tied; equality is a draw. The local referee samples both seats at the same cutoff tick. The platform uses its latest observations, so sampling may differ; local scoring is not an official platform-returned result. Missing referee data leaves a capped run unresolved. K and D mean the own seat's destroyed/lost cost, not unit counts or the opponent's score.

## Training: unified integer-HP adapter

All 16 original training cases are retained below. The original capped v23 case remains recorded as unfinished; its separately documented same-condition replay is not an additional independent sample.

| Policy | Engine wins | Engine losses | Local score wins / losses / draws | Unresolved |
|---|---:|---:|---:|---:|
| v21 | 0 | 4 | 0 / 0 / 0 | 0 |
| macro_v23 | 1 | 2 | 0 / 0 / 0 | 1 |
| combined_v24 | 2 | 2 | 0 / 0 / 0 | 0 |
| muster_v25 | 2 | 2 | 0 / 0 / 0 | 0 |

| Policy | Map | Own side | Own / enemy faction | Opponent | Seed | Outcome | Result source | Seconds | K | D | Policy hash |
|---|---|---|---|---|---:|---|---|---:|---:|---:|---|
| v21 | sidestep | Multi0 | russia / russia | Normal | 2 | Loss | Engine | 648.48 | 2650 | 22000 | `6066833a94a0` |
| v21 | sidestep | Multi1 | russia / russia | Normal | 3 | Loss | Engine | 864.28 | 7800 | 21100 | `6066833a94a0` |
| v21 | sidestep | Multi0 | russia / russia | Rush | 2 | Loss | Engine | 528.48 | 1300 | 19100 | `6066833a94a0` |
| v21 | sidestep | Multi1 | russia / russia | Rush | 3 | Loss | Engine | 684.48 | 8850 | 24100 | `6066833a94a0` |
| macro_v23 | sidestep | Multi0 | russia / russia | Normal | 2 | Win | Engine | 707.88 | 42950 | 15700 | `91ba2285bbe3` |
| macro_v23 | sidestep | Multi1 | russia / russia | Normal | 3 | Loss | Engine | 972.28 | 22800 | 44000 | `91ba2285bbe3` |
| macro_v23 | sidestep | Multi0 | russia / russia | Rush | 2 | Loss | Engine | 572.28 | 5300 | 29450 | `91ba2285bbe3` |
| macro_v23 | sidestep | Multi1 | russia / russia | Rush | 3 | Unfinished | Cap | 1200.08 | 95150 | 32200 | `91ba2285bbe3` |
| combined_v24 | sidestep | Multi0 | russia / russia | Normal | 2 | Loss | Engine | 1039.48 | 40000 | 50300 | `fe35bd23ffad` |
| combined_v24 | sidestep | Multi1 | russia / russia | Normal | 3 | Loss | Engine | 1137.08 | 42450 | 52750 | `fe35bd23ffad` |
| combined_v24 | sidestep | Multi0 | russia / russia | Rush | 2 | Win | Engine | 836.48 | 61200 | 12900 | `fe35bd23ffad` |
| combined_v24 | sidestep | Multi1 | russia / russia | Rush | 3 | Win | Engine | 576.28 | 30500 | 9650 | `fe35bd23ffad` |
| muster_v25 | sidestep | Multi0 | russia / russia | Normal | 2 | Win | Engine | 893.28 | 56550 | 17200 | `718681d974b8` |
| muster_v25 | sidestep | Multi1 | russia / russia | Normal | 3 | Win | Engine | 804.28 | 50950 | 13300 | `718681d974b8` |
| muster_v25 | sidestep | Multi0 | russia / russia | Rush | 2 | Loss | Engine | 820.68 | 26200 | 41100 | `718681d974b8` |
| muster_v25 | sidestep | Multi1 | russia / russia | Rush | 3 | Loss | Engine | 317.08 | 2600 | 15900 | `718681d974b8` |

### Candidate changes

- `v21`: v2.1 baseline, source commit `23244f627875867e3c2354c04e3624589a17ce96`.
- `macro_v23`: protect economic recovery/growth and funds for an initial heavy-tank core.
- `combined_v24`: v23 economy plus committed retreats despite temporary loss of enemy vision, and prevention of depleted armies renewing attack commitment indefinitely. Original attack thresholds remain.
- `muster_v25`: v24 with attack thresholds of value 2800 and at least 8 main units, or value 3500 and at least 3; the 3-unit fallback applies only with under 90 seconds remaining. This was a strategy experiment.
- `recovery_v26`: v24 plus the last-harvester income-reserve correction; `final_v22` differs only in the package version string.

### Same-condition v23 scoring replay

The original Rush/seed 3/Multi1 run reached 1200.08 seconds without a terminal engine result. After referee instrumentation was available, the same frozen policy and condition were replayed: all 6000 observations and decisions through tick 29997 matched, excluding session identity. At tick 30000 the local score was `(62950, 33400)` versus `(-62950, 2300)`, a local score win with `engine_done=false`. This adds scoring evidence to that condition; it is not a fifth v23 test, an elimination win, or an official platform win. Accounting for that evidence gives v23 one engine win, one same-condition local score win and two losses. It did not change the preselected v24 base.

## Recovery correction: repeated training conditions

These four repeats validate the small bug fix; they are not holdout and are not pooled with training or holdout denominators.

| Policy | Map | Own side | Own / enemy faction | Opponent | Seed | Outcome | Result source | Seconds | K | D | Policy hash |
|---|---|---|---|---|---:|---|---|---:|---:|---:|---|
| recovery_v26 | sidestep | Multi0 | russia / russia | Normal | 2 | Loss | Engine | 1039.48 | 40000 | 50300 | `a5d698ad7662` |
| recovery_v26 | sidestep | Multi1 | russia / russia | Normal | 3 | Loss | Engine | 1137.08 | 42450 | 52750 | `a5d698ad7662` |
| recovery_v26 | sidestep | Multi0 | russia / russia | Rush | 2 | Win | Engine | 836.48 | 61200 | 12900 | `a5d698ad7662` |
| recovery_v26 | sidestep | Multi1 | russia / russia | Rush | 3 | Win | Engine | 576.28 | 30500 | 9650 | `a5d698ad7662` |

## Holdout: frozen final v2.2 versus v2.1

Eight new conditions were fixed before testing: each of Trapped and Shadowfiend-II against Normal/Rush on both fixed sides, seeds 101–104 and 111–114. Both frozen policies run every condition. Selection was recorded at `2026-10-15T03:36:09.947806+00:00`; holdout began at `2026-10-15T03:38:48.547983+00:00`. Status: 16/16 runs complete.

| Policy | Engine wins | Engine losses | Local score wins / losses / draws | Unresolved |
|---|---:|---:|---:|---:|
| v21 | 2 | 6 | 0 / 0 / 0 | 0 |
| final_v22 | 3 | 5 | 0 / 0 / 0 | 0 |

| Policy | Map | Own side | Own / enemy faction | Opponent | Seed | Outcome | Result source | Seconds | K | D | Policy hash |
|---|---|---|---|---|---:|---|---|---:|---:|---:|---|
| v21 | trapped | Multi0 | russia / england | Normal | 101 | Loss | Engine | 852.28 | 6500 | 21900 | `6066833a94a0` |
| final_v22 | trapped | Multi0 | russia / england | Normal | 101 | Win | Engine | 783.48 | 34250 | 11700 | `dabc39191f01` |
| v21 | trapped | Multi1 | england / russia | Normal | 102 | Loss | Engine | 726.28 | 5800 | 18700 | `6066833a94a0` |
| final_v22 | trapped | Multi1 | england / russia | Normal | 102 | Loss | Engine | 660.08 | 7400 | 26650 | `dabc39191f01` |
| v21 | trapped | Multi0 | russia / england | Rush | 103 | Win | Engine | 467.68 | 22800 | 4500 | `6066833a94a0` |
| final_v22 | trapped | Multi0 | russia / england | Rush | 103 | Win | Engine | 633.08 | 37350 | 3200 | `dabc39191f01` |
| v21 | trapped | Multi1 | england / russia | Rush | 104 | Loss | Engine | 512.08 | 3700 | 14400 | `6066833a94a0` |
| final_v22 | trapped | Multi1 | england / russia | Rush | 104 | Loss | Engine | 433.28 | 2750 | 19150 | `dabc39191f01` |
| v21 | shadowfiend-ii | Multi0 | russia / england | Normal | 111 | Loss | Engine | 606.28 | 3750 | 19300 | `6066833a94a0` |
| final_v22 | shadowfiend-ii | Multi0 | russia / england | Normal | 111 | Loss | Engine | 886.08 | 19450 | 37400 | `dabc39191f01` |
| v21 | shadowfiend-ii | Multi1 | england / russia | Normal | 112 | Loss | Engine | 768.08 | 3700 | 20300 | `6066833a94a0` |
| final_v22 | shadowfiend-ii | Multi1 | england / russia | Normal | 112 | Loss | Engine | 730.88 | 16950 | 35450 | `dabc39191f01` |
| v21 | shadowfiend-ii | Multi0 | russia / england | Rush | 113 | Win | Engine | 713.28 | 39400 | 4300 | `6066833a94a0` |
| final_v22 | shadowfiend-ii | Multi0 | russia / england | Rush | 113 | Win | Engine | 836.28 | 58950 | 10100 | `dabc39191f01` |
| v21 | shadowfiend-ii | Multi1 | england / russia | Rush | 114 | Loss | Engine | 508.08 | 3850 | 15000 | `6066833a94a0` |
| final_v22 | shadowfiend-ii | Multi1 | england / russia | Rush | 114 | Loss | Engine | 705.08 | 14100 | 34300 | `dabc39191f01` |

### Local referee scores, separate from engine terminal results

| Phase / case | Tick | Own (net cost, assets) | Opponent (net cost, assets) | Local outcome |
|---|---:|---|---|---|
| training_score_replay / int_macro_v23_rush_s3_Multi1_score_replay | 30000 | (62950, 33400) | (-62950, 2300) | Win |

## Provenance and checks

Each completed row was checked against its condition manifest, frozen policy hash, per-match metadata, summary, and final own-seat trace. Suite result records were also checked when finalized. The accompanying JSON contains only aggregate outcomes and provenance, without player traces, local paths, session identities, or credentials.

The engine has three documented evaluation patches: (1) report the own player's already-determined `WinState` because the headless UI delay queue is absent; (2) optionally seed `World.LocalRandom`; (3) emit both seats' final statistics to a referee-only channel after tick 30000, disabled by default and never added to observations. The third patch was added after the original 16-case training group and before the scoring replay, recovery validation and holdout. None changes unit statistics, combat rules, physics or visibility. One earlier 120-second repeatability check matched observations and orders after removing session identity; that alone does not prove universal full-match determinism.

| Instrumentation | Patch SHA-256 |
|---|---|
| own-seat terminal reporting | `56dc0653b1768ce11f63688b33adb0d7d33faa623432e3922f92eb74701d94ee` |
| optional local RNG seed for repeatable evaluation | `70a369a10e8fbfb92ed4dade638b387958db7144672ab9e6c1beeec9b81bb60d` |
| post-cutoff referee-only stderr telemetry | `ff798bc53171679977a3f55ffd25500fd2a19099b4cec6827bee9352b5fa7c20` |

Policy SHA-256 hashes concatenate each sorted `altru_redalert/*.py` filename and its bytes. They identify policy files, not the Windows executable, whole repository or evaluator.

| Policy | Full SHA-256 |
|---|---|
| v21 | `6066833a94a0c0fe6cf4588fac327b2a72d5685bfae6b24f1cccc4220b80cf4b` |
| macro_v23 | `91ba2285bbe359380ebb6ef73544f772eeea5cdbfbbf537aa05708fc37eec78b` |
| combined_v24 | `fe35bd23ffadddb977371adbc6ab0d15f9831697fb1f28a3c5545f5e1e02989d` |
| muster_v25 | `718681d974b8a5e855437418c9b79e08ce52854f476ad21cbdf90c662b8eeb9d` |
| recovery_v26 | `a5d698ad7662e87b3380034483e9c938082a0a456d260468f9bc2906761ba35a` |
| final_v22 | `dabc39191f013d31b6b09ca0e816ec98f80aa34f1035c07e79d4bcfeb9bb81ba` |

## Earlier exploratory runs

Earlier floating-point-HP runs, including the paired v22/retreat-v22 experiments, are excluded from this calibrated dataset and are not pooled into any reported rate. The first exploratory runs also preceded fixed local RNG, terminal reporting or corrected observation cadence. They helped identify defects and design candidates. This report preserves every run in the finalized integer-HP selection, recovery-validation and holdout manifests, including losses; supplemental scoring replay is separately identified.

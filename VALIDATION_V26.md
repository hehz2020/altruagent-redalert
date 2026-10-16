# v2.6 validation

The selected runtime is frozen. Local policy and launcher tests and all 30 paired engine comparisons are complete. The observed results favor this version in this sample, but do not establish a general win-rate improvement.

Source baseline: `6551e29ad961ab656a6b4fdd34f6a00eda0d2180` (v2.5), source tree `6e8dfc203d40542a04d37fe2fa739942e3bab9be`. v2.6 is developed separately on `improvement/v26-ryan`; the baseline and frozen evaluation engine are retained unchanged.

Selected v2.6 runtime package SHA256: `93dea14bd76235d5d4dda9e4eee93312b2eb1effdc87c1c277cdcb19cf5f2784`. This is the SHA256 of the canonical sorted file-to-SHA256 mapping, not a Git commit or a hash of a ZIP. Each experiment contains the exact runtime files and their individual hashes.

## Implemented behavior

- Reserve four opening rifle infantry, leaving a small home screen after one unit scouts. When a factory has just become ready, allow a short grace period for legal cheap escort options before choosing optional development.
- Detect a group of at least four visible armed infantry approaching key assets, with an alert that expires after contact ends. During this alert, prioritize affordable defense and defer optional depot or additional-harvester spending.
- Cancel at most one optional unfinished commitment at a time when needed for defense. Preserve essential income and power, do not cancel a ready structure, and wait for observed funds before spending a refund.
- Keep emergency recall assignments across observations, with bounded release conditions. A brief visibility or incident-radius gap must not immediately send reinforcements back toward the enemy.
- Give each defensive post independent retreat state and a bounded refuge, reducing repeated move/attack reversals. Choose scouts only after allocating defenders.

These decisions use legal observations and public configuration. There are no branches keyed to an opponent's name or private information.

## Tests and build identity

Local command: `python -m pytest tests redalert_bot_tests windows/tests -q`.

Selected-source result: **1,107 tests and 24 subtests passed**, recorded in `arena/eval_v26/full-tests-04.log`. New scenarios cover opening defense budgets, factory readiness, optional-production cancellation, waiting for an observed refund, recall persistence, independent retreats and scout/defender allocation. This result replaces the earlier candidate's 1,103-test result.

The Windows workflow repeats the full suite, builds a native x64 executable and tests that executable's controller, spawned worker and persistent MCP fixture. A source test run alone is not a native EXE test. Native-build success is not claimed by this document. The completed package's `build-info.json` records the source commit, `controller_package_sha256`, individual `controller_files_sha256` and executable hash. Match its runtime digest to the value above; `self-test.json` and `SHA256SUMS.txt` supply the build's executable-check evidence.

Python sources are checked out with LF line endings on both platforms so their byte hashes remain comparable. This branch builds an artifact; only `main` publishes a Release.

## Frozen-source engine comparison

Only complete valid baseline/candidate pairs enter this table. Both versions run against the same fixed opponent revision, map, seed, seat, factions, rules and timing mode. The baseline is rerun rather than replaced by historical results.

The more relevant comparison is the **24 held-out and regression pairs not used for further tuning: v2.6 won 22 and lost 2; v2.5 won 21 and lost 3**. That is one additional win in this sample. The six original development conditions do not count as independent validation.

| Cohort | Valid paired conditions | v2.5 baseline | v2.6 | Use |
| --- | ---: | --- | --- | --- |
| `original-02`: Ryan, original seeds | 6 | 5 wins, 1 loss | 6 wins, 0 losses | Development conditions, not independent validation |
| `validation-01`: Ryan, held-out seeds | 12 | 10 wins, 2 losses | 11 wins, 1 loss | Candidate frozen before these outcomes; no later policy tuning |
| `validation-01`: six other opponents | 12 | 11 wins, 1 loss | 11 wins, 1 loss | Regression comparison |
| Total, including development conditions | 30 | 26 wins, 4 losses | 28 wins, 2 losses | 4 improved pairs, 2 worsened, 24 unchanged |

No games were drawn. The total mixes development and validation conditions for accounting; the held-out cohort remains separately identified rather than treating all 30 conditions as independent validation.

The original Ryan conditions cover Trapped seed 1729, Sidestep 1730 and Shadowfiend II 1731, each in both seats. Held-out conditions use seed bases 27183 and 31415, plus map offsets 0/1/2, again in both seats. The other opponents are Henry, Friendly, William, Khuong, Riffo and Pakled, with one preregistered map each and both seats. Their exact conditions are in `arena/eval_v26/preregistered_cases.json`.

Each match uses a 20-minute game-time limit, a fresh frozen OpenRA engine, measured think latency and at most two concurrent games. The engine runs construction, gathering, movement, combat and fog. The lobby has 5,000 starting cash, no starting army, unexplored terrain, no kill bounties and **random crates enabled**. All external language-model components are disabled, using each public program's rule-based policy or native fallback. These results do not represent model-assisted tournament configurations or confirm that a repository belongs to an actual entrant.

### Observed regression

The regression cohort improved against Henry on Trapped in our seat 0 and worsened against Friendly on Sidestep in our seat 1; the other ten paired outcomes were unchanged. The Friendly loss is a valid game outcome, not an adapter failure, and remains in the counts. In that game, the candidate's first heavy tank was requested at 204.96 game seconds versus 184.32 for baseline, and the three-tank departure was at 289.92 versus 269.28. Earlier flak-vehicle and rocket-infantry production accompanied that delay. This is a concrete trade-off worth monitoring, not proof that one change alone caused the loss.

The Friendly runs also differed in early enemy infantry counts despite matching initial conditions. Measured decision timing and enabled random crates can produce different trajectories even with the same initial seed. No direct crate-pickup event was recorded, so a crate reward is an unconfirmed explanation and is not treated as an established cause.

## Invalid attempts and retries

| Selected-runtime experiment | Game attempts | Valid individual games | Invalid attempts | Valid pairs |
| --- | ---: | ---: | ---: | ---: |
| `original-02` | 14 | 13 | 1 | 6 |
| `validation-01` | 52 | 50 | 2 | 24 |
| Total | 66 | 63 | 3 | 30 |

Three failed pairs were rerun in both arms. Their three earlier valid individual arms remain in the evidence but are excluded from comparative totals; exactly 60 games enter the 30 selected pairs. Invalid attempts are not counted as wins or losses.

Missing terminal evidence, adapter/process failures, timeouts and mismatched paired conditions are excluded. Every attempt and reason remains in the evidence package. Ordinary rejected game commands, such as a target leaving visibility, are measured separately and do not automatically make a game invalid.

The retry helper permits only the reviewed terminal-recording failure class, reruns both arms, and limits a pair to three attempts. It does not rerun a valid pair to seek a better outcome or alter scoring. Its decisions are recorded in each experiment's `finish_validation.jsonl` when the helper is used.

## Earlier development evidence

The following older candidate used runtime package SHA256 `f52126c99539bf85903759008f1614463957812a89699493bf6903cf04fee887`. These trials informed the factory-readiness fix and are excluded from the selected-runtime comparison above.

| Experiment | Evidence | Interpretation |
| --- | --- | --- |
| `screen-01` | 1 valid win, 1 invalid attempt, 1 planned game not started | Screening stopped after a terminal/runtime-recording failure |
| `screen-02` | 2 wins, 1 loss in three previously lost Ryan cases | Selected development cases; no contemporaneous baseline arm |
| `original-01` | Five valid pairs: baseline 4 wins/1 loss; candidate 3 wins/2 losses | The earlier candidate performed worse in this comparison; one additional pair was invalid after terminal cleanup |

All early failures, incomplete work and less favorable results are preserved. They are not combined with held-out evaluation or used as evidence for the final runtime.

## Map adaptation and limits

The observation exposes `raw.map.id`; public configuration provides the map title, bounds, spawn points and static layout. Existing planning uses terrain paths, resource positions and expansion opportunities. This version does not add a named-map strategy selector or claim a battle-validated optimal strategy for each map. Such a claim would require comparisons across maps, starting seats and unseen seeds, followed by adaptation to observed enemy behavior.

Fixed seeds do not eliminate variation from measured decision latency, communication, machine scheduling or random events along different game trajectories. Full-engine results remain specific to the frozen revisions, adapters, conditions and time limit. A few additional wins in these small samples do not establish statistical superiority, platform tournament win rates or a guarantee of victory. No online match was created and no opponent author was contacted for these tests.

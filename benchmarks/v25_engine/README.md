# v2.5 local engine evaluation

These are development and held-out comparisons in a locally rebuilt, instrumented OpenRA engine. They are not official platform matches. Engine results use the controlled player's terminal WinState. Runs still undecided at 1,200 simulated seconds are censored, not counted as wins or draws. The original v2.3 benchmark and the v2.4 scenario tests describe different experiments.

The four development conditions and four initial reserved conditions were declared before the first full match. Before any reserved condition ran, eight more reserved conditions were declared, giving twelve reserved conditions balanced across three maps, both own factions, both seats and Normal/Rush AI. conditions.initial.json preserves the original declaration; heldout-declaration.json pins the expansion. evaluation-freeze.json retains its original conditions hash, which should be checked against conditions.initial.json. Development results may inform revisions and must not be pooled with held-out results. Every candidate and ablation is retained, including losses. Only the controlled seat's fog-filtered observations and public static rules/maps enter the policy. Stock AI can use privileged engine information. See ADAPTER_CALIBRATION.md for limitations.

The source baseline is public release e264fce0d48da86110c896cf39a720fdc52b02ba. policy-manifests contains file hashes. policy-deltas reconstructs every candidate and ablation from that baseline. conditions.json, map-manifest.json and instrumentation.patch retain the engine setup. results.json is a compact index; records retains each unedited result body, startup metadata, samples and a hash of its full observation/action trace. Raw traces remain evaluation intermediates and can be regenerated with the frozen setup.

New sessions receive different session IDs and wall-clock durations, so regenerated trace/result bytes need not match the retained digests. Those digests audit the original files; exact policy/map reconstruction is checked separately. Logical trajectories and outcomes can be compared independently of session metadata.

candidate_b was the first-stage frozen candidate. selection-freeze.json records its selection before any first-stage held-out result existed, including its known regression on development_4. It scored 1W/4L/7C versus v2.4's 4W/5L/3C and was rejected for release. A and C were also rejected. All results and reconstruction patches remain available. B stayed unchanged throughout its reserved evaluation.

Stage 2 selected candidate_f after investigating a general search-continuity issue and correcting search timers during regrouping, withdrawal and local combat. D and E are retained as intermediate development versions. The inspected first-stage held-out condition 7 has a new condition ID and stage2_development role; it cannot independently evaluate any of these later candidates. stage2-declaration.json reserved eight new conditions with seeds 5501–5508 before any of their results existed. stage2-selection-freeze.json records F's source fingerprints, selection time and known development regression before those matches began. F stays unchanged throughout that evaluation. SUMMARY.md separates the completed phases. Files with .phase1 in their names preserve the first-stage snapshots, and independent-audit.phase1.json records their audit. The original twelve conditions retain their historical role as independent evaluation of B only.

Two source hash formats are used. policy-manifests uses SHA256 of compact sorted JSON mapping relative filenames to file hashes. The adapter's policy_source_sha256 hashes the relative filenames and source bytes as a stream. They are different fingerprints of the same frozen files, not evidence that the source changed; selection-freeze.json names both formats explicitly.

Four runs began before a reporting-only adapter change added source-hash fields: released_v24 development_1/development_2 and candidate_a development_1/development_2. Their original reports remain unchanged and do not contain an in-run source fingerprint. Frozen policy manifests and filesystem timing provide retrospective provenance for these four runs. adapter-audit records the exact reporting diff and explicitly labels its earlier adapter snapshot as a reverse reconstruction. Observation, static-data and command conversion functions were unchanged. Later runs report source hashes themselves.

## Reproduce on Linux x64

Use Python 3.12, a C/C++ runtime, tar, patch and access to the public download sources. The setup fetches the pinned engine commit, .NET 8 SDK and official freeware assets; no platform key is used. The SDK and asset digests are checked. The platform's current config schema is approximated as documented, so this is not a platform-equivalence claim.

```bash
python -m venv .venv
.venv/bin/python setup.py --baseline-source /absolute/path/to/v24-checkout
.venv/bin/python -m pytest test_adapter.py -q
.venv/bin/python run_stage2.py --candidate candidate_f --mode development --workers 4
.venv/bin/python run_stage2.py --candidate candidate_f --mode held_out --workers 4
```

These commands reproduce F's five development cases and the eight new paired conditions for both v2.4 and F. To reproduce the historical first stage, use run_suite.py with policies/v24 or policies/candidate_b, the matching label, --phase development, then run_paired.py --candidate candidate_b --workers 4. Historical B reproduction is not a recommendation to deploy B.

The baseline checkout must be commit e264fce0d48da86110c896cf39a720fdc52b02ba; all policy file hashes are verified. If that option is omitted, setup tries the public GitHub archive. This workspace could fetch the engine archive but received 404 for the bot archive, so reconstruction was verified from the already authenticated v2.4 checkout.

run_paired.py runs the twelve declared held-out conditions for both policies, with four games in progress at most. It refuses to overwrite existing held-out reports. The checked-in records are separate from the local results directory used for new executions. Rejected candidates and ablations can be reproduced with their policy directory and the appropriate development condition; their incomplete condition sets are intentional.

run_stage2.py likewise refuses to overwrite reports. Its development mode selects only the original four development cases and the explicitly reused condition 7; its held_out mode selects only the eight new stage2_held_out conditions. summarize_stage2.py --candidate candidate_f regenerates SUMMARY.md from the checked-in records after the sixteen new reports are present.

diagnostics.py --candidate candidate_f reads the local results traces to derive own-harvester diagnostics. --verify-retained-traces additionally requires the original retained trace digests, and is for auditing the original runs, not new sessions. The published stage2-diagnostics.json was generated with that verification enabled.

conditions.phase1.json and map-manifest.phase1.json are the snapshots pinned by the first-stage expanded declaration and selection. conditions.initial.json remains the original eight-condition declaration. The current conditions.json also includes stage 2; the original rows and map packages are unchanged. The stage-2 development copy of condition 7 explicitly retains its original frozen map and Title, so setup reproduces that same package instead of changing the first-stage map.

Each case launches its own local daemon and checks its seat, factions, cash and initial MCV before decisions begin. Requested advancement is five ticks; this bridge generally returns one tick later. Both policies use the same actual observation schedule. The sampler records actual ticks and allows the terminal boundary to overshoot by one tick.

For individual conditions or ablations, use case_runner.py with --policy, --condition and --label. Do not reuse --seconds for an early-stop smoke of a long game: it also changes the horizon shown to the policy. A 90-second smoke was used only to check the build/deploy/production connection and was excluded from comparison results.

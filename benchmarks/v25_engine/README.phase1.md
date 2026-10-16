# v2.5 local engine evaluation

These are development and held-out comparisons in a locally rebuilt, instrumented OpenRA engine. They are not official platform matches. Engine results use the controlled player's terminal WinState. Runs still undecided at 1,200 simulated seconds are censored, not counted as wins or draws. The original v2.3 benchmark and the v2.4 scenario tests describe different experiments.

The four development conditions and four initial reserved conditions were declared before the first full match. Before any reserved condition ran, eight more reserved conditions were declared, giving twelve reserved conditions balanced across three maps, both own factions, both seats and Normal/Rush AI. conditions.initial.json preserves the original declaration; heldout-declaration.json pins the expansion. evaluation-freeze.json retains its original conditions hash, which should be checked against conditions.initial.json. Development results may inform revisions and must not be pooled with held-out results. Every candidate and ablation is retained, including losses. Only the controlled seat's fog-filtered observations and public static rules/maps enter the policy. Stock AI can use privileged engine information. See ADAPTER_CALIBRATION.md for limitations.

The source baseline is public release e264fce0d48da86110c896cf39a720fdc52b02ba. policy-manifests contains file hashes. policy-deltas reconstructs every candidate and ablation from that baseline. conditions.json, map-manifest.json and instrumentation.patch retain the engine setup. results.json is a compact index; records retains each unedited result body, startup metadata, samples and a hash of its full observation/action trace. Raw traces remain evaluation intermediates and can be regenerated with the frozen setup.

candidate_b is the final frozen candidate. selection-freeze.json records its selection before any held-out result existed, including its known regression on development_4. Candidates A and C were rejected; all their results and reconstruction patches remain available. No strategy changes are permitted based on the reserved evaluation results. SUMMARY.md separates development, ablation and held-out outcomes.

Two source hash formats are used. policy-manifests uses SHA256 of compact sorted JSON mapping relative filenames to file hashes. The adapter's policy_source_sha256 hashes the relative filenames and source bytes as a stream. They are different fingerprints of the same frozen files, not evidence that the source changed; selection-freeze.json names both formats explicitly.

Four runs began before a reporting-only adapter change added source-hash fields: released_v24 development_1/development_2 and candidate_a development_1/development_2. Their original reports remain unchanged and do not contain an in-run source fingerprint. Frozen policy manifests and filesystem timing provide retrospective provenance for these four runs. adapter-audit records the exact reporting diff and explicitly labels its earlier adapter snapshot as a reverse reconstruction. Observation, static-data and command conversion functions were unchanged. Later runs report source hashes themselves.

## Reproduce on Linux x64

Use Python 3.12, a C/C++ runtime, tar, patch and access to the public download sources. The setup fetches the pinned engine commit, .NET 8 SDK and official freeware assets; no platform key is used. The SDK and asset digests are checked. The platform's current config schema is approximated as documented, so this is not a platform-equivalence claim.

```bash
python -m venv .venv
.venv/bin/python setup.py --baseline-source /absolute/path/to/v24-checkout
.venv/bin/python -m pytest test_adapter.py -q
.venv/bin/python run_suite.py --policy "$PWD/policies/v24" --label released_v24 --phase development --workers 2
.venv/bin/python run_suite.py --policy "$PWD/policies/candidate_b" --label candidate_b --phase development --workers 2
.venv/bin/python run_paired.py --candidate candidate_b --workers 4
```

The baseline checkout must be commit e264fce0d48da86110c896cf39a720fdc52b02ba; all policy file hashes are verified. If that option is omitted, setup tries the public GitHub archive. This workspace could fetch the engine archive but received 404 for the bot archive, so reconstruction was verified from the already authenticated v2.4 checkout.

run_paired.py runs the twelve declared held-out conditions for both policies, with four games in progress at most. It refuses to overwrite existing held-out reports. The checked-in records are separate from the local results directory used for new executions. Rejected candidates and ablations can be reproduced with their policy directory and the appropriate development condition; their incomplete condition sets are intentional.

Each case launches its own local daemon and checks its seat, factions, cash and initial MCV before decisions begin. Requested advancement is five ticks; this bridge generally returns one tick later. Both policies use the same actual observation schedule. The sampler records actual ticks and allows the terminal boundary to overshoot by one tick.

For individual conditions or ablations, use case_runner.py with --policy, --condition and --label. Do not reuse --seconds for an early-stop smoke of a long game: it also changes the horizon shown to the policy. A 90-second smoke was used only to check the build/deploy/production connection and was excluded from comparison results.

from collections import Counter
from pathlib import Path
import argparse
import json


ROOT = Path(__file__).resolve().parent


def outcome(record):
    report = record['report']
    return {'win': 'W', 'lose': 'L'}[report['result']] if report['engine_done'] else 'C'


def counts(rows):
    total = Counter(outcome(row) for row in rows)
    return '/'.join(str(total[key]) for key in 'WLC')


def cell(record):
    return 'not run' if record is None else f"{outcome(record)} {record['report']['seconds']:.2f}s"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    conditions = json.loads((ROOT / 'conditions.json').read_text())['conditions']
    selected = [row for row in conditions if row['phase'] == 'stage2_held_out']
    records = {(path.parent.name, path.stem): json.loads(path.read_text()) for path in (ROOT / 'records').glob('*/*.json')}
    baseline = 'released_v24'
    candidate = args.candidate
    assert len(selected) == 8
    assert all((label, c['id']) in records for label in [baseline, candidate] for c in selected)
    lines = [
        '# v2.5 local engine evaluation', '',
        f'The independently evaluated second-stage candidate is {candidate}. Eight new conditions were declared before their results existed and the candidate was selected and frozen before these matches. Stage-1 results were used for subsequent diagnosis and are not counted as independent evidence for this candidate.', '',
        'W/L/C means terminal wins, terminal losses, and runs still undecided at the 1,200-second limit. C is censored, not a draw. All matches are local instrumented OpenRA tests against stock AI, not official platform matches.', '',
        '## Stage 2: independent paired evaluation', '',
        '| Policy | Completed / planned | W/L/C |', '|---|---:|---:|',
    ]
    for label in [baseline, candidate]:
        group = [records[(label, c['id'])] for c in selected]
        lines.append(f'| {label} | {len(group)} / 8 | {counts(group)} |')
    lines += ['', '| Condition | Map | Own / enemy faction | Seat | AI / seed | v2.4 | Candidate |', '|---|---|---|---|---|---|---|']
    transitions = {}
    for condition in selected:
        short = condition['id'].removeprefix('v25_stage2_held_out_')
        left, right = [records[(label, condition['id'])] for label in [baseline, candidate]]
        lines.append(f"| {short} | {condition['map']} | {condition['own_faction']} / {condition['enemy_faction']} | {condition['own_side']} | {condition['opponent']} / {condition['seed']} | {cell(left)} | {cell(right)} |")
        transitions.setdefault(outcome(left) + ' → ' + outcome(right), []).append(short)
    lines += ['', 'Transitions show v2.4 followed by the candidate. L → W and W → L are direct terminal improvements and regressions. Any transition involving C leaves at least one outcome unresolved.', '', '| Transition | Conditions |', '|---|---|']
    for transition, identifiers in sorted(transitions.items()):
        lines.append(f"| {transition} | {', '.join(identifiers)} |")
    lines += ['', '| Dimension | Group | v2.4 W/L/C | Candidate W/L/C |', '|---|---|---:|---:|']
    for dimension in ['map', 'own_faction', 'opponent', 'own_side']:
        for value in sorted({c[dimension] for c in selected}):
            group = [c for c in selected if c[dimension] == value]
            totals = [counts([records[(label, c['id'])] for c in group]) for label in [baseline, candidate]]
            lines.append(f'| {dimension} | {value} | {totals[0]} | {totals[1]} |')
    lines += ['', '## Stage 2: development', '',
        'These inspected conditions informed selection. The fifth column reuses first-stage held-out condition 7 under a new explicit development ID and the identical frozen map. Its old v2.4/B reports are included here only as diagnostic references, not new independent observations.', '',
        '| Policy | Original dev 1 | Original dev 2 | Original dev 3 | Original dev 4 | Reused condition 7 |', '|---|---|---|---|---|---|']
    labels = [baseline, 'candidate_b'] + sorted({label for label, _ in records if label.startswith('candidate_') and label not in {'candidate_a', 'candidate_b', 'candidate_c'}})
    for label in labels:
        identifiers = [f'v25_development_{i}' for i in range(1, 5)] + ['v25_held_out_7' if label in {baseline, 'candidate_b'} else 'v25_stage2_development_7']
        lines.append('| ' + ' | '.join([label] + [cell(records.get((label, identifier))) for identifier in identifiers]) + ' |')
    lines += ['', '## Preserved first stage', '',
        'The original twelve reserved conditions evaluated unchanged B: v2.4 finished 4W/5L/3C and B finished 1W/4L/7C. B did not establish stronger performance and was rejected for release. A and C were also rejected. Their full results, every ablation and the historical first-stage paired/subgroup tables remain in SUMMARY.phase1.md, results.phase1.json and records. They are not pooled with the eight new pairs.', '',
        '## Scope and remaining limits', '',
        'The engine receives real unit orders and supplies the controlled seat’s fog-filtered observations. Public static rules/maps are allowed; the spatial tensor and enriched enemy fields are excluded. Stock AI may use privileged engine information. The adapter approximates the current platform schema, reconstructs events and does not provide faithful per-order acknowledgments. See ADAPTER_CALIBRATION.md.', '',
        'Source manifests/deltas, original declarations, phase-specific selection freezes, map hashes, raw-report bodies and trace hashes are retained. Four early first-stage reports lack in-run fingerprints and are documented. Later runtime fingerprints verify unchanged policy files. D’s development manifest explicitly records its delayed creation after a digest-format mismatch; it was not backdated.', '',
        'Formation timing and attacks into overlapping turrets remain tactical limitations seen in first-stage condition 1. The search revisions do not claim to repair that engagement behavior. Known development regressions remain visible in the table above.', '',
        'DIAGNOSTICS_STAGE2.md and stage2-diagnostics.json retain each condition’s terminal time, destroyed/lost cost, remaining assets and own-harvester observations. These diagnostics are not converted into wins for censored games.', '',
        'Eight paired conditions provide only a small fixed sample. They cannot establish platform win rate, general dominance, SOTA status or guaranteed wins. Censored games are not converted into score-based wins, and losses and rejected versions remain in the record.', '',
    ]
    (ROOT / 'SUMMARY.md').write_text('\n'.join(lines))
    print(json.dumps({'candidate': candidate, 'independent_pairs': 8, 'records': len(records), 'baseline_wlc': counts([records[(baseline, c['id'])] for c in selected]), 'candidate_wlc': counts([records[(candidate, c['id'])] for c in selected])}))


if __name__ == '__main__':
    main()

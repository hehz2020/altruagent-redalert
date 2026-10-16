from collections import Counter
from pathlib import Path
import argparse
import json


ROOT = Path(__file__).resolve().parent


def outcome(report):
    if not report['engine_done']:
        return 'C'
    return {'win': 'W', 'lose': 'L'}[report['result']]


def counts(records):
    result = Counter(outcome(record['report']) for record in records)
    return '/'.join(str(result[key]) for key in 'WLC')


def cell(record):
    if record is None:
        return 'not run'
    report = record['report']
    return f"{outcome(report)} {report['seconds']:.2f}s"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', default='candidate_b')
    args = parser.parse_args()
    conditions = json.loads((ROOT / 'conditions.json').read_text())['conditions']
    records = {}
    for path in sorted((ROOT / 'records').glob('*/*.json')):
        records[(path.parent.name, path.stem)] = json.loads(path.read_text())
    development = [c for c in conditions if c['phase'] == 'development']
    reserved = [c for c in conditions if c['phase'] == 'held_out']
    baseline = 'released_v24'
    candidate = args.candidate
    lines = [
        '# v2.5 engine evaluation: first stage', '',
        'W/L/C means terminal wins, terminal losses, and censored runs still undecided at the 1,200-second limit. C is not a draw. Every result comes from the controlled seat in a locally instrumented OpenRA engine; none is an official platform result.', '',
        f'The first-stage candidate was {candidate}. It was selected from development results before any first-stage held-out result existed; selection-freeze.json records the decision and known development regression. B stayed unchanged throughout that evaluation. Its results did not establish stronger performance, and B was rejected for release. Stage 2 investigates candidate D; the inspected first-stage held-out condition 7 is now explicitly a stage-2 development case. Only the new declared stage-2 conditions may independently evaluate D. Development and ablation outcomes must not be pooled with held-out outcomes.', '',
        '## Held-out paired results', '',
        '| Policy | Completed / planned | W/L/C |',
        '|---|---:|---:|',
    ]
    for policy in [baseline, candidate]:
        subset = [records[(policy, c['id'])] for c in reserved if (policy, c['id']) in records]
        lines.append(f'| {policy} | {len(subset)} / {len(reserved)} | {counts(subset)} |')
    lines += ['', '| Condition | Map | Own / enemy faction | Seat | AI / seed | v2.4 | Evaluated B |', '|---|---|---|---|---|---|---|']
    transitions = {}
    for condition in reserved:
        left = records.get((baseline, condition['id']))
        right = records.get((candidate, condition['id']))
        short = condition['id'].removeprefix('v25_held_out_')
        lines.append(f"| {short} | {condition['map']} | {condition['own_faction']} / {condition['enemy_faction']} | {condition['own_side']} | {condition['opponent']} / {condition['seed']} | {cell(left)} | {cell(right)} |")
        if left and right:
            key = outcome(left['report']) + ' → ' + outcome(right['report'])
            transitions.setdefault(key, []).append(short)
    lines += ['', 'Paired transitions list the baseline outcome followed by the candidate outcome. W → L and L → W are direct terminal regressions and improvements; transitions involving C leave at least one outcome unresolved.', '', '| Transition | Conditions |', '|---|---|']
    for key, identifiers in sorted(transitions.items()):
        lines.append(f"| {key} | {', '.join(identifiers)} |")
    lines += ['', '## Held-out subgroups', '', '| Dimension | Group | v2.4 W/L/C | Evaluated B W/L/C |', '|---|---|---:|---:|']
    for dimension in ['map', 'own_faction', 'opponent', 'own_side']:
        for value in sorted({condition[dimension] for condition in reserved}):
            selected = [condition for condition in reserved if condition[dimension] == value]
            groups = [[records[(policy, c['id'])] for c in selected if (policy, c['id']) in records] for policy in [baseline, candidate]]
            lines.append(f'| {dimension} | {value} | {counts(groups[0])} | {counts(groups[1])} |')
    lines += ['', '## Development and ablations', '', 'These conditions were inspected during iteration and used for selection. The incomplete ablation sets are intentional. They provide diagnostics, not an independent estimate of performance.', '', '| Policy | Development 1 | Development 2 | Development 3 | Development 4 | W/L/C |', '|---|---|---|---|---|---:|']
    labels = [baseline, 'candidate_a', 'candidate_b', 'candidate_c']
    labels += sorted({key[0] for key in records if key[0].startswith('ablation_')})
    for policy in labels:
        subset = [records[(policy, c['id'])] for c in development if (policy, c['id']) in records]
        cells = [cell(records.get((policy, c['id']))) for c in development]
        lines.append('| ' + ' | '.join([policy] + cells + [counts(subset)]) + ' |')
    lines += [
        '', 'Candidate A regressed badly and was rejected. A blocked scout destination optimization had changed tie ordering; B restored the previous sweep behavior. Candidate C reserved ordinary scouts before defense and was rejected after worse development results and a lone-guard scouting regression.', '',
        'Development 4 exposes an unresolved interaction: B lost where v2.4 won. Replacing only the old goal selection or only the old defense/scout order still lost; replacing both restored the v2.4 win. This does not establish that the first observed command divergence alone caused the loss. The known regression was recorded before held-out evaluation.', '',
        '## Reproducibility and limits', '',
        'All completed reports are retained in records, including rejected candidates and losses. The exact source deltas, file manifests, engine patch, map package hashes, declarations and final selection freeze are included. Four early reports lack the later source-hash fields; README.md identifies them and explains the retrospective evidence. The remaining reports include a source fingerprint and an unchanged-during-run check.', '',
        'The controlled policy receives only its fog-filtered seat observation plus public static map/rule data. Stock AI may use privileged engine information. The local adapter approximates the current platform schema and lacks exact per-command acknowledgments. Terminal detection and deterministic local randomness were instrumented; no game balance changes were made. See ADAPTER_CALIBRATION.md for specific differences.', '',
        'Remaining tactical limitation: a read-only inspection of held-out condition 1 found both versions sending infantry directly at a visible gun turret while their tanks were still approaching with attack-move orders. Another gun turret then became visible, creating overlapping fire. This suggests formation timing and turret engagement remain weak; it is an observation, not proof of the sole cause of defeat. No fix was made from this held-out inspection.', '',
        'Twelve paired conditions are a small fixed sample across three maps and two stock AI configurations. Counts describe this suite only and do not demonstrate platform win rate, general dominance, SOTA status, or guaranteed wins. No score-based winner was fabricated for censored runs.', '',
    ]
    (ROOT / 'SUMMARY.md').write_text('\n'.join(lines))
    print(json.dumps({'records': len(records), 'held_out_pairs_complete': sum((baseline, c['id']) in records and (candidate, c['id']) in records for c in reserved), 'candidate': candidate}))


if __name__ == '__main__':
    main()

from pathlib import Path
import argparse
import hashlib
import json


ROOT = Path(__file__).resolve().parent


def derive(folder):
    result = json.loads((folder / 'result.json').read_text())
    previous = {}
    absent = set()
    first_drop = None
    first_absent = None
    first_four = None
    maximum = 0
    unit_samples = 0
    idle_samples = 0
    last = {}
    trace_hash = hashlib.sha256()
    with (folder / 'trace.jsonl').open('rb') as stream:
        for line in stream:
            trace_hash.update(line)
            raw = json.loads(line)['raw']
            seconds = raw['time']['game_seconds']
            observation = raw['observation']
            harvesters = {u['id']: u for u in observation['units'] if u['type'] == 'harv'}
            maximum = max(maximum, len(harvesters))
            if len(harvesters) >= 4 and first_four is None:
                first_four = seconds
            if first_drop is None and any(key in previous and unit['hp'] < previous[key]['hp'] for key, unit in harvesters.items()):
                first_drop = seconds
            missing = set(previous) - set(harvesters)
            if missing and first_absent is None:
                first_absent = seconds
            absent.update(missing)
            unit_samples += len(harvesters)
            idle_samples += sum(bool(unit.get('idle')) for unit in harvesters.values())
            previous = harvesters
            last = {'seconds': seconds, 'harvesters': len(harvesters), 'cash': observation['economy']['cash'], 'ore': observation['economy']['ore']}
    return {
        'condition': folder.name,
        'policy': folder.parent.name,
        'outcome': result['result'] if result['engine_done'] else 'censored',
        'seconds': result['seconds'],
        'kills_cost': result['military']['kills_cost'],
        'deaths_cost': result['military']['deaths_cost'],
        'assets_value': result['military']['assets_value'],
        'army_value': result['military']['army_value'],
        'final_economy': result['economy'],
        'maximum_observed_harvesters': maximum,
        'first_four_harvesters_seconds': first_four,
        'first_observed_harvester_hp_drop_seconds': first_drop,
        'first_observed_harvester_disappearance_seconds': first_absent,
        'unique_harvester_ids_observed_disappearing': len(absent),
        'idle_harvester_unit_observation_fraction': idle_samples / unit_samples if unit_samples else None,
        'harvester_unit_observations': unit_samples,
        'last_decision_observation': last,
        'explicit_harvest_orders': result['orders'].get('harvest', 0),
        'trace_sha256': trace_hash.hexdigest(),
    }


def time_cell(value):
    return 'none observed' if value is None else f'{value:.2f}s'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, default=ROOT / 'results')
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--verify-retained-traces', action='store_true')
    args = parser.parse_args()
    conditions = [c for c in json.loads((ROOT / 'conditions.json').read_text())['conditions'] if c['phase'] == 'stage2_held_out']
    rows = [derive(args.results / label / condition['id']) for condition in conditions for label in ['released_v24', args.candidate]]
    if args.verify_retained_traces:
        for row in rows:
            record = json.loads((ROOT / 'records' / row['policy'] / (row['condition'] + '.json')).read_text())
            assert row['trace_sha256'] == record['trace_sha256']
    output = {
        'scope': 'Own-seat observation and report diagnostics only. These do not change terminal outcomes.',
        'verified_against_retained_trace_hashes': args.verify_retained_traces,
        'definitions': {
            'first_four_harvesters_seconds': 'First decision observation containing at least four owned harv units.',
            'hp_drop': 'First observed integer-percent HP decrease for an owned harvester between decision observations; not a guarantee that this was the first actual hit.',
            'disappearance': 'An owned harv ID present in the previous decision observation is absent. This is not independently certified death and can include ownership or representation changes. The final terminal cleanup is not appended to the decision trace.',
            'idle_fraction': 'Fraction of observed harvester unit samples with idle=true; not mining yield, ore income, or a time-to-victory score.',
            'final_economy': 'Direct final report. A terminal defeat can remove remaining actors; last_decision_observation is separately retained.',
        },
        'rows': rows,
    }
    (ROOT / 'stage2-diagnostics.json').write_text(json.dumps(output, indent=2) + '\n')
    lines = ['# Stage 2 own-seat diagnostics', '', output['scope'], '',
        'All monetary values below are engine-reported unit/building cost totals or remaining assets. Censored outcomes stay censored. Mining fields are descriptive observations, not inferred income or a replacement winner calculation.', '',
        '| Case | Policy | Outcome / seconds | Destroyed / lost cost | Assets | Max / last observed harvesters | First four | First HP drop | First disappearance | Idle samples |',
        '|---|---|---|---:|---:|---:|---|---|---|---:|']
    for row in rows:
        idle = row['idle_harvester_unit_observation_fraction']
        idle_text = 'none observed' if idle is None else f'{idle:.2%}'
        lines.append(f"| {row['condition'].removeprefix('v25_stage2_held_out_')} | {row['policy']} | {row['outcome']} / {row['seconds']:.2f} | {row['kills_cost']} / {row['deaths_cost']} | {row['assets_value']} | {row['maximum_observed_harvesters']} / {row['last_decision_observation']['harvesters']} | {time_cell(row['first_four_harvesters_seconds'])} | {time_cell(row['first_observed_harvester_hp_drop_seconds'])} | {time_cell(row['first_observed_harvester_disappearance_seconds'])} | {idle_text} |")
    lines += ['', 'A disappearance is not independently certified death; unit ownership or representation can change. HP percentages are rounded and observed at decision intervals. The final terminal cleanup is not inserted into the trace, while the final report can show zero actors after defeat. Idle=true measures the exposed flag, not productive mining time. Full definitions, cash/ore snapshots, order counts and trace hashes are in stage2-diagnostics.json.', '']
    (ROOT / 'DIAGNOSTICS_STAGE2.md').write_text('\n'.join(lines))
    print(json.dumps({'cases': len(rows), 'candidate': args.candidate}))


if __name__ == '__main__':
    main()

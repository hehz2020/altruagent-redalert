from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--mode', choices=['development', 'held_out'], required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    conditions = json.loads((ROOT / 'conditions.json').read_text())['conditions']
    if args.mode == 'development':
        selected = [c for c in conditions if c['phase'] in {'development', 'stage2_development'}]
        jobs = [(args.candidate, args.candidate, c) for c in selected]
    else:
        selected = [c for c in conditions if c['phase'] == 'stage2_held_out']
        jobs = [(label, policy, c) for c in selected for label, policy in [('released_v24', 'v24'), (args.candidate, args.candidate)]]

    def run(job):
        label, policy, condition = job
        output = ROOT / 'results' / label / condition['id']
        if (output / 'result.json').exists():
            raise ValueError('Existing result: ' + str(output))
        output.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with (output / 'runner.log').open('w') as log:
            process = subprocess.run([sys.executable, str(ROOT / 'case_runner.py'), '--policy', str(ROOT / 'policies' / policy), '--condition', condition['id'], '--label', label], stdout=log, stderr=log, timeout=900)
        row = {'label': label, 'condition': condition['id'], 'returncode': process.returncode, 'elapsed_s': round(time.monotonic() - started, 2)}
        if (output / 'result.json').exists():
            result = json.loads((output / 'result.json').read_text())
            row.update({key: result[key] for key in ['result', 'engine_done', 'seconds', 'military', 'policy_source_sha256', 'source_unchanged_during_run']})
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = [future.result() for future in as_completed([pool.submit(run, job) for job in jobs])]
    (ROOT / 'results' / ('stage2-' + args.mode + '-' + args.candidate + '.json')).write_text(json.dumps(rows, indent=2) + '\n')
    if any(row['returncode'] for row in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

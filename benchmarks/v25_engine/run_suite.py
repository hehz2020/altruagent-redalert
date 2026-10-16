from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--policy', required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--phase', choices=['development','held_out'], required=True)
    p.add_argument('--workers', type=int, default=2)
    args=p.parse_args()
    conditions=[c for c in json.loads((ROOT/'conditions.json').read_text())['conditions'] if c['phase']==args.phase]
    def run(c):
        output=ROOT/'results'/args.label/c['id']
        output.mkdir(parents=True,exist_ok=True)
        started=time.monotonic()
        with (output/'runner.log').open('w') as log:
            result=subprocess.run([sys.executable,str(ROOT/'case_runner.py'),'--policy',args.policy,'--condition',c['id'],'--label',args.label],stdout=log,stderr=log,timeout=900)
        info={'condition':c['id'],'returncode':result.returncode,'elapsed_s':round(time.monotonic()-started,2)}
        if (output/'result.json').exists():
            r=json.loads((output/'result.json').read_text())
            info.update(result=r['result'],engine_done=r['engine_done'],seconds=r['seconds'],military=r['military'])
        print(json.dumps(info),flush=True)
        return info
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows=[f.result() for f in as_completed([pool.submit(run,c) for c in conditions])]
    out=ROOT/'results'/args.label/(args.phase+'-summary.json')
    out.write_text(json.dumps(rows,indent=2)+'\n')
    if any(r['returncode'] for r in rows):raise SystemExit(1)

if __name__=='__main__':main()

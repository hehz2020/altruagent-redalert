from pathlib import Path
import argparse
import json
import os
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', required=True)
    parser.add_argument('--condition', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--seconds', type=int)
    args = parser.parse_args()
    condition = next(c for c in json.loads((ROOT / 'conditions.json').read_text())['conditions'] if c['id'] == args.condition)
    out = ROOT / 'results' / args.label / condition['id']
    out.mkdir(parents=True, exist_ok=True)
    support = out / 'support'
    support.mkdir(exist_ok=True)
    if not (support / 'Content').exists():
        (support / 'Content').symlink_to(ROOT / 'support/Content', target_is_directory=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, ALTRU_BENCH_SEEDED_LOCAL='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')
    with (out / 'engine.log').open('w') as log:
        process = subprocess.Popen([str(ROOT / 'dotnet/dotnet'), str(ROOT / 'OpenRA/bin/OpenRA.dll'), 'Engine.EngineDir=' + str(ROOT / 'OpenRA'), 'Engine.SupportDir=' + str(support), 'Game.Mod=ra', 'Game.Platform=Null', 'Launch.MultiSession=' + str(port)], cwd=ROOT / 'OpenRA', env=env, stdout=log, stderr=log)
        session = None
        try:
            import adapter
            bridge = adapter.Bridge('localhost:' + str(port))
            pb = adapter.pb
            create = bridge.channel.unary_unary('/openra.rl.RLBridge/CreateSession', request_serializer=pb.CreateSessionRequest.SerializeToString, response_deserializer=pb.CreateSessionResponse.FromString)
            destroy = bridge.channel.unary_unary('/openra.rl.RLBridge/DestroySession', request_serializer=pb.DestroySessionRequest.SerializeToString, response_deserializer=pb.DestroySessionResponse.FromString)
            enemy = 'Multi1' if condition['own_side'] == 'Multi0' else 'Multi0'
            bots = condition['own_side'] + ':rl-agent,' + enemy + ':' + condition['opponent']
            session = create(pb.CreateSessionRequest(map_name=condition['frozen_map'], bots=bots, seed=condition['seed']), timeout=20).session_id
            first = bridge.advance(pb.FastAdvanceRequest(session_id=session, ticks=1), timeout=90)
            state = bridge.state(pb.StateRequest(session_id=session), timeout=20)
            assert state.player_faction == condition['own_faction'], (state,condition)
            assert state.enemy_faction == condition['enemy_faction'], (state,condition)
            assert first.economy.cash == 5000 and len(first.units) == 1 and first.units[0].type == 'mcv', str(first.economy)
            assert first.units[0].owner == condition['own_side'], first.units[0]
            meta = dict(condition, verified_own_faction=state.player_faction, verified_enemy_faction=state.enemy_faction, verified_own_seat=first.units[0].owner, policy=str(Path(args.policy).resolve()), label=args.label)
            (out / 'metadata.json').write_text(json.dumps(meta, indent=2) + '\n')
            sys.argv = ['adapter.py', '--repo', args.policy, '--host', 'localhost:' + str(port), '--engine', str(ROOT / 'OpenRA'), '--map', condition['frozen_map'], '--session-id', session, '--faction', condition['own_faction'], '--enemy-faction', condition['enemy_faction'], '--seconds', str(args.seconds or condition['seconds_limit']), '--ticks', str(condition['tick_step']), '--output', str(out / 'result.json'), '--trace', str(out / 'trace.jsonl')]
            adapter.main()
        except Exception as exc:
            (out / 'error.json').write_text(json.dumps({'type':type(exc).__name__, 'error':str(exc)}, indent=2)+'\n')
            raise
        finally:
            if session:
                try: destroy(pb.DestroySessionRequest(session_id=session), timeout=5)
                except Exception: pass
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()

if __name__ == '__main__':
    main()

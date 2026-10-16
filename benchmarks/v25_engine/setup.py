from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
ENGINE_COMMIT = '9b271c1a5562a07deeb1c3f81d9a556cd563a676'
BASELINE_COMMIT = 'e264fce0d48da86110c896cf39a720fdc52b02ba'
SDK_URL = 'https://builds.dotnet.microsoft.com/dotnet/Sdk/8.0.426/dotnet-sdk-8.0.426-linux-x64.tar.gz'
SDK_SHA512 = '8141d01bdc53f604aed3bb661b604707a64209f8a947cd81bf95b4f518951593d77864069191f54ea5e84362a409da6b0f69074bf893b283d7e0cf93e2bf20a8'


def download(url, path, digest=None, algorithm='sha256'):
    if not path.exists():
        urllib.request.urlretrieve(url, path)
    if digest and hashlib.new(algorithm, path.read_bytes()).hexdigest() != digest:
        raise ValueError('Archive digest mismatch: ' + str(path))


def unpack(path, output, strip_root=False):
    output.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        if strip_root:
            for member in members:
                member.name = member.name.partition('/')[2]
            members = [member for member in members if member.name]
        archive.extractall(output, members=members, filter='data')


def prepare_maps(engine):
    conditions = json.loads((ROOT / 'conditions.json').read_text())['conditions']
    manifest = json.loads((ROOT / 'map-manifest.json').read_text())
    for row in conditions:
        sources = {p.stem.lower(): p for p in (engine / 'mods/ra/maps').glob('*.oramap')}
        with zipfile.ZipFile(sources[row['map'].lower()]) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        text = entries['map.yaml'].decode()
        text = re.sub(r'^Title:.*$', 'Title: ' + row.get('map_title_condition_id', row['id']), text, flags=re.M)
        own = row['own_side']
        enemy = 'Multi1' if own == 'Multi0' else 'Multi0'
        players = [(own, row['own_faction'], 1 if own == 'Multi0' else 2),
                   (enemy, row['enemy_faction'], 2 if own == 'Multi0' else 1)]
        for slot, faction, spawn in players:
            pattern = rf'(\tPlayerReference@{slot}:\n)(.*?)(?=\n\tPlayerReference|\n\S|\Z)'
            match = re.search(pattern, text, re.S)
            if not match:
                raise ValueError('Missing player: ' + slot)
            body = re.sub(r'\t\tFaction:.*', '\t\tFaction: ' + faction, match.group(2))
            body += f'\n\t\tLockFaction: True\n\t\tLockSpawn: True\n\t\tSpawn: {spawn}'
            text = text[:match.start(2)] + body + text[match.end(2):]
        if '\nRules:' in text:
            raise ValueError('Unexpected map rules')
        text += '\nRules:\n\tPlayer:\n\t\tPlayerResources:\n\t\t\tDefaultCash: 5000\n\t\tShroud:\n\t\t\tFogCheckboxEnabled: True\n\t\t\tExploredMapCheckboxEnabled: False\n\tWorld:\n\t\tSpawnStartingUnits:\n\t\t\tStartingUnitsClass: none\n\t\tMapOptions:\n\t\t\tShortGameCheckboxEnabled: True\n'
        entries['map.yaml'] = text.encode()
        expected = manifest[row['frozen_map']]
        destination = engine / 'mods/ra/maps' / row['frozen_map']
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries.items():
                member = expected['members'][name]
                if hashlib.sha256(data).hexdigest() != member['sha256']:
                    raise ValueError('Map member differs: ' + name)
                info = zipfile.ZipInfo(name, tuple(member['date_time']))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected['package_sha256']:
            raise ValueError('Map archive differs: ' + row['frozen_map'])


def prepare_policies(baseline_source=None):
    base = ROOT / 'policies/v24'
    if not base.exists():
        if baseline_source:
            shutil.copytree(Path(baseline_source) / 'altru_redalert', base / 'altru_redalert')
        else:
            source = ROOT / 'baseline-source.tar.gz'
            download('https://codeload.github.com/hehz2020/altruagent-redalert/tar.gz/' + BASELINE_COMMIT, source)
            unpack(source, base, True)
    for manifest_path in sorted((ROOT / 'policy-manifests').glob('*.json')):
        label = manifest_path.stem
        manifest = json.loads(manifest_path.read_text())
        target = ROOT / 'policies' / label
        if label != 'v24' and not target.exists():
            shutil.copytree(base / 'altru_redalert', target / 'altru_redalert')
            with (ROOT / 'policy-deltas' / (label + '.patch')).open('rb') as patch:
                subprocess.run(['patch', '-p1'], cwd=target, stdin=patch, check=True)
        for name, digest in manifest['files'].items():
            if hashlib.sha256((target / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Policy differs: ' + label + '/' + name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--policies-only', action='store_true')
    parser.add_argument('--baseline-source')
    args = parser.parse_args()
    if args.policies_only:
        prepare_policies(args.baseline_source)
        return
    sdk = ROOT / 'dotnet-sdk.tar.gz'
    download(SDK_URL, sdk, SDK_SHA512, 'sha512')
    if not (ROOT / 'dotnet/dotnet').exists():
        unpack(sdk, ROOT / 'dotnet')
    engine_archive = ROOT / 'openra.tar.gz'
    download('https://codeload.github.com/yxc20089/OpenRA/tar.gz/' + ENGINE_COMMIT, engine_archive, '4ab56f6035dfe902d2e20816413b0b5e7a5397613b8daa53019b39cbfe2dcab9')
    engine = ROOT / 'OpenRA'
    if not engine.exists():
        unpack(engine_archive, engine, True)
        with (ROOT / 'instrumentation.patch').open('rb') as patch:
            subprocess.run(['patch', '-p1'], cwd=engine, stdin=patch, check=True)
    content = ROOT / 'ra-content.zip'
    download('https://openra.baxxster.no/openra/ra-quickinstall.zip', content, '44241f68e69db9511db82cf83c174737ccda300b', 'sha1')
    with zipfile.ZipFile(content) as archive:
        archive.extractall(ROOT / 'support/Content/ra/v2')
    prepare_maps(engine)
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1')
    for project in ['OpenRA.Launcher', 'OpenRA.Mods.Cnc', 'OpenRA.Platforms.Null']:
        subprocess.run([str(ROOT / 'dotnet/dotnet'), 'build', str(engine / project / (project + '.csproj')),
                        '-c', 'Release', '--disable-build-servers', '-m:1', '--verbosity', 'minimal'], env=env, check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    generated = ROOT / 'generated'
    generated.mkdir(exist_ok=True)
    proto = engine / 'OpenRA.Mods.Common/Traits/Player/Protos'
    subprocess.run([sys.executable, '-m', 'grpc_tools.protoc', '-I' + str(proto), '--python_out=' + str(generated),
                    '--grpc_python_out=' + str(generated), str(proto / 'rl_bridge.proto')], check=True)
    prepare_policies(args.baseline_source)


if __name__ == '__main__':
    main()

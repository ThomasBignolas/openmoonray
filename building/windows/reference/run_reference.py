#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate RATS references with a checksum-pinned published Linux renderer.

The Windows renderer is never used to create these canonicals. The initial
focus covers the five image cases previously compared under software emulation.
Set plan.json scope to "all" for every enabled CPU/default case in 16 shards.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
FOCUS = ('moonray/geometry/sphere', 'moonray/map/checkerboard', 'hd_render/geometry/skel')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def select_tests(manifest, scope, shard, shards):
    if scope not in ('focus', 'all') or not 0 <= shard < shards <= 16:
        raise ValueError('Invalid scope or shard selection')
    tests = []
    for test in manifest['tests']:
        props = {p['name']: p['value'] for p in test.get('properties', [])}
        if props.get('DISABLED', False):
            continue
        if not test['name'].startswith(('update-sca-', 'update-vec-', 'update-def-')):
            raise ValueError('Unexpected execution mode in update manifest: ' + test['name'])
        if scope == 'focus' and test['name'].split('-', 2)[2] not in FOCUS:
            continue
        tests.append(test)
    tests.sort(key=lambda t: t['name'])
    expected = 5 if scope == 'focus' else 645
    if len(tests) != expected:
        raise ValueError(f'Pinned suite changed: expected {expected}, found {len(tests)}')
    # All modes of a scene share diff.json; keep them on the same worker.
    groups = {}
    for test in tests:
        groups.setdefault(test['name'].split('-', 2)[2], []).append(test)
    return [test for scene in sorted(groups)[shard::shards] for test in groups[scene]]


def runtime_environment(snap):
    prefix = snap / 'opt/MoonRay/installs'
    env = dict(os.environ)
    env.update({
        'SNAP': str(snap),
        'PATH': os.pathsep.join(str(p) for p in (prefix/'openmoonray/bin', prefix/'bin', snap/'usr/bin', snap/'bin')) + ':/usr/bin:/bin',
        'LD_LIBRARY_PATH': ':'.join(str(p) for p in (
            prefix/'openmoonray/lib', prefix/'lib', snap/'usr/lib', snap/'usr/lib/x86_64-linux-gnu',
            snap/'usr/lib/x86_64-linux-gnu/lapack', snap/'usr/lib/x86_64-linux-gnu/blas', prefix/'openmoonray/rdl2dso')),
        'PYTHONPATH': ':'.join(str(p) for p in (prefix/'lib/python', prefix/'lib/python3.12/site-packages')),
        'PXR_PLUGINPATH_NAME': ':'.join(str(p) for p in (prefix/'lib/usd', prefix/'openmoonray/plugin/pxr/hd_moonray', prefix/'openmoonray/plugin/pxr', prefix/'plugin/usd')),
        'ARRAS_SESSION_PATH': str(prefix/'openmoonray/sessions'),
        'RDL2_DSO_PATH': str(prefix/'openmoonray/rdl2dso'),
        'RATS_HD_RENDERER': 'Moonray (debug)',
        'RATS_RUN_CONCURRENT': '0',
    })
    # An inherited development environment must not inject a different renderer.
    for key in ('LD_PRELOAD', 'PYTHONHOME', 'OIIO_PYTHON'):
        env.pop(key, None)
    return env


def verify_canonicals(tests, evidence):
    """Require every selected command's image and mode-specific thresholds."""
    names = [case.get('name') for case in ET.parse(evidence/'update-results.xml').getroot().iter('testcase')]
    if sorted(names) != sorted(t['name'] for t in tests):
        raise RuntimeError('JUnit does not cover exactly the selected update cases')
    for case in ET.parse(evidence/'update-results.xml').getroot().iter('testcase'):
        if any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')):
            raise RuntimeError('JUnit contains an unsuccessful update case: '+case.get('name', ''))
    canonical_root = evidence/'canonicals'
    for test in tests:
        command = test['command']
        relative = command[command.index('--test-rel-path')+1]
        mode = command[command.index('--exec-mode')+1]
        diff = canonical_root/command[command.index('--diff-json')+1]
        if not diff.resolve().is_relative_to(canonical_root.resolve()):
            raise RuntimeError('Canonical path escapes its output directory')
        thresholds = read(diff)
        images = [command[i+1] for i, value in enumerate(command) if value == '--canonicals']
        if not images:
            raise RuntimeError('Update case has no canonical images: '+test['name'])
        for name in images:
            image = canonical_root/relative/mode/name
            if not image.resolve().is_relative_to(canonical_root.resolve()) or not image.is_file() or image.stat().st_size == 0:
                raise RuntimeError('Missing canonical image: '+str(image))
            if not isinstance(thresholds.get(name, {}).get(mode), dict) or not thresholds[name][mode]:
                raise RuntimeError(f'Missing thresholds for {test["name"]}/{name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--emit-plan', action='store_true')
    parser.add_argument('--work', type=Path)
    parser.add_argument('--scope', choices=('focus', 'all'), default='focus')
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--shards', type=int, default=1)
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--snap-file', type=Path, help='Optional local copy of the pinned Snap')
    parser.add_argument('--runtime-root', type=Path, help='Existing read-only extraction, verified against the pinned binary hashes')
    args = parser.parse_args()
    plan = read(HERE/'plan.json')
    if (plan['canonical_candidates'] != 25 or plan['scope'] not in ('focus', 'all')
            or not isinstance(plan['threads_per_render'], int) or not 1 <= plan['threads_per_render'] <= 128):
        parser.error('The plan must retain 25 canonical candidates and a known scope')
    if args.emit_plan:
        shards = 1 if plan['scope'] == 'focus' else plan['full_suite_shards']
        if not isinstance(shards, int) or not 1 <= shards <= 16:
            parser.error('Expected between 1 and 16 shards')
        output = f'matrix={json.dumps({"shard": list(range(shards))})}\nscope={plan["scope"]}\nshards={shards}\n'
        if os.getenv('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write(output)
        print(output, end='')
        return
    if sys.platform != 'linux' or platform.machine() != 'x86_64' or not args.work:
        parser.error('Use x86_64 Linux and a new --work directory')
    if not 0 <= args.shard < args.shards <= 16:
        parser.error('Invalid shard selection')
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    evidence = work/'evidence'
    evidence.mkdir()
    lock = read(HERE/'reference-lock.json')
    state = {'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'preparing',
             'scope': args.scope, 'shard': args.shard, 'shards': args.shards,
             'canonical_candidates': 25, 'python': sys.version, 'platform': platform.platform(),
             'lock': lock, 'commands': [], 'native_hardware_claimed': False}
    state_path = evidence/'run.json'

    def save():
        state_path.write_text(json.dumps(state, indent=2)+'\n', encoding='utf-8')

    def run(command, label, cwd=None, env=None, check=True):
        command = [str(p) for p in command]
        print(label, flush=True)
        with (evidence/(label+'.log')).open('w') as log:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        state['commands'].append({'command': command, 'log': label+'.log', 'exit_code': result.returncode})
        save()
        if check and result.returncode:
            raise RuntimeError(f'{label} failed ({result.returncode}); inspect the retained log')
        return result.returncode

    def checkout(name, target):
        spec = lock[name]
        env = {**os.environ, 'GIT_LFS_SKIP_SMUDGE': '1'}
        run(['git', 'init', target], name+'-init', env=env)
        run(['git', '-C', target, 'remote', 'add', 'origin', spec['url']], name+'-remote', env=env)
        run(['git', '-C', target, 'fetch', '--depth=1', 'origin', spec['commit']], name+'-fetch', env=env)
        run(['git', '-C', target, 'checkout', '--detach', 'FETCH_HEAD'], name+'-checkout', env=env)
        head = subprocess.check_output(['git', '-C', target, 'rev-parse', 'HEAD'], text=True).strip()
        if head != spec['commit']:
            raise RuntimeError('Unexpected source revision for '+name)

    save()
    try:
        for filename in ('/proc/cpuinfo', '/etc/os-release'):
            shutil.copyfile(filename, evidence/Path(filename).name)
        run(['lscpu', '--json'], 'cpu')
        run(['systemd-detect-virt'], 'virtualization', check=False)
        if 'avx2' not in Path('/proc/cpuinfo').read_text():
            raise RuntimeError('The published renderer requires AVX2')
        for tool in ('git', 'cmake', 'ctest'):
            run([tool, '--version'], tool+'-version')
        runtime = args.runtime_root.resolve() if args.runtime_root else work/'snap'
        if not args.runtime_root:
            snap_file = args.snap_file.resolve() if args.snap_file else work/'openmoonray.snap'
            if not args.snap_file:
                with urllib.request.urlopen(lock['snap']['url'], timeout=120) as incoming, snap_file.open('xb') as target:
                    shutil.copyfileobj(incoming, target)
            if snap_file.stat().st_size != lock['snap']['size'] or sha(snap_file, 'sha3_384') != lock['snap']['sha3_384']:
                raise RuntimeError('Published Snap checksum mismatch')
            run(['unsquashfs', '-no-progress', '-d', runtime, snap_file], 'extract-snap')
            state['snap_verified'] = True
        state['binary_hashes'] = {}
        for item in lock['runtime_files']:
            found = sha(runtime/item['path'])
            if found != item['sha256']:
                raise RuntimeError('Published runtime file mismatch: '+item['path'])
            state['binary_hashes'][item['path']] = found
        env = runtime_environment(runtime)
        env['RATS_MOONRAY_THREADS'] = str(plan['threads_per_render'])
        env['RATS_CANONICAL_DIR'] = str(evidence/'canonicals')
        (evidence/'canonicals').mkdir()
        run(['moonray', '-help'], 'renderer-help', env=env)
        run(['/usr/bin/python3', '-c', 'import OpenImageIO; print(OpenImageIO.VERSION_STRING)'], 'oiio-import', env=env)
        source = work/'source'
        source.mkdir()
        checkout('rats', source/'rats')
        checkout('cmake_modules', source/'cmake_modules')
        run(['git', '-C', source/'rats', 'lfs', 'install', '--local'], 'lfs-install')
        run(['git', '-C', source/'rats', 'lfs', 'pull'], 'lfs-pull')
        for asset in (source/'rats/assets').rglob('*'):
            if asset.is_file():
                with asset.open('rb') as stream:
                    if stream.read(43).startswith(b'version https://git-lfs.github.com/spec/v1'):
                        raise RuntimeError('Unmaterialized LFS asset: '+str(asset))
        patch = HERE/'rats-harness.patch'
        if sha(patch) != lock['harness_patch_sha256']:
            raise RuntimeError('RATS harness patch checksum mismatch')
        run(['git', '-C', source/'rats', 'apply', '--check', patch], 'harness-check')
        run(['git', '-C', source/'rats', 'apply', patch], 'harness-apply')
        (source/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.23.1)\nproject(MoonRayReferenceTests LANGUAGES C CXX)\ninclude(CTest)\nlist(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake_modules/cmake")\nadd_subdirectory(rats)\n')
        build = work/'build'
        run(['cmake', '-S', source, '-B', build, '-DBUILD_TESTING=ON', '-DPython_EXECUTABLE=/usr/bin/python3'], 'configure', env=env)
        manifest = json.loads(subprocess.check_output(['ctest', '--test-dir', build, '--show-only=json-v1', '-L', '^rats$', '-L', '^update$', '-L', '^(scalar|vector|default)$'], env=env))
        (evidence/'update-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        tests = select_tests(manifest, args.scope, args.shard, args.shards)
        if not tests:
            raise RuntimeError('Empty reference shard')
        state['selected_tests'] = [test['name'] for test in tests]
        state['disabled_tests'] = [t['name'] for t in manifest['tests'] if any(p['name']=='DISABLED' and p['value'] for p in t.get('properties', []))]
        source_files = []
        for directory in (source/'rats', source/'cmake_modules/cmake'):
            for path in sorted(directory.rglob('*')):
                if path.is_file() and '.git' not in path.relative_to(source).parts:
                    source_files.append({'path': path.relative_to(source).as_posix(), 'sha256': sha(path)})
        (evidence/'source-manifest.json').write_text(json.dumps(source_files, indent=2)+'\n')
        state['status'] = 'configured'
        save()
        if args.configure_only:
            return
        expression = '^('+'|'.join(re.escape(t['name']) for t in tests)+')$'
        result = run(['ctest', '--test-dir', build, '--output-on-failure', '--no-tests=error', '-j', '1',
                      '--timeout', '7200', '--output-junit', evidence/'update-results.xml', '-R', expression], 'update', env=env, check=False)
        shutil.copytree(build/'Testing', evidence/'Testing', dirs_exist_ok=True)
        files = [{'path': p.relative_to(evidence).as_posix(), 'size': p.stat().st_size, 'sha256': sha(p)}
                 for p in sorted((evidence/'canonicals').rglob('*')) if p.is_file()]
        (evidence/'canonical-manifest.json').write_text(json.dumps(files, indent=2)+'\n')
        # Upstream commands retain their scenes, samples, 25 candidates and derived tolerances.
        state['status'] = 'updates_passed' if result == 0 else 'updates_failed'
        state['canonical_files'] = len(files)
        save()
        if result:
            raise RuntimeError('One or more canonical update cases failed; partial outputs are retained')
        verify_canonicals(tests, evidence)
        state['canonical_outputs_verified'] = True
    except Exception as exc:
        state['status'] = 'failed'
        state['error'] = str(exc)
        save()
        raise
    finally:
        state['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    main()

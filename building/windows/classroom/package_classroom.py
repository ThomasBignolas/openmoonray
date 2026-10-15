# SPDX-License-Identifier: Apache-2.0
"""Package the classroom preparation tools and offline coordinator dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-bin', type=Path, help='Include the validated Windows Arras binaries')
    parser.add_argument('--bundle', type=Path, help='Portable bundle supplying dependency license notices')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    output = args.output.resolve()
    archive = output.with_name(output.name + '.zip')
    if output.exists() or archive.exists():
        parser.error('Use a new output directory and ZIP name')
    output.mkdir(parents=True)
    for name in ('Classroom.ps1', 'classroom.py', 'worker.py', 'LaunchHoudini.ps1', 'classroom.example.json', 'README.md',
                 'requirements.txt', 'requirements-lock.txt', 'test_classroom.py', 'test_houdini_preferences.py'):
        shutil.copy2(here / name, output / name)
    shutil.copy2(here.parent/'houdini/run_bounded.py', output/'run_bounded.py')
    if args.native_bin:
        if not args.bundle:
            parser.error('--native-bin requires --bundle for license notices')
        native = output/'native/bin'
        native.mkdir(parents=True)
        for path in args.native_bin.glob('*.dll'):
            if not path.name.startswith('arras_worker_'):
                shutil.copy2(path, native/path.name)
        for name in ('arras4_node.exe', 'arras4_router.exe', 'execComp.exe'):
            shutil.copy2(args.native_bin/name, native/name)
        shutil.copytree(args.bundle/'worker/licenses', output/'native/licenses')
        shutil.copy2(root/'arras/distributed/arras4_node/LICENSE', output/'native/licenses/arras4_node-LICENSE')
    upstream = root / 'arras/distributed/minicoord'
    shutil.copytree(upstream / 'minicoord', output / 'minicoord',
                    ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(upstream / 'LICENSE', output / 'minicoord/LICENSE')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-compile',
                    '--find-links', str(args.wheels.resolve()), '--require-hashes',
                    '-r', str(here / 'requirements-lock.txt'),
                    '--target', str(output / 'site-packages')], check=True)
    manifest = {'format': 1, 'stage': 'native-worker' if args.native_bin else 'preparation-only',
                'classroom_lan_validated': False,
                'native_windows_node_included': bool(args.native_bin), 'requires': 'MoonRay portable Windows bundle with Python 3.11',
                'files': []}
    for path in sorted(output.rglob('*')):
        if path.is_file():
            manifest['files'].append({'path': path.relative_to(output).as_posix(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (output / 'kit.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                zipped.write(path, path.relative_to(output.parent))
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        for item in manifest['files']:
            assert hashlib.sha256(zipped.read(output.name + '/' + item['path'])).hexdigest() == item['sha256']
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size,
                      'sha256': digest, 'files_verified': len(manifest['files'])}))


if __name__ == '__main__':
    main()

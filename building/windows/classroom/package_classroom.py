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
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    output = args.output.resolve()
    archive = output.with_name(output.name + '.zip')
    if output.exists() or archive.exists():
        parser.error('Use a new output directory and ZIP name')
    output.mkdir(parents=True)
    for name in ('Classroom.ps1', 'classroom.py', 'classroom.example.json', 'README.md',
                 'requirements.txt', 'requirements-lock.txt', 'test_classroom.py', 'test_houdini_preferences.py'):
        shutil.copy2(here / name, output / name)
    upstream = root / 'arras/distributed/minicoord'
    shutil.copytree(upstream / 'minicoord', output / 'minicoord',
                    ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(upstream / 'LICENSE', output / 'minicoord/LICENSE')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-compile',
                    '--find-links', str(args.wheels.resolve()), '--require-hashes',
                    '-r', str(here / 'requirements-lock.txt'),
                    '--target', str(output / 'site-packages')], check=True)
    manifest = {'format': 1, 'stage': 'preparation-only', 'distributed_render_validated': False,
                'native_windows_node_included': False, 'requires': 'MoonRay portable Windows bundle with Python 3.11',
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

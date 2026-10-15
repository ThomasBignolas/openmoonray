#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export Windows source changes and verify patches against the recorded Git bases.

The archive includes binary-safe patches for tracked changes, all non-ignored
untracked source files, and the revisions of the superproject and submodules.
The real Git indexes and working trees are never changed.
"""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New ZIP file; existing files are refused')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.exists():
        parser.error(f'Output already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    warnings = []

    def git(repository, *arguments, data=None, env=None):
        result = subprocess.run(['git', '-C', str(repository), *arguments],
                                input=data, capture_output=True, env=env, check=False)
        if result.stderr:
            warnings.append(result.stderr.decode('utf-8', errors='replace'))
        if result.returncode:
            raise RuntimeError(f'{repository}: git {arguments}: {result.stderr.decode(errors="replace")}')
        return result.stdout

    modules = configparser.ConfigParser()
    modules.read(root/'.gitmodules', encoding='utf-8')
    repositories = ['.'] + [modules[section]['path'] for section in modules.sections()]
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(),
                'repositories': [], 'files': [], 'patches_checked_against_base': 0}
    payloads = {}

    def include(name, data):
        assert name not in payloads, name
        payloads[name] = data
        manifest['files'].append({'path': name, 'bytes': len(data),
                                  'sha256': hashlib.sha256(data).hexdigest()})

    with tempfile.TemporaryDirectory(prefix='source-index-', dir=output.parent) as temporary:
        for index, relative in enumerate(repositories):
            repository = root/relative
            assert repository.resolve().is_relative_to(root), repository
            assert (repository/'.git').exists(), f'Uninitialized submodule: {relative}'
            head = git(repository, 'rev-parse', 'HEAD').decode().strip()
            if relative != '.':
                pin = git(root, 'ls-tree', 'HEAD', '--', relative).decode().split()
                assert pin[:2] == ['160000', 'commit'] and pin[2] == head, (relative, pin, head)
                assert not (repository/'.gitmodules').exists(), 'Nested submodules need explicit export support'
            patch = git(repository, 'diff', 'HEAD', '--binary', '--full-index',
                        '--no-ext-diff', '--no-textconv', '--ignore-submodules=all')
            row = {'path': relative, 'base_commit': head, 'patch': None, 'added_files': []}
            if patch:
                name = f'patches/{index:02d}-{repository.name}.patch'
                environment = {**os.environ, 'GIT_INDEX_FILE': str(Path(temporary)/f'{index}.index')}
                git(repository, 'read-tree', head, env=environment)
                git(repository, 'apply', '--cached', '--check',
                    data=patch, env=environment)
                include(name, patch)
                row['patch'] = name
                manifest['patches_checked_against_base'] += 1
            untracked = git(repository, 'ls-files', '--others', '--exclude-standard', '-z')
            for encoded in filter(None, untracked.split(b'\0')):
                path = repository/encoded.decode('utf-8')
                assert path.is_file() and not path.is_symlink(), path
                assert path.resolve().is_relative_to(root), path
                workspace_relative = path.relative_to(root).as_posix()
                assert not workspace_relative.startswith('build/'), path
                name = 'new-files/'+workspace_relative
                include(name, path.read_bytes())
                row['added_files'].append(name)
            manifest['repositories'].append(row)

    instructions = '''Windows source changes

Start with a separate clean OpenMoonRay checkout at the superproject commit in
manifest.json, with every submodule at its recorded base_commit. Keep your
existing working checkout unchanged. Fetch Git LFS assets for render tests.

For each manifest repository with a patch, run from that repository:
    git apply --check <absolute path to patch>
    git apply <absolute path to patch>
Then copy the contents of new-files/ into the superproject root, preserving
relative paths. Do not overwrite existing files: these paths are additions.
Read building/windows/README.md for build, runtime and validation instructions.

Every patch was checked against its base using an isolated Git index. This
verifies patch applicability; it is not a fresh-machine build validation.
The archive contains source changes only, without dependencies or binaries.
'''
    include('APPLY.txt', instructions.encode('utf-8'))
    payloads['manifest.json'] = (json.dumps(manifest, indent=2)+'\n').encode('utf-8')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(payloads)
        for name, data in payloads.items():
            assert archive.read(name) == data, name
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(f'{digest}  {output.name}\n')
    output.with_suffix('.validation.json').write_text(json.dumps({
        'archive': str(output), 'sha256': digest,
        'files_verified': len(payloads),
        'repositories_recorded': len(repositories),
        'patches_checked_against_base': manifest['patches_checked_against_base'],
        'added_source_files': sum(len(row['added_files']) for row in manifest['repositories']),
    }, indent=2)+'\n')
    output.with_suffix('.git-warnings.log').write_text(''.join(warnings))
    print(f'Created {output} ({output.stat().st_size} bytes); '
          f'{manifest["patches_checked_against_base"]} patches verified; SHA256 {digest}')


if __name__ == '__main__':
    main()

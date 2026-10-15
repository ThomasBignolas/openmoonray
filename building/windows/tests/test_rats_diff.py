# SPDX-License-Identifier: Apache-2.0
"""Exercise the upstream image-diff harness with real OIIO tools, not render baselines."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


repo = Path(__file__).resolve().parents[3]
tools = repo / 'build/deps/x64-windows/tools/openimageio'
cmake = shutil.which('cmake')
if not cmake:
    raise RuntimeError('Run from the Windows build environment')

with tempfile.TemporaryDirectory(prefix='rats diff ', dir=repo / 'build') as tmp:
    work = Path(tmp)
    canonical_dir = work / 'canonical images' / 'fixture' / 'scalar'
    canonical_dir.mkdir(parents=True)
    env = dict(os.environ, RATS_CANONICAL_DIR=str(work / 'canonical images'))

    def make_image(path, value):
        subprocess.run([str(tools / 'oiiotool.exe'), '--pattern',
                        f'constant:color={value},{value},{value}', '4x4', '3',
                        '-d', 'float', '-o', str(path)], check=True)

    make_image(canonical_dir / 'scene.exr', 0.5)
    (canonical_dir.parent / 'diff.json').write_text(json.dumps({
        'scene.exr': {'scalar': {'-fail': 0.05, '-failpercent': 0, '-hardfail': 0.05}}
    }), encoding='utf-8')

    def compare(expect_success, tool=tools / 'idiff.exe'):
        result = subprocess.run([
            cmake, '-DDIFF_IMAGE_FILENAME=difference.exr', '-DEXEC_MODE=scalar',
            f'-DIDIFF_TOOL={tool}', '-DIMAGE_FILENAME=scene.exr',
            '-DTEST_REL_PATH=fixture', '-P', str(repo / 'rats/cmake/diff.cmake')
        ], cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if (result.returncode == 0) != expect_success:
            raise AssertionError(result.stdout)

    make_image(work / 'scene.exr', 0.5)
    compare(True)
    make_image(work / 'scene.exr', 0.51)
    compare(True)
    make_image(work / 'scene.exr', 0.7)
    compare(False)
    compare(False, work / 'missing tool.exe')
    (work / 'scene.exr').unlink()
    compare(False)

print('RATS diff: identical image, tolerance, excessive difference, missing tool and missing result checks passed')

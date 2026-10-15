# SPDX-License-Identifier: Apache-2.0
"""Exercise canonical generation and comparison with synthetic noisy image fixtures.

These tiny fixtures validate the harness only; they are never renderer references.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[3]
cmake = shutil.which('cmake')
idiff = shutil.which('idiff')
oiiotool = shutil.which('oiiotool')
if not cmake or not idiff or not oiiotool:
    raise RuntimeError('Run from the Windows build and MoonRay environments.')
handles = []
if os.name == 'nt':
    for directory in os.environ['PATH'].split(os.pathsep):
        try:
            handles.append(os.add_dll_directory(directory))
        except OSError:
            pass
from OpenImageIO import ImageBuf, ImageBufAlgo, ImageSpec, FLOAT

with tempfile.TemporaryDirectory(prefix='rats canonical fixture ', dir=repo / 'build') as temporary:
    work = Path(temporary)
    inputs = work / 'input images'
    inputs.mkdir()
    canonicals = work / 'synthetic canonicals'
    canonicals.mkdir()
    for index in range(25):
        image = ImageBuf(ImageSpec(4, 4, 3, FLOAT))
        ImageBufAlgo.fill(image, [0.5 + index * 0.0001] * 3)
        assert image.write(str(inputs / f'{index}.exr')), image.geterror()
    fixture = work / 'copy candidate.py'
    fixture.write_text('import pathlib, shutil, sys\n'
                       'assert len(sys.argv) == 2, sys.argv\n'
                       'index = int(pathlib.Path.cwd().name)\n'
                       'shutil.copyfile(pathlib.Path(sys.argv[1]) / f"{index}.exr", "scene.exr")\n')
    command_file = work / 'command arguments.json'
    command_file.write_text(json.dumps([sys.executable, str(fixture), str(inputs)]), encoding='utf-8')
    env = dict(os.environ, RATS_CANONICAL_DIR=str(canonicals), RATS_MOONRAY_THREADS='4',
               RATS_RUN_CONCURRENT='0')
    for mode in ('default', 'scalar'):
        command = [sys.executable, str(repo / 'rats/cmake/update_canonicals.py'),
                   '--test-rel-path', 'fixture', '--canonicals', 'scene.exr',
                   '--render-command-file', str(command_file), '--exec-mode', mode,
                   '--idiff', idiff, '--diff-json', 'fixture/diff.json']
        result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        canonical = canonicals / 'fixture' / mode / 'scene.exr'
        assert canonical.is_file(), canonical
        # The middle of these equally spaced candidates minimizes total error.
        # Both directions of every cached pair must count toward each score.
        expected = ImageBuf(str(inputs / '12.exr'))
        chosen = ImageBuf(str(canonical))
        assert chosen.getpixel(0, 0) == expected.getpixel(0, 0), (
            'The canonical is not the candidate with the smallest total error',
            chosen.getpixel(0, 0), expected.getpixel(0, 0))
        thresholds = json.loads((canonicals / 'fixture/diff.json').read_text())
        assert thresholds['scene.exr'][mode]['-fail'] > 0
        shutil.copyfile(canonical, work / 'scene.exr')
        compare_command = [cmake, '-DDIFF_IMAGE_FILENAME=fixture.diff.exr',
                           '-DEXEC_MODE=' + mode, '-DIDIFF_TOOL=' + idiff,
                           '-DIMAGE_FILENAME=scene.exr', '-DTEST_REL_PATH=fixture',
                           '-P', str(repo / 'rats/cmake/diff.cmake')]
        comparison = subprocess.run(compare_command, cwd=work, env=env, capture_output=True, text=True)
        assert comparison.returncode == 0, comparison.stdout + comparison.stderr
        header_command = [cmake, '-DCANONICAL=fixture/' + mode + '/scene.exr',
                          '-DRESULT=scene.exr', '-DOIIO_TOOL=' + oiiotool,
                          '-P', str(repo / 'rats/cmake/diff_headers.cmake')]
        header = subprocess.run(header_command, cwd=work, env=env, capture_output=True, text=True)
        assert header.returncode == 0, header.stdout + header.stderr
        wrong_spec = ImageSpec(4, 4, 3, FLOAT)
        wrong_spec.attribute('reference_test', 'changed metadata')
        wrong = ImageBuf(wrong_spec)
        ImageBufAlgo.fill(wrong, [0.9] * 3)
        assert wrong.write(str(work / 'scene.exr')), wrong.geterror()
        comparison = subprocess.run(compare_command, cwd=work, env=env, capture_output=True, text=True)
        assert comparison.returncode != 0, 'The generated tolerances accepted a deliberately incorrect image.'
        header = subprocess.run(header_command, cwd=work, env=env, capture_output=True, text=True)
        assert header.returncode != 0, 'The header comparison accepted deliberately changed metadata.'
        print(f'PASS {mode}: 25 candidates, correct canonical path/key, exact match accepted, changed image and metadata rejected; paths contain spaces', flush=True)
    assert set(thresholds['scene.exr']) == {'default', 'scalar'}
    assert not (canonicals / 'fixture/auto').exists()

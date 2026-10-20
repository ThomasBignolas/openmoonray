"""Create an isolated Houdini worker from the validated standalone runtime."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--base', type=Path, required=True)
parser.add_argument('--destination', type=Path, required=True)
parser.add_argument('--xpu', action='store_true', help='Stage the OptiX-enabled worker, CUDA runtime and PTX')
args = parser.parse_args()
repo = Path(__file__).resolve().parents[3]
base, destination = args.base.resolve(), args.destination.resolve()
assert destination.is_relative_to(repo / 'build/windows/houdini') and destination != base
sources = [repo / 'build/windows/native/moonray/lib/grid/engine_tool/grid_engine_tool.dll',
           repo / 'build/windows/native/moonray/lib/rendering/shading/rendering_shading.dll',
           repo / 'build/windows/native/moonray/lib/rendering/rndr/rendering_rndr.dll',
           repo / 'build/windows/native/moonray/lib/rendering/pbr/rendering_pbr.dll',
           repo / 'build/windows/native/mcrt_computation/lib/engine/mcrt/computation_engine_mcrt.dll']
sources += [repo / 'build/windows/native/moonray/cmd/denoise_cmd/denoise.exe',
            repo / 'build/windows/native/mcrt_denoise/lib/denoiser/denoiser.dll']
gpu_files = []
for shader, folder in (('ImageMap', 'Image'), ('UsdUVTexture', 'UsdUVTexture')):
    shader_dir = repo / 'build/windows/native/moonray/dso/map' / folder
    for suffix in ('.dll', '.dll.proxy'):
        gpu_files.append((shader_dir / (shader + suffix), destination / 'rdl2dso' / (shader + suffix)))
    gpu_files.append((shader_dir / (shader + '.json'), destination / 'coredata' / (shader + '.json')))
if args.xpu:
    cache = (repo / 'build/windows/native/CMakeCache.txt').read_text()
    if 'MOONRAY_USE_OPTIX:BOOL=ON' not in cache:
        raise RuntimeError('Build with -WithOptix before staging an XPU worker')
    cuda_bin = Path(re.search(r'^CUDAToolkit_BIN_DIR:PATH=(.+)$', cache, re.M)[1])
    cuda_runtime = list(cuda_bin.glob('cudart64_*.dll'))
    # CUDA 13 stores DLLs in bin/x64.
    cuda_runtime += list((cuda_bin / 'x64').glob('cudart64_*.dll'))
    if len(cuda_runtime) != 1:
        raise RuntimeError(f'Expected one CUDA runtime in {cuda_bin}: {cuda_runtime}')
    sources += cuda_runtime
    ptx = repo / 'build/windows/native/shaders/OptixGPUPrograms.ptx'
    gpu_files.append((ptx, destination / 'shaders' / ptx.name))
    optix_include = Path(re.search(r'^OptiX_INCLUDE_DIRS:[^=]+=(.+)$', cache, re.M)[1])
    gpu_files.append((optix_include.parent / 'LICENSE.txt', destination / 'licenses/OptiX-LICENSE.txt'))
    gpu_files.append((cuda_bin.parent / 'EULA.txt', destination / 'licenses/CUDA-EULA.txt'))
for source in sources:
    if not source.is_file():
        raise FileNotFoundError(source)
for source, _ in gpu_files:
    if not source.is_file():
        raise FileNotFoundError(source)
if not destination.exists():
    shutil.copytree(base, destination)
manifest = {'base': str(base), 'worker': str(destination), 'cryptomatte_transport': 1, 'native_deep_output': 1,
            'xpu': args.xpu, 'binaries': {}}
for source in sources:
    target = destination / 'bin' / source.name
    shutil.copy2(source, target)
    manifest['binaries'][source.name] = hashlib.sha256(target.read_bytes()).hexdigest()
for source, target in gpu_files:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    manifest['binaries'][target.relative_to(destination).as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
if args.xpu:
    setup = destination / 'Setup.ps1'
    text = setup.read_text(encoding='utf-8-sig')
    if '$env:REZ_MOONRAY_ROOT' not in text:
        setup.write_text(text + '\n$env:REZ_MOONRAY_ROOT = $moonrayRuntimeRoot\n', encoding='utf-8')
    setup_cmd = destination / 'Setup.cmd'
    text = setup_cmd.read_text()
    if 'REZ_MOONRAY_ROOT=' not in text:
        setup_cmd.write_text(text + '\nset "REZ_MOONRAY_ROOT=%~dp0"\n')
(destination / 'houdini-worker.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))

"""Copy a staged Houdini host and worker into a relocatable end-user bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--worker', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--zip', action='store_true')
    args = parser.parse_args()
    host, worker, output = args.host.resolve(), args.worker.resolve(), args.output.resolve()
    archive = output.with_name(output.name + '.zip')
    if output.exists() or archive.exists():
        parser.error('Output must be a new directory and archive name')
    if output.is_relative_to(host) or output.is_relative_to(worker):
        parser.error('Output must not be inside either source runtime')
    for source in (host / 'plugin/hd_moonray.dll', host / 'bin/hydramoonray.dll',
                   worker / 'bin/execComp.exe', worker / 'bin/computation_progmcrt.dll'):
        if not source.is_file():
            raise FileNotFoundError(source)
    here = Path(__file__).resolve().parent
    output.mkdir(parents=True)
    print('Copying Houdini host and isolated worker', flush=True)
    shutil.copytree(host, output / 'host', ignore=shutil.ignore_patterns('*.lib', '*.pdb', '__pycache__'))
    shutil.copytree(worker, output / 'worker', ignore=shutil.ignore_patterns('*.pdb', '__pycache__'))
    for source in (here / 'portable').iterdir():
        if source.is_file():
            shutil.copy2(source, output / source.name)
    (output / 'docs').mkdir()
    shutil.copy2(here / 'README.md', output / 'docs/HOUDINI.md')
    shutil.copy2(here.parents[2] / 'LICENSE', output / 'LICENSE')
    (output / 'tests').mkdir()
    for name in ('run_bounded.py', 'validate_default_sphere.py'):
        shutil.copy2(here / name, output / 'tests' / name)
    # Remove machine-specific launch paths before archiving. Install.ps1 writes
    # actual paths from its own location after extraction on the destination PC.
    package_path = output / 'host/moonray.json'
    package = json.loads(package_path.read_text())
    for entry in package['env']:
        if 'MOONRAY_HOUDINI_ROOT' in entry:
            entry['MOONRAY_HOUDINI_ROOT'] = 'RUN_INSTALL_PS1_FIRST'
    package_path.write_text(json.dumps(package, indent=2) + '\n')
    for path in (output / 'host/sessions').glob('*.sessiondef'):
        session = json.loads(path.read_text())
        for name, computation in session['computations'].items():
            if name != '(client)':
                computation['environment'] = {'MOONRAY_PORTABLE_SETUP_REQUIRED': '1'}
        path.write_text(json.dumps(session, indent=2) + '\n')
    # The standalone base README predates the XPU overlay; avoid presenting its
    # CPU-only description as this bundle's capabilities.
    (output / 'worker/README.txt').write_text('Isolated MoonRay CPU/XPU worker. See ../README.txt.\n')
    manifest = {'format': 1, 'houdini_version': '21.0.729', 'platform': 'windows-x64',
                'cpu': 'AVX2', 'xpu_ptx_target': 'sm_75', 'cuda': '13.3', 'optix': '9.1',
                'files': []}
    for path in sorted(output.rglob('*')):
        if path.is_file():
            manifest['files'].append(dict(path=path.relative_to(output).as_posix(),
                bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (output / 'bundle.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(files=len(manifest['files']), bytes=sum(p['bytes'] for p in manifest['files']),
                          output=str(output))), flush=True)
    if args.zip:
        print('Writing portable archive', flush=True)
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zipped:
            for path in sorted(output.rglob('*')):
                if path.is_file():
                    zipped.write(path, path.relative_to(output.parent))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n')
        print(json.dumps(dict(archive=str(archive), bytes=archive.stat().st_size, sha256=digest)), flush=True)


if __name__ == '__main__':
    main()

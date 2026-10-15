"""Stage Houdini assets, native dependencies and isolated local worker settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess


def imports(path):
    data = path.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    optional_size = struct.unpack_from('<H', data, pe + 20)[0]
    optional = pe + 24
    directories = optional + (112 if struct.unpack_from('<H', data, optional)[0] == 0x20b else 96)
    rva = struct.unpack_from('<I', data, directories + 8)[0]
    sections = optional + optional_size
    def offset(address):
        for i in range(count):
            size, va, raw_size, raw = struct.unpack_from('<IIII', data, sections + 40*i + 8)
            if va <= address < va + max(size, raw_size):
                return raw + address - va
        raise ValueError(f'Invalid PE address {address}: {path}')
    if not rva:
        return []
    result = []
    descriptor = offset(rva)
    while any(data[descriptor:descriptor + 20]):
        name = offset(struct.unpack_from('<I', data, descriptor + 12)[0])
        result.append(data[name:data.index(b'\0', name)].decode('ascii'))
        descriptor += 20
    return result


def fix_light_defaults(asset_root):
    # Houdini 21 uses USD's versioned dome schema. Keep the upstream light
    # class expression working for both versions when creating native lights.
    for name in ('HdMoonrayRendererPlugin_Light.ds', 'moonray_Light.ds'):
        template = asset_root / 'soho/parameters' / name
        text = template.read_text()
        text = text.replace(r'value == \"UsdLuxDomeLight\"',
                            r'value in (\"UsdLuxDomeLight\", \"UsdLuxDomeLight_1\")')
        text = re.sub(r'primtype != UsdLuxDomeLight (?!primtype != UsdLuxDomeLight_1 )',
                      'primtype != UsdLuxDomeLight primtype != UsdLuxDomeLight_1 ', text)
        template.write_text(text)


def add_execution_settings(asset_root):
    parameters = asset_root / 'soho/parameters'
    fragment = (parameters / 'MoonRay_Execution.ds').read_text()
    for name in ('HdMoonrayRendererPlugin_Global.ds', 'moonray_Global.ds'):
        path = parameters / name
        text = path.read_text()
        first_group = text.index('    group {')
        path.write_text(text[:first_group] + fragment + '\n' + text[first_group:])


def stage(install, houdini, worker):
    repo = Path(__file__).resolve().parents[3]
    install = install.resolve()
    worker = worker.resolve()
    houdini = houdini.resolve()
    if not install.is_relative_to(repo):
        raise ValueError('Stage within the workspace')
    dcc = repo / 'moonray/moonray_dcc_plugins'
    asset_root = install / 'plugin/houdini'
    shutil.copytree(Path(__file__).with_name('assets'), asset_root, dirs_exist_ok=True)
    shutil.copytree(dcc / 'houdini/soho', asset_root / 'soho', dirs_exist_ok=True)
    fix_light_defaults(asset_root)
    add_execution_settings(asset_root)
    shutil.copy2(dcc / 'houdini/moonray_nodes.json', asset_root / 'moonray_nodes.json')
    translators = asset_root / 'husdplugins/shadertranslators'
    translators.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).with_name('moonray_shader_translator.py'), translators / 'moonray.py')
    # Git can store colons in filenames; Windows cannot. The HDA's internal
    # operator name stays unchanged when the on-disk filename is renamed.
    records = subprocess.check_output(['git', '-C', str(dcc), 'ls-tree', '-rz', 'HEAD', 'houdini/otls'])
    hdas = []
    for record in records.split(b'\0'):
        if not record:
            continue
        info, name = record.split(b'\t', 1)
        mode, kind, oid = info.split()
        if kind != b'blob':
            continue
        source = name.decode('utf-8')
        target = asset_root / 'otls' / re.sub(r'[<>:"/\\|?*]', '_', Path(source).name)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = subprocess.check_output(['git', '-C', str(dcc), 'cat-file', 'blob', oid.decode()])
        target.write_bytes(data)
        hdas.append({'source': source, 'installed': target.name, 'sha256': hashlib.sha256(data).hexdigest()})
    # The upstream shader assets predate the native filtering controls. Edit
    # only this staged copy with Houdini's own HDA API, in a clean subprocess.
    environment = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'PXR_PLUGINPATH_NAME', 'HOUDINI_PATH'):
        environment.pop(name, None)
    environment['PATH'] = str(houdini / 'bin') + ';C:/Windows/System32;C:/Windows'
    environment['HOUDINI_USER_PREF_DIR'] = str(install / '.stage-prefs21.0')
    environment['HOUDINI_MAXTHREADS'] = '2'
    with (install / 'texture-hda-staging.log').open('w') as log:
        subprocess.run([str(houdini / 'bin/hython.exe'), str(Path(__file__).with_name('configure_texture_hdas.py')),
                        '--install', str(install)], env=environment, stdout=log, stderr=subprocess.STDOUT,
                       timeout=120, check=True)
    for record in hdas:
        record['sha256'] = hashlib.sha256((asset_root / 'otls' / record['installed']).read_bytes()).hexdigest()
    # Only the process-isolated delegate is safe with Houdini's oneTBB ABI.
    renderers = json.loads((asset_root / 'UsdRenderers.json').read_text())
    renderers.pop('HdMoonrayRendererDebugPlugin', None)
    # Keep host scene updates on the UI thread; the Arras worker still renders
    # asynchronously. This avoids a Solaris background-update wait cycle.
    renderers['HdMoonrayRendererPlugin']['allowbackgroundupdate'] = False
    renderers['HdMoonrayRendererPlugin']['pauseonupdate'] = False
    renderers['HdMoonrayRendererPlugin']['diskproducttypes'] = ['deep']
    renderers['HdMoonrayRendererPlugin']['restartrendersettings'] = ['renderingColorSpace', 'moonray:colorSpace']
    (asset_root / 'UsdRenderers.json').write_text(json.dumps(renderers, indent=2) + '\n')
    shutil.copytree(worker / 'coredata', install / 'coredata', dirs_exist_ok=True)
    proxy_dir = install / 'rdl2dso'
    proxy_dir.mkdir(exist_ok=True)
    for source in (worker / 'rdl2dso').glob('*.proxy'):
        shutil.copy2(source, proxy_dir / source.name)

    sessions = install / 'sessions'
    sessions.mkdir(exist_ok=True)
    for source in (worker / 'sessions').glob('*.sessiondef'):
        value = json.loads(source.read_text())
        for name, computation in value.get('computations', {}).items():
            if name.startswith('('):
                continue
            computation['environment'] = {
                'PATH': f'{worker / "bin"};{worker / "lib"};{worker / "python"};{worker / "python/DLLs"};C:/Windows/System32;C:/Windows',
                'RDL2_DSO_PATH': str(worker / 'rdl2dso'),
                'MOONRAY_CLASS_PATH': str(worker / 'coredata'),
                'REZ_MOONRAY_ROOT': worker.as_posix(),
                'PXR_PLUGINPATH_NAME': f'{worker / "lib/usd"};{worker / "plugin/usd"}',
                'PYTHONHOME': str(worker / 'python'),
                'PYTHONPATH': str(worker / 'python/Lib/site-packages'),
            }
        (sessions / source.name).write_text(json.dumps(value, indent=2) + '\n')

    # Copy only the host delegate's dependency closure. In particular, never
    # put the standalone USD or Python runtime on Houdini's search path.
    pending = list((install / 'plugin').glob('*.dll')) + list((install / 'bin').glob('*.dll'))
    pending += list(proxy_dir.glob('*.proxy'))
    visited = set()
    external = set()
    dependency_origins = {}
    system = Path('C:/Windows/System32')
    while pending:
        binary = pending.pop()
        if binary.name.lower() in visited:
            continue
        visited.add(binary.name.lower())
        for name in imports(binary):
            if name.lower().startswith(('api-ms-', 'ext-ms-')) or (system / name).is_file():
                continue
            if (houdini / 'bin' / name).is_file():
                external.add(name)
                continue
            destination = install / 'bin' / name
            if not destination.is_file():
                source = next((folder / name for folder in (worker / 'bin', worker / 'lib',
                    worker / 'python/DLLs') if (folder / name).is_file()), None)
                if source is None:
                    raise FileNotFoundError(f'{binary.name} requires {name}')
                shutil.copy2(source, destination)
                dependency_origins[name] = str(source)
            pending.append(destination)
    # Houdini supplies OIDN and loads the matching device DLLs from its bin.
    # Do not mix the standalone worker's OIDN device plugins into the host.
    for name in ('OpenImageDenoise_core.dll', 'OpenImageDenoise_device_cpu.dll'):
        generated = install / 'bin' / name
        if generated.is_file() and (houdini / 'bin' / name).is_file():
            generated.unlink()
    package = {
        'enable': "houdini_os == 'windows' and houdini_version == '21.0.729'",
        'load_package_once': True,
        'env': [
            {'MOONRAY_HOUDINI_ROOT': install.as_posix()},
            {'PATH': {'value': '$MOONRAY_HOUDINI_ROOT/bin', 'method': 'append'}},
            {'PXR_PLUGINPATH_NAME': '$MOONRAY_HOUDINI_ROOT/plugin/pxr'},
            {'RDL2_DSO_PATH': '$MOONRAY_HOUDINI_ROOT/rdl2dso'},
            {'MOONRAY_CLASS_PATH': '$MOONRAY_HOUDINI_ROOT/coredata'},
            {'ARRAS_SESSION_PATH': '$MOONRAY_HOUDINI_ROOT/sessions'},
            {'HDMOONRAY_HOSTS': '0'},
            {'HDMOONRAY_PROXY_DSOS': '1'},
        ],
        'hpath': '$MOONRAY_HOUDINI_ROOT/plugin/houdini',
    }
    (install / 'moonray.json').write_text(json.dumps(package, indent=2) + '\n')
    report = {'houdini': str(houdini), 'worker': str(worker), 'hda_count': len(hdas),
              'hdas': hdas, 'host_libraries': sorted(external), 'dependencies': dependency_origins}
    (install / 'stage-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'hda_count': len(hdas), 'host_dependencies': len(visited), 'package': str(install / 'moonray.json')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--houdini', type=Path, required=True)
    parser.add_argument('--worker', type=Path, required=True)
    args = parser.parse_args()
    stage(args.install, args.houdini, args.worker)

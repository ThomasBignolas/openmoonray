"""Launch MoonRay's native denoiser in its isolated, bounded worker environment."""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import hou
from pxr import UsdRender

_jobs = {}


def parameters():
    result = [
        hou.ToggleParmTemplate('denoise_guides', 'Export Albedo and Normal Guides', default_value=False,
            help='Adds denoise_albedo (material albedo) and denoise_normal (signed shading normal). Enable before rendering. These are OIDN guides, not RenderMan variance passes.'),
        hou.LabelParmTemplate('denoise_note', 'Method', column_labels=(
            'Open Image Denoise / CPU. Scene-linear EXR, one frame at a time.',)),
        hou.StringParmTemplate('denoise_input', 'Input EXR', 1, default_value=('',),
            string_type=hou.stringParmType.FileReference,
            help='Empty reads the single Render Product path on this node at the current frame. If the render ROP overrides that path, choose its actual EXR here.'),
        hou.StringParmTemplate('denoise_output', 'Output EXR', 1, default_value=('',),
            string_type=hou.stringParmType.FileReference,
            help='Empty adds .denoised before the input extension. Writes beauty RGBA only. Existing files are never overwritten; choose a new name to rerun.'),
        hou.StringParmTemplate('denoise_layer', 'Beauty Layer', 1, default_value=('beauty',),
            help='EXR layer or part name. Empty selects unprefixed R/G/B channels.'),
        hou.ToggleParmTemplate('denoise_useguides', 'Use Exported Guides', default_value=True,
            help='Requires denoise_albedo and denoise_normal in the rendered EXR. Turn off for beauty-only denoising.'),
        hou.IntParmTemplate('denoise_threads', 'CPU Threads', 1, default_value=(4,), min=1, max=32,
            min_is_strict=True, help='The background job always leaves at least one available logical CPU free.'),
        hou.FloatParmTemplate('denoise_memory', 'Memory Limit (GB)', 1, default_value=(8,), min=1, max=32,
            min_is_strict=True, help='Aggregate process limit. The job also stops if system free memory falls below 6 GB.'),
    ]
    for action, label in (('start', 'Denoise Current Frame'), ('cancel', 'Cancel Denoise'), ('log', 'Open Last Denoise Log')):
        button = hou.ButtonParmTemplate('denoise_' + action, label)
        button.setScriptCallback(f"import moonray_denoise\nmoonray_denoise.action(kwargs['node'], '{action}')")
        button.setScriptCallbackLanguage(hou.scriptLanguage.Python)
        result.append(button)
    return result


def worker_environment(host):
    workers = set()
    for path in (host / 'sessions').glob('*.sessiondef'):
        for comp in json.loads(path.read_text())['computations'].values():
            worker = comp.get('environment', {}).get('REZ_MOONRAY_ROOT')
            if worker:
                workers.add(Path(worker).resolve())
    if len(workers) != 1:
        raise hou.OperationFailed('Cannot locate the isolated local MoonRay worker. Reinstall the portable package.')
    worker = workers.pop()
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PXR_PLUGINPATH_NAME', 'HOUDINI_PATH', 'HOUDINI_PACKAGE_DIR',
                'RDL2_DSO_PATH', 'OCIO', 'OIDN_DEFAULT_DEVICE'):
        env.pop(key, None)
    env.update(PATH=os.pathsep.join(str(worker / p) for p in ('bin', 'lib', 'python', 'python/DLLs')) +
               os.pathsep + os.pathsep.join((os.environ.get('SystemRoot', 'C:/Windows') + '/System32',
                                            os.environ.get('SystemRoot', 'C:/Windows'))),
               PYTHONHOME=str(worker / 'python'), OIDN_NUM_THREADS='4')
    return worker, env


def input_output(node):
    filename = node.evalParm('denoise_input')
    if not filename:
        stage = node.stage()
        if not stage or node.errors():
            raise hou.OperationFailed('Cook the MoonRay AOVs node successfully before denoising.')
        selected = node.evalParm('products').split()
        products = [UsdRender.Product(stage.GetPrimAtPath(p)) for p in selected] if selected else [
            UsdRender.Product(p) for p in stage.Traverse() if p.IsA(UsdRender.Product)
            and UsdRender.Product(p).GetProductTypeAttr().Get() == 'raster']
        if len(products) != 1 or not products[0]:
            raise hou.OperationFailed('Choose an Input EXR when the node has more than one Render Product.')
        filename = hou.expandString(str(products[0].GetProductNameAttr().Get()))
    source = Path(filename).resolve()
    output = node.evalParm('denoise_output')
    target = Path(output).resolve() if output else source.with_name(source.stem + '.denoised.exr')
    if not source.is_file():
        raise hou.OperationFailed('Render the frame first. Input EXR does not exist: ' + str(source))
    if source.suffix.lower() != '.exr' or target.suffix != '.exr':
        raise hou.OperationFailed('Choose an EXR input and a new .exr output.')
    if target == source or target.exists():
        raise hou.OperationFailed('Output already exists. Choose a new filename: ' + str(target))
    return source, target


def launch(node):
    for key, job in list(_jobs.items()):
        if job['process'].poll() is not None:
            if _jobs.get(key) is job:
                _jobs.pop(key, None)
    if node.sessionId() in _jobs:
        raise hou.OperationFailed('This node already has a denoise job running.')
    source, target = input_output(node)
    if any(job['target'] == target for job in _jobs.values()):
        raise hou.OperationFailed('A denoise job is already writing that output.')
    host = Path(hou.getenv('MOONRAY_HOUDINI_ROOT', ''))
    worker, env = worker_environment(host)
    guard = host / 'plugin/houdini/scripts/moonray/run_bounded.py'
    executable = worker / 'bin/denoise.exe'
    python = worker / 'python/python.exe'
    if not all(p.is_file() for p in (guard, executable, python)):
        raise hou.OperationFailed('MoonRay denoising tools are missing. Install the updated package.')
    target.parent.mkdir(parents=True, exist_ok=True)
    jobdir = target.parent / '.moonray-denoise' / uuid.uuid4().hex
    jobdir.mkdir(parents=True)
    log, report = jobdir / 'denoise.log', jobdir / 'resources.json'
    command = [str(executable), '-in', str(source), '-mode', 'oidn_cpu', '-out', str(target)]
    layer = node.evalParm('denoise_layer').strip()
    if layer:
        command += ['-layer', layer]
    if node.evalParm('denoise_useguides'):
        command += ['-albedo', str(source), '-albedo-layer', 'denoise_albedo',
                    '-normals', str(source), '-normal-layer', 'denoise_normal']
    threads = max(1, node.evalParm('denoise_threads'))
    env['OIDN_NUM_THREADS'] = str(threads)
    command = [str(python), str(guard), '--threads', str(threads),
        '--memory-gb', str(node.evalParm('denoise_memory')), '--min-free-gb', '6', '--timeout', '1800',
        '--log', str(log), '--report', str(report), '--'] + command
    with (jobdir / 'launcher.log').open('w') as launcher:
        process = subprocess.Popen(command, env=env, stdout=launcher, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    job = dict(process=process, target=target, log=log, report=report, directory=jobdir)
    key = node.sessionId()
    _jobs[key] = job
    node.setUserData('moonray_denoise_log', str(log))
    if hou.isUIAvailable():
        last = [0.]

        def poll():
            if time.monotonic() - last[0] < .5:
                return
            last[0] = time.monotonic()
            if process.poll() is None:
                return
            hou.ui.removeEventLoopCallback(poll)
            if _jobs.get(key) is job:
                _jobs.pop(key, None)
            if job.get('cancelled'):
                hou.ui.setStatusMessage('MoonRay denoising cancelled.')
            elif process.returncode == 0 and target.is_file():
                hou.ui.setStatusMessage('MoonRay denoised: ' + str(target))
            else:
                status = json.loads(report.read_text()).get('status') if report.is_file() else 'launch failed'
                details = log if log.is_file() else jobdir / 'launcher.log'
                hou.ui.displayMessage('MoonRay denoising failed (' + str(status) +
                    '). See the denoise log:\n' + str(details), severity=hou.severityType.Error)
        hou.ui.addEventLoopCallback(poll)
        hou.ui.setStatusMessage('MoonRay denoising in background: ' + str(source))
    return job


def action(node, name):
    try:
        if name == 'start':
            return launch(node)
        if name == 'cancel':
            job = _jobs.get(node.sessionId())
            if job and job['process'].poll() is None:
                # Closing the guard's job handle kills only its own children.
                job['cancelled'] = True
                job['process'].terminate()
        elif name == 'log':
            path = node.userData('moonray_denoise_log')
            if path and not Path(path).is_file():
                path = str(Path(path).with_name('launcher.log'))
            if path and Path(path).is_file():
                hou.ui.showInFileBrowser(path)
            else:
                raise hou.OperationFailed('No denoise log is available yet.')
    except (hou.Error, OSError, ValueError) as error:
        if not hou.isUIAvailable():
            raise
        hou.ui.displayMessage(str(error), title='MoonRay Denoising', severity=hou.severityType.Error)

"""Stop only this test's worker and require Husk to report a render failure."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import shutil
import time
import traceback

import hou
from validate_camera_projection import scene


class ProcessEntry(c.Structure):
    _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                ('heap', c.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD), ('name', w.WCHAR * 260)]


def stop_worker(parent):
    kernel = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateToolhelp32Snapshot': ([w.DWORD, w.DWORD], w.HANDLE),
        'Process32FirstW': ([w.HANDLE, c.POINTER(ProcessEntry)], w.BOOL),
        'Process32NextW': ([w.HANDLE, c.POINTER(ProcessEntry)], w.BOOL),
        'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(kernel, name).argtypes, getattr(kernel, name).restype = args, result
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    assert snapshot != c.c_void_p(-1).value
    entry = ProcessEntry()
    entry.size = c.sizeof(entry)
    entries = []
    try:
        present = kernel.Process32FirstW(snapshot, c.byref(entry))
        while present:
            entries.append((entry.pid, entry.parent, entry.name))
            present = kernel.Process32NextW(snapshot, c.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    # Require a direct child of the Husk process created by this test. Never
    # target a worker belonging to an existing Houdini session.
    workers = [pid for pid, owner, name in entries if owner == parent and name.lower() == 'execcomp.exe']
    assert len(workers) == 1, (parent, workers)
    handle = kernel.OpenProcess(1, False, workers[0])
    assert handle, c.get_last_error()
    try:
        assert kernel.TerminateProcess(handle, 99), c.get_last_error()
    finally:
        kernel.CloseHandle(handle)
    return workers[0]


def run(out):
    stage, _ = scene(out, 'interrupted', 'perspective')
    stage.GetPrimAtPath('/Render/settings').GetAttribute('moonray:sceneVariable:pixel_samples').Set(512)
    path = out / 'interrupted.usda'
    stage.GetRootLayer().Export(str(path))
    env = dict(os.environ, HDM_LOG_FILE=str(out / 'hydra.log'))
    with (out / 'husk.log').open('w') as log:
        process = subprocess.Popen([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer',
            'HdMoonrayRendererPlugin', '--disable-motionblur', str(path)], env=env,
            stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                text = (out / 'hydra.log').read_text(errors='replace') if (out / 'hydra.log').exists() else ''
                if 'First MoonRay image received' in text:
                    break
                assert process.poll() is None, 'Husk exited before the fault injection'
                time.sleep(.1)
            else:
                raise RuntimeError('No first image before fault-injection timeout')
            worker = stop_worker(process.pid)
            stopped = time.monotonic()
            try:
                code = process.wait(timeout=12)
                timed_out = False
            except subprocess.TimeoutExpired:
                code, timed_out = None, True
            elapsed = time.monotonic() - stopped
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    checks = dict(husk_exits_after_worker_loss=not timed_out,
                  husk_reports_failure=code is not None and code != 0)
    return dict(passed=all(checks.values()), checks=checks, husk_pid=process.pid,
                worker_pid=worker, husk_returncode=code, seconds_after_worker_loss=elapsed,
                installation=hou.getenv('MOONRAY_HOUDINI_ROOT'))


def run_startup(out):
    # Override only this test's session definition and Houdini preferences.
    # The installed worker, package and any open Houdini session are untouched.
    root = Path(hou.getenv('MOONRAY_HOUDINI_ROOT'))
    sessions = out / 'sessions'
    shutil.copytree(root / 'sessions', sessions, dirs_exist_ok=True)
    definition = sessions / 'hd_single.sessiondef'
    data = json.loads(definition.read_text())
    data['computations']['mcrt']['dso'] = str(out / 'intentionally-missing-worker.dll')
    definition.write_text(json.dumps(data, indent=2))
    prefs = out / 'prefs21.0'
    (prefs / 'packages').mkdir(parents=True, exist_ok=True)
    package = json.loads((root / 'moonray.json').read_text())
    for entry in package['env']:
        if 'ARRAS_SESSION_PATH' in entry:
            entry['ARRAS_SESSION_PATH'] = sessions.as_posix()
    (prefs / 'packages/moonray.json').write_text(json.dumps(package, indent=2))
    stage, _ = scene(out, 'startup', 'perspective')
    path = out / 'startup.usda'
    stage.GetRootLayer().Export(str(path))
    env = dict(os.environ, HOUDINI_USER_PREF_DIR=str(prefs), HDM_LOG_FILE=str(out / 'hydra.log'))
    started = time.monotonic()
    with (out / 'husk.log').open('w') as log:
        result = subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer',
            'HdMoonrayRendererPlugin', '--disable-motionblur', str(path)], env=env,
            stdout=log, stderr=subprocess.STDOUT, timeout=30)
    text = (out / 'husk.log').read_text(errors='replace')
    checks = dict(husk_reports_failure=result.returncode != 0,
                  failed_startup_diagnosed='Failed to create an Arras session' in text,
                  missing_worker_identified='intentionally-missing-worker.dll' in text,
                  delegate_error_reported='Delegate fatal error' in text)
    return dict(passed=all(checks.values()), checks=checks, husk_returncode=result.returncode,
                elapsed_seconds=time.monotonic() - started, installation=str(root))


def run_lifecycle(out, executable, scene_path):
    root = Path(hou.getenv('MOONRAY_HOUDINI_ROOT'))
    env = dict(os.environ, PATH=str(root / 'plugin') + os.pathsep + os.environ['PATH'],
               HDM_LOG_FILE=str(out / 'hydra.log'))
    started = time.monotonic()
    with (out / 'lifecycle.log').open('w') as log:
        result = subprocess.run([str(executable.resolve()), str(scene_path.resolve())], env=env,
            stdout=log, stderr=subprocess.STDOUT, timeout=65)
    text = (out / 'lifecycle.log').read_text(errors='replace')
    checks = dict(clean_exit=result.returncode == 0)
    for step in ('initial frame', 'healthy restart', 'recovery after worker loss', 'renderer lifecycle'):
        checks[step] = step + ' passed' in text
    return dict(passed=all(checks.values()), checks=checks, returncode=result.returncode,
                elapsed_seconds=time.monotonic() - started, installation=str(root))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--startup', action='store_true')
    parser.add_argument('--lifecycle', type=Path, help='Native lifecycle test executable')
    parser.add_argument('--scene', type=Path, help='Small RDLA scene for the lifecycle test')
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        if args.lifecycle:
            assert args.scene, '--scene is required with --lifecycle'
            result = run_lifecycle(args.out, args.lifecycle, args.scene)
        else:
            result = run_startup(args.out) if args.startup else run(args.out)
    except Exception:
        result = dict(passed=False, error=traceback.format_exc())
    (args.out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result['passed'] else 1)

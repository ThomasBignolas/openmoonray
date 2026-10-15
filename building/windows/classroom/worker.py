# SPDX-License-Identifier: Apache-2.0
"""Foreground, user-level launcher for the native Windows Arras worker."""
import ctypes as c
from ctypes import wintypes as w
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import build_opener, ProxyHandler, Request

from classroom import HERE, NATIVE_WORKER_FILES, RENDER_FILES, get_json, write_json
from run_bounded import ExtendedLimits, MemoryStatus

# Keep this handle alive until process exit. Closing a kill-on-close job containing
# this launcher would kill the launcher itself. Windows releases it on exit and
# removes any surviving descendants, including routers and computations.
_job = None


def resource_job(threads, memory_mb):
    global _job
    kernel = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
        'GlobalMemoryStatusEx': ([c.POINTER(MemoryStatus)], w.BOOL),
        'GetCurrentProcess': ([], w.HANDLE),
        'GetProcessAffinityMask': ([w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)], w.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        getattr(kernel, name).argtypes, getattr(kernel, name).restype = arguments, result
    def checked(result):
        if not result:
            raise c.WinError(c.get_last_error())
        return result
    available = MemoryStatus()
    available.Length = c.sizeof(available)
    checked(kernel.GlobalMemoryStatusEx(c.byref(available)))
    if available.AvailablePhysical < (memory_mb + 6144) * 2**20:
        raise ValueError('Free memory must cover the worker budget plus 6 GB for the workstation')
    process_mask, system_mask = c.c_size_t(), c.c_size_t()
    checked(kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), c.byref(process_mask), c.byref(system_mask)))
    cpus = [bit for bit in range(64) if process_mask.value & (1 << bit)]
    if len(cpus) < 2:
        raise ValueError('At least two available logical CPUs are needed to leave one free')
    count = min(threads, len(cpus) - 1)
    limits = ExtendedLimits()
    limits.Basic.Flags = 0x2000 | 0x200 | 0x10
    limits.Basic.Affinity = sum(1 << bit for bit in cpus[:count])
    limits.JobMemory = memory_mb * 2**20
    handle = checked(kernel.CreateJobObjectW(None, None))
    try:
        checked(kernel.SetInformationJobObject(handle, 9, c.byref(limits), c.sizeof(limits)))
        checked(kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()))
    except Exception:
        kernel.CloseHandle(handle)
        raise
    _job = handle
    return count, kernel


def run_worker(bundle, cfg, bind, http_port, router_port, state_dir, duration):
    if os.name != 'nt':
        raise ValueError('This worker package requires Windows')
    address = ipaddress.IPv4Address(bind)
    if address.is_unspecified or address.is_multicast:
        raise ValueError('Select one local IPv4 interface, not 0.0.0.0')
    if http_port == router_port or any(not 1024 <= p <= 65535 for p in (http_port, router_port)):
        raise ValueError('Worker HTTP and router ports must be different and in 1024..65535')
    if not 0 <= duration <= 86400:
        raise ValueError('duration must be 0 for interactive use, or 1..86400 seconds')
    # Fail before starting anything if either port is already occupied.
    for port in (http_port, router_port):
        with socket.socket() as probe:
            probe.bind((bind, port))
    worker = bundle / 'worker'
    native = HERE / 'native/bin'
    for path in [native / name for name in NATIVE_WORKER_FILES] + [worker / name for name in RENDER_FILES]:
        if not path.is_file():
            raise ValueError('Missing runtime file: ' + str(path))
    budget = cfg['worker_memory_mb'] + cfg['merge_memory_mb'] + cfg['dispatch_memory_mb']
    threads, kernel = resource_job(cfg['worker_threads'], budget + 512)
    if state_dir:
        state = state_dir.resolve()
        state.mkdir(parents=True, exist_ok=False)
    else:
        state = Path(tempfile.mkdtemp(prefix='mr-'))
    if len(str(state / ('n-' + '0' * 36)).encode('utf-8')) >= 108:
        raise ValueError('IPC path is too long; use --state-dir with a new, shorter local folder')
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PXR_PLUGINPATH_NAME', 'ARRAS_SESSION_PATH', 'HDMOONRAY_STACK'):
        env.pop(key, None)
    env.update(PATH=';'.join(str(p) for p in [native, worker/'bin', worker/'lib',
                                            worker/'python', worker/'python/DLLs']) +
               ';' + os.environ.get('SystemRoot', 'C:/Windows') + '/System32',
               PYTHONHOME=str(worker/'python'), PYTHONPATH=str(worker/'python/Lib/site-packages'),
               RDL2_DSO_PATH=str(worker/'rdl2dso'), MOONRAY_CLASS_PATH=str(worker/'coredata'),
               REZ_MOONRAY_ROOT=str(worker), PXR_PLUGINPATH_NAME=str(worker/'plugin/pxr'),
               NO_PROXY='*', no_proxy='*')
    command = [native/'arras4_node.exe', '--coordinator-host', cfg['coordinator'],
               '--coordinator-port', cfg['coordinator_port'], '--no-consul',
               '--cores', threads + 1, '--memory', str(budget) + 'm', '--max-node-memory', '256m',
               '--http-port', http_port, '--router-port', router_port, '--bind', bind,
               '--ipc-dir', state, '--enforce-memory', '1', '--enforce-cpu', '1', '--use-color', '0']
    report = {'state': 'starting', 'bind': bind, 'http_port': http_port, 'router_port': router_port,
              'logical_cpus': threads, 'memory_limit_mb': budget + 512, 'log': str(state/'worker.log')}
    write_json(state/'worker.json', report)
    print(json.dumps(report), flush=True)
    print('Starting worker. Ctrl+C stops it. Detailed log: ' + str(state/'worker.log'), flush=True)
    base = f'http://{bind}:{http_port}'
    process = None
    registered = False
    started = time.monotonic()
    try:
        with (state/'worker.log').open('w') as log:
            process = subprocess.Popen([str(s) for s in command], env=env, stdout=log,
                                       stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            while process.poll() is None:
                if not registered:
                    try:
                        get_json(base+'/node/1/health')
                        registered = True
                        report.update(state='ready', pid=process.pid)
                        write_json(state/'worker.json', report)
                        print('Worker ready at ' + base + '. Keep this window open.', flush=True)
                    except Exception:
                        if time.monotonic() - started > 30:
                            raise RuntimeError('Worker startup timed out; inspect worker.log')
                if duration and time.monotonic() - started >= duration:
                    break
                status = MemoryStatus()
                status.Length = c.sizeof(status)
                if not kernel.GlobalMemoryStatusEx(c.byref(status)):
                    raise c.WinError(c.get_last_error())
                if status.AvailablePhysical < 6 * 2**30:
                    raise RuntimeError('Stopping worker because less than 6 GB of system RAM remains free')
                time.sleep(0.25)
    except KeyboardInterrupt:
        print('Stopping worker...', flush=True)
    except Exception as error:
        report.update(state='failed', error=str(error))
        raise
    finally:
        if process and process.poll() is None:
            if registered:
                try:
                    req = Request(base+'/status', data=b'{"status":"shutdown"}',
                                  headers={'Content-Type':'application/json'}, method='PUT')
                    with build_opener(ProxyHandler({})).open(req, timeout=3):
                        pass
                    process.wait(timeout=20)
                except Exception:
                    process.terminate()
            else:
                process.terminate()
            process.wait(timeout=5)
        if report['state'] != 'failed':
            report['state'] = 'stopped'
        report['exit_code'] = process.returncode if process else None
        write_json(state/'worker.json', report)
    if process and process.returncode:
        raise RuntimeError(f'Worker exited {process.returncode}; see {state / "worker.log"}')
    return 0

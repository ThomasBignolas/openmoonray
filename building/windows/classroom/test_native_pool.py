# SPDX-License-Identifier: Apache-2.0
"""Bounded, loopback-only integration test of real Windows Arras nodes."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import build_opener, ProxyHandler, Request

import classroom


def request(url, data=None):
    req = Request(url, data=json.dumps(data).encode() if data is not None else None,
                  headers={'Content-Type': 'application/json'},
                  method='PUT' if data is not None else 'GET')
    with build_opener(ProxyHandler({})).open(req, timeout=3) as response:
        body = response.read()
        return json.loads(body.rstrip(b'\0')) if body else None


def until(fn, processes, timeout=20):
    end = time.monotonic() + timeout
    error = None
    while time.monotonic() < end:
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('A pool process exited; inspect the logs')
        try:
            value = fn()
            if value:
                return value
        except Exception as ex:
            error = ex
        time.sleep(0.1)
    raise RuntimeError('Timed out: ' + str(error))


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--native-bin', type=Path, required=True)
    parser.add_argument('--coordinator-kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--nodes', type=int, choices=(1, 2), default=2)
    parser.add_argument('--houdini-dir', type=Path, help='Also render Solaris scenes through hython/husk')
    parser.add_argument('--launchers', action='store_true', help='Exercise the packaged worker launcher')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bundle = args.bundle.resolve()
    worker = bundle / 'worker'
    native = args.native_bin.resolve()
    kit = args.coordinator_kit.resolve()
    cfg = classroom.config(kit / 'classroom.example.json')
    cfg.update(coordinator='127.0.0.1', coordinator_port=free_port(),
               render_workers=args.nodes, worker_memory_mb=3072,
               worker_threads=4, merge_memory_mb=512, dispatch_memory_mb=128)
    classroom.write_json(out / 'config.json', cfg)
    classroom.prepare(bundle, cfg, out / 'client')
    env = dict(os.environ)
    env.update(PATH=';'.join(str(p) for p in [native, worker/'bin', worker/'lib',
                                            worker/'python', worker/'python/DLLs']) +
               ';C:/Windows/System32;C:/Windows',
               PYTHONHOME=str(worker/'python'),
               PYTHONPATH=str(worker/'python/Lib/site-packages'),
               RDL2_DSO_PATH=str(worker/'rdl2dso'), MOONRAY_CLASS_PATH=str(worker/'coredata'),
               REZ_MOONRAY_ROOT=str(worker), PXR_PLUGINPATH_NAME=str(worker/'plugin/pxr'),
               NO_PROXY='*', no_proxy='*')
    logs, processes, nodes = [], [], []
    def spawn(command, name, child_env=None):
        log = (out / (name + '.log')).open('w')
        logs.append(log)
        proc = subprocess.Popen([str(s) for s in command], env=child_env,
                                stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(proc)
        return proc
    try:
        spawn([worker/'python/python.exe', '-E', '-s', kit/'classroom.py', 'coordinator',
               '--bundle', bundle, '--config', out/'config.json', '--duration', '0'], 'coordinator')
        base = classroom.coordinator_url(cfg)
        until(lambda: request(base+'/status'), processes)
        for index in range(args.nodes):
            port = free_port()
            ipc = root / 'build' / ('an' + str(os.getpid()) + '-' + str(index))
            if args.launchers:
                command = [worker/'python/python.exe', '-E', '-s', kit/'classroom.py', 'worker',
                           '--bundle', bundle, '--config', out/'config.json', '--bind', '127.0.0.1',
                           '--http-port', port, '--router-port', free_port(), '--state-dir', ipc]
            else:
                command = [native/'arras4_node.exe', '--coordinator-host', '127.0.0.1',
                          '--coordinator-port', cfg['coordinator_port'], '--no-consul',
                          '--cores', '4', '--memory', '4096m', '--max-node-memory', '256m',
                          '--http-port', port, '--router-port', free_port(), '--bind', '127.0.0.1',
                          '--ipc-dir', ipc, '--enforce-memory', '1', '--enforce-cpu', '1',
                          '--use-color', '0', '-l', '4']
            node = spawn(command, 'node' + str(index), env)
            nodes.append((node, port))
            until(lambda: request(base+'/status')['nodes'] == index + 1, processes)
            request(f'http://127.0.0.1:{port}/node/1/health')
        render = spawn([worker/'python/python.exe', root/'building/windows/tests/test_arras_renders.py',
                        worker, '--bundle', '--remote-url', base, '--hosts', args.nodes,
                        '--session-directory', out/'client/sessions', '--output', out/'images',
                        '--timeout', '75'], 'render', env)
        code = render.wait(timeout=165)
        if code:
            raise RuntimeError(f'Render exited {code}; inspect render.log and images/*/render.log')
        processes.remove(render)
        until(lambda: request(base+'/status')['sessions'] == 0, processes)
        houdini_result = None
        if args.houdini_dir:
            houdini_env = dict(os.environ)
            for key in ('PYTHONHOME', 'PYTHONPATH', 'PXR_PLUGINPATH_NAME', 'HOUDINI_PATH',
                        'HOUDINI_PACKAGE_DIR', 'ARRAS_SESSION_PATH'):
                houdini_env.pop(key, None)
            houdini_env.update(HOUDINI_USER_PREF_DIR=str(out/'client/prefs21.0'),
                               HOUDINI_NO_ENV_FILE='1', HDMOONRAY_LOGLEVEL='4',
                               PATH=str(args.houdini_dir.resolve()/'bin')+';C:/Windows/System32;C:/Windows')
            houdini = spawn([args.houdini_dir.resolve()/'bin/hython.exe',
                             root/'building/windows/houdini/validate_default_sphere.py',
                             '--out', out/'houdini', '--mesh-resolution', '4'], 'houdini', houdini_env)
            assert houdini.wait(timeout=180) == 0, 'Houdini validation failed'
            processes.remove(houdini)
            houdini_result = classroom.read_json(out/'houdini/validation.json')
            assert houdini_result['passed']
            until(lambda: request(base+'/status')['sessions'] == 0, processes)
        exits = []
        for node, port in nodes:
            request(f'http://127.0.0.1:{port}/status', {'status':'shutdown'})
            code = node.wait(timeout=15)
            assert code == 0, code
            exits.append(code)
        assert request(base+'/status')['nodes'] == 0
        report = {'passed':True, 'native_nodes':args.nodes, 'network':'loopback only',
                  'node_exit_codes':exits, 'sessions_remaining':0,
                  'renders':classroom.read_json(out/'images/results.json'), 'houdini':houdini_result}
        classroom.write_json(out/'result.json', report)
        print(json.dumps(report, indent=2))
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()

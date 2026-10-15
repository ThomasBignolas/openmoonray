# SPDX-License-Identifier: Apache-2.0
"""Verify native node cleanup after router and coordinator startup failures."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    worker = args.bundle.resolve()/'worker'
    native = args.kit.resolve()/'native/bin'
    env = dict(os.environ, PATH=str(native)+';'+str(worker/'bin')+';C:/Windows/System32;C:/Windows')
    results = []
    # Occupied listening ports prevent accidental contact with another service.
    with socket.socket() as unavailable, socket.socket() as occupied:
        unavailable.bind(('127.0.0.1', 0))
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        for case in ('router_port_occupied', 'coordinator_unavailable'):
            with socket.socket() as temporary:
                temporary.bind(('127.0.0.1', 0))
                router_port = temporary.getsockname()[1]
            if case == 'router_port_occupied':
                router_port = occupied.getsockname()[1]
            ipc = Path(__file__).resolve().parents[3]/'build'/('af'+str(os.getpid()))
            command = [native/'arras4_node.exe', '--coordinator-host', '127.0.0.1',
                       '--coordinator-port', unavailable.getsockname()[1], '--no-consul',
                       '--cores', '3', '--memory', '2048m', '--max-node-memory', '256m',
                       '--bind', '127.0.0.1', '--router-port', router_port,
                       '--ipc-dir', ipc, '--use-color', '0']
            with (args.output/(case+'.log')).open('w') as log:
                proc = subprocess.Popen([str(s) for s in command], env=env, stdout=log,
                                        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    code = proc.wait(timeout=25)
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=5)
            assert code in (255, 4294967295), (case, code)
            if case == 'coordinator_unavailable':
                with socket.socket() as probe:
                    probe.settimeout(1)
                    assert probe.connect_ex(('127.0.0.1', router_port)) != 0, 'Orphan router remains'
            results.append({'case':case, 'exit_code':code, 'clean_failure':True})
    report = {'passed':True, 'cases':results}
    (args.output/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()

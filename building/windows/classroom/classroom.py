# SPDX-License-Identifier: Apache-2.0
"""Prepare, run and diagnose a portable Windows Arras classroom pool."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'site-packages'))
MINICOORD = HERE / 'minicoord'
if not MINICOORD.is_dir():
    MINICOORD = HERE.parents[2] / 'arras/distributed/minicoord/minicoord'
sys.path.insert(0, str(MINICOORD))

NATIVE_WORKER_FILES = ('arras4_node.exe', 'arras4_router.exe', 'execComp.exe')
RENDER_FILES = ('bin/execComp.exe', 'bin/computation_progmcrt.dll',
                'bin/computation_progmcrt_dispatch.dll', 'bin/computation_progmcrt_merge.dll')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def config(path):
    value = read_json(path)
    host = value.get('coordinator', '')
    # Host only; disallow URLs, credentials, paths, IPv6 (not yet validated),
    # whitespace and shell syntax. No network scan or implicit discovery.
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', host):
        raise ValueError('coordinator must be an IPv4 address or hostname, without http:// or a port')
    bounds = {'coordinator_port': (1024, 65535), 'render_workers': (1, 32),
              'worker_threads': (1, 256), 'worker_memory_mb': (1024, 262144),
              'merge_threads': (1, 32), 'merge_memory_mb': (256, 65536),
              'dispatch_memory_mb': (128, 16384), 'fps': (1, 30)}
    for key, (low, high) in bounds.items():
        number = value.get(key)
        if type(number) is not int or not low <= number <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
    if value.get('execution_mode') not in ('vectorized', 'scalar', 'xpu'):
        raise ValueError('execution_mode must be vectorized, scalar or xpu')
    return value


def get_json(url, timeout=3):
    # School proxy settings should not send private pool traffic to a proxy.
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url, headers={'Accept': 'application/json'}), timeout=timeout) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('Unexpectedly large response')
    # Native Arras HTTP responses can include a trailing C-string terminator.
    return json.loads(data.rstrip(b'\0'))


def coordinator_url(value):
    return f'http://{value["coordinator"]}:{value["coordinator_port"]}'


def check(bundle, value, contact=False, assets=None):
    worker = bundle / 'worker'
    missing_render = [p for p in RENDER_FILES if not (worker / p).is_file()]
    missing_node = [p for p in NATIVE_WORKER_FILES if not (HERE / 'native/bin' / p).is_file()]
    cpus = os.cpu_count() or 1
    threads = max(1, min(value['worker_threads'], cpus - 1))
    result = {'kind': 'pool-readiness', 'distributed_render_validated': False,
              'hostname': socket.gethostname(), 'logical_cpus': cpus,
              'proposed_worker_threads': threads, 'reserved_logical_cpus': cpus - threads,
              'missing_render_files': missing_render, 'missing_native_worker_files': missing_node,
              'blockers': [], 'coordinator': coordinator_url(value)}
    if missing_render:
        result['blockers'].append('Incomplete MoonRay worker bundle')
    if missing_node:
        result['blockers'].append('Native Arras runtime is missing from this kit; use the native worker package')
    if cpus < 2:
        result['blockers'].append('At least two logical CPUs are needed to leave one free')
    if assets:
        mismatches = []
        for item in read_json(assets)['files']:
            path = Path(item['path'])
            if not path.is_file() or sha256(path) != item['sha256']:
                mismatches.append(str(path))
        result['asset_mismatches'] = mismatches
        if mismatches:
            result['blockers'].append('Asset files are missing or differ from the manifest')
    if contact:
        try:
            status = get_json(coordinator_url(value) + '/status')
            if not all(type(status.get(k)) is int for k in ('nodes', 'sessions')):
                raise ValueError('Not a minicoord status response')
            result['coordinator_status'] = status
            if status['nodes'] < value['render_workers']:
                result['blockers'].append('Fewer registered nodes than requested render workers')
        except Exception as error:
            result['blockers'].append('Coordinator unavailable: ' + str(error))
    else:
        result['network_checked'] = False
    result['prerequisites_present'] = not result['blockers']
    result['next_step'] = ('Start the coordinator and workers, then test a small two-PC viewport render. '
                           'An HTTP probe does not validate Arras message routing or image merging.')
    return result


def prepare(bundle, value, output):
    if output.exists():
        raise ValueError('Use a new output directory; existing settings are never overwritten')
    host = bundle / 'host'
    package = read_json(host / 'moonray.json')
    sessions = {}
    for name in ('hd_single', 'hd_multi'):
        session = read_json(bundle / 'worker/sessions' / (name + '.sessiondef'))
        for role, computation in session['computations'].items():
            if role == '(client)':
                continue
            # Worker-local paths are inherited from each node's own environment.
            # Sending this client's absolute paths breaks a remote installation.
            computation.pop('environment', None)
            # Losing any render/dispatch/merge computation invalidates the image.
            # End the session so the client sees a disconnect instead of waiting
            # indefinitely for pixels from a failed worker.
            computation['exitKillsSession'] = True
            requirements = computation.setdefault('requirements', {})
            requirements['packaging_system'] = 'current-environment'
            for key in ('rez_packages', 'rez_context', 'rez_packages_prepend'):
                requirements.pop(key, None)
            if role == 'mcrt':
                requirements['resources'] = {'minCores': 1, 'maxCores': '*',
                                             'memoryMB': value['worker_memory_mb']}
                computation['exec_mode'] = value['execution_mode']
                if name == 'hd_multi':
                    computation['arrayExpand'] = value['render_workers']
            else:
                requirements['resources'] = {'cores': value['merge_threads'] if role == 'merge' else 1,
                                             'memoryMB': value[role + '_memory_mb']}
            computation['fps'] = value['fps']
        sessions[name] = session
    viewport_source = host / 'plugin/houdini/soho/parameters/HdMoonrayRendererPlugin_Viewport.ds'
    viewport = viewport_source.read_text()
    for name, default in [('useRemoteHosts', '1'), ('remoteHosts', str(value['render_workers'])),
                          ('maxFps', str(value['fps'])), ('executionMode', '"' + value['execution_mode'] + '"')]:
        pattern = r'(name\s+"' + name + r'"(?:(?!\n\s*parm\s*\{).)*?default\s*\{)[^}]*(\})'
        viewport, count = re.subn(pattern, lambda m: m[1] + ' ' + default + ' ' + m[2], viewport, flags=re.S)
        if count != 1:
            raise ValueError('Cannot find exactly one viewport control: ' + name)
    output.mkdir(parents=True)
    for name, session in sessions.items():
        write_json(output / 'sessions' / (name + '.sessiondef'), session)
    env = {'MOONRAY_HOUDINI_ROOT': host.as_posix(),
           'ARRAS_SESSION_PATH': (output / 'sessions').as_posix(),
           'HDMOONRAY_STACK': 'url-' + coordinator_url(value),
           'HDMOONRAY_HOSTS': str(value['render_workers'])}
    for entry in package['env']:
        for key in set(entry) & set(env):
            entry[key] = env.pop(key)
    package['env'].extend({key: item} for key, item in env.items())
    # Houdini prepends each hpath entry in order, so the override goes last.
    package['hpath'] = ['$MOONRAY_HOUDINI_ROOT/plugin/houdini', (output / 'overlay').as_posix()]
    write_json(output / 'prefs21.0/packages/moonray.json', package)
    viewport_path = output / 'overlay/soho/parameters/HdMoonrayRendererPlugin_Viewport.ds'
    viewport_path.parent.mkdir(parents=True)
    viewport_path.write_text(viewport)
    write_json(output / 'classroom.json', value)
    readiness = check(bundle, value)
    write_json(output / 'readiness.json', readiness)
    (output / 'README.txt').write_text(
        'Prepared Arras client configuration. Validate the classroom LAN before project use.\n'
        'See readiness.json and the kit README for worker startup and limitations.\n'
        'These preferences are isolated; your normal Houdini installation is unchanged.\n'
        'With workers registered, launch Houdini 21.0.729 with HOUDINI_USER_PREF_DIR\n'
        'set to this folder/prefs21.0 and HOUDINI_NO_ENV_FILE=1.\n'
        'The MoonRay viewport defaults to remote rendering with the configured worker count.\n'
        'The settings contain paths to this extraction: regenerate after moving it.\n')
    return {'prepared': True, 'directory': str(output), 'readiness': readiness}


def serve_coordinator(bind, port, duration):
    import asyncio
    import logging
    from coord_service import CoordService
    from tornado.ioloop import IOLoop
    # The upstream interactive run.py starts an IOLoop in a thread without an
    # asyncio loop. Run the actual upstream service on this process's main loop.
    logging.basicConfig(level=logging.INFO)
    asyncio.set_event_loop(asyncio.new_event_loop())
    application = CoordService(port)
    server = application.listen(port, address=bind)
    loop = IOLoop.current()
    if duration:
        loop.call_later(duration, loop.stop)
    print(json.dumps({'coordinator_listening': bind, 'port': port,
                      'status': 'minicoord ready; no workers started'}), flush=True)
    try:
        loop.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        application.coord.shutdown_all()
        loop.close(all_fds=True)


def listen_probe(bind, port, duration):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/moonray-network-probe':
                self.send_error(404)
                return
            data = b'{"protocol":"moonray-classroom-probe-v1","render_worker":false}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(2)

    # Diagnostic only: no file serving, node registration or command execution.
    with HTTPServer((bind, port), Handler) as server:
        server.timeout = 0.25
        print(json.dumps({'probe_listening': bind, 'port': server.server_port,
                          'seconds': duration, 'render_worker': False}), flush=True)
        until = time.monotonic() + duration
        try:
            while time.monotonic() < until:
                server.handle_request()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'prepare', 'coordinator', 'worker', 'listen', 'probe', 'assets'])
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=HERE / 'classroom.example.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--contact', action='store_true', help='Contact only the configured coordinator')
    parser.add_argument('--assets', type=Path, help='Verify assets from an explicit manifest')
    parser.add_argument('--file', type=Path, action='append', default=[], help='Explicit asset for manifest creation')
    parser.add_argument('--bind', default='127.0.0.1', help='Local IPv4 interface; default is loopback')
    parser.add_argument('--port', type=int, default=8889, help='Probe listener port')
    parser.add_argument('--duration', type=int, help='Lifetime in seconds; worker/coordinator default to running until Ctrl+C')
    parser.add_argument('--url', help='Exact probe URL printed in the guide; no discovery/scanning')
    parser.add_argument('--http-port', type=int, default=8890, help='Worker control port')
    parser.add_argument('--router-port', type=int, default=8891, help='Worker message port')
    parser.add_argument('--state-dir', type=Path, help='New local directory for worker state and logs')
    args = parser.parse_args()
    if args.duration is None:
        args.duration = 0 if args.action in ('coordinator', 'worker') else 120
    try:
        value = config(args.config)
        bundle = args.bundle.resolve()
        if not (bundle / 'worker/python/python.exe').is_file():
            raise ValueError('Bundle must be the extracted MoonRay portable package')
        if args.action == 'check':
            result = check(bundle, value, args.contact, args.assets)
            code = 0 if result['prerequisites_present'] else 2
        elif args.action == 'prepare':
            if not args.output:
                raise ValueError('--output must name a new directory')
            result = prepare(bundle, value, args.output.resolve())
            code = 0
        elif args.action == 'worker':
            from worker import run_worker
            return run_worker(bundle, value, args.bind, args.http_port, args.router_port,
                              args.state_dir, args.duration)
        elif args.action in ('coordinator', 'listen'):
            address = ipaddress.IPv4Address(args.bind)
            if address.is_unspecified or address.is_multicast:
                raise ValueError('Bind to one explicit local interface, not 0.0.0.0')
            if not 0 <= args.duration <= 86400 or (args.action == 'listen' and args.duration == 0):
                raise ValueError('duration must be 1..86400 (or 0 for an interactive coordinator)')
            if args.action == 'coordinator':
                # Avoid proxying outgoing node requests; environment changes are
                # confined to this process and are never stored system-wide.
                os.environ['NO_PROXY'] = '*'
                serve_coordinator(args.bind, value['coordinator_port'], args.duration)
            else:
                if not 1024 <= args.port <= 65535:
                    raise ValueError('port must be 1024..65535')
                listen_probe(args.bind, args.port, args.duration)
            return 0
        elif args.action == 'probe':
            parsed = urlsplit(args.url or '')
            if (parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path != '/moonray-network-probe' or parsed.query or parsed.fragment):
                raise ValueError('--url must be http://PC:PORT/moonray-network-probe')
            result = get_json(args.url)
            if result.get('protocol') != 'moonray-classroom-probe-v1' or result.get('render_worker') is not False:
                raise ValueError('Endpoint is not the classroom network probe')
            result.update(reachable=True, url=args.url, distributed_render_validated=False)
            code = 0
        else:
            if not args.output or args.output.exists() or not args.file:
                raise ValueError('assets requires --file paths and a new --output manifest')
            result = {'files': [{'path': str(path.resolve()), 'sha256': sha256(path)} for path in args.file]}
            code = 0
        if args.output and args.action != 'prepare':
            write_json(args.output, result)
        print(json.dumps(result, indent=2))
        return code
    except Exception as error:
        print(json.dumps({'error': str(error), 'distributed_render_validated': False}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

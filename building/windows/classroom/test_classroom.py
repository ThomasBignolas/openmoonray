# SPDX-License-Identifier: Apache-2.0
"""Real loopback HTTP plus coordinator accounting tests; no render workers."""
import argparse
import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
from urllib.request import build_opener, ProxyHandler, Request
from urllib.error import HTTPError

parser = argparse.ArgumentParser()
parser.add_argument('--bundle', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.bundle = args.bundle.resolve()
args.output.mkdir(parents=True, exist_ok=True)
import classroom
from allocate import RequiredResources
from coord import Coord
from node import Node, HTTP_TIMEOUT
from session import Session


def register(coordinator, hostname, cores=4, memory=8192):
    value = {'id': str(uuid.uuid4()), 'hostname': hostname, 'ipAddress': '127.0.0.1',
             'httpPort': 9999, 'port': 9998, 'resources': {'cores': cores, 'memoryMB': memory}}
    coordinator.register_node_request(value)
    node = coordinator.node(value['id'])
    node.is_test_node = True
    return node


def single(cores):
    return {'sessionDef': {'computations': {
        '(client)': {}, 'a': {'requirements': {'resources': {'cores': cores, 'memoryMB': 1024}}},
        'b': {'requirements': {'resources': {'cores': cores, 'memoryMB': 1024}}}}}}


class Accounting(unittest.TestCase):
    def test_failed_allocation_does_not_consume_resources_or_keep_session(self):
        co = Coord()
        node = register(co, '127.0.0.1')
        for _ in range(3):
            self.assertIsNone(co.create_session_request(single(3)))
            self.assertEqual((node.resources.free.cores, node.resources.free.memory), (4, 8192))
            self.assertEqual(node.resources.per_session, {})
            self.assertEqual(co.sessions, {})
        good = co.create_session_request(single(2))
        self.assertEqual(node.resources.free.cores, 0)
        co.terminate_session_request(good['sessionId'], 'test complete')
        self.assertEqual(node.resources.free.cores, 4)
        self.assertEqual(node.resources.per_session, {})

    def test_variable_maximum_is_clamped_to_available(self):
        self.assertEqual(RequiredResources((1, 8), 1024).maxCores(3), 3)
        co = Coord()
        node = register(co, '127.0.0.1', cores=3)
        definition = {'sessionDef': {'computations': {'(client)': {}, 'mcrt': {
            'requirements': {'resources': {'minCores': 1, 'maxCores': 8, 'memoryMB': 1024}}}}}}
        session = co.create_session_request(definition)
        self.assertEqual(node.resources.free.cores, 0)
        co.terminate_session_request(session['sessionId'], 'test complete')
        self.assertEqual(node.resources.free.cores, 3)

    def test_all_outgoing_worker_requests_have_timeouts(self):
        node = register(Coord(), '127.0.0.1')
        node.is_test_node = False
        with patch('node.requests.post') as post, patch('node.requests.put') as put, patch('node.requests.delete') as delete:
            node.launch('session', {})
            node.update('session', {'status': 'run'})
            node.delete_session('session', 'test')
            node.shutdown('test')
            for call in post.call_args_list + put.call_args_list + delete.call_args_list:
                self.assertEqual(call.kwargs['timeout'], HTTP_TIMEOUT)
            self.assertEqual(sum(len(x.call_args_list) for x in (post, put, delete)), 4)


class Preparation(unittest.TestCase):
    def setUp(self):
        self.value = classroom.config(classroom.HERE / 'classroom.example.json')
        self.temp = tempfile.TemporaryDirectory(dir=args.output)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_sessions_are_portable_and_two_workers_merge_into_one_client(self):
        output = self.root / 'client'
        original = (args.bundle / 'host/moonray.json').read_bytes()
        classroom.prepare(args.bundle, self.value, output)
        session = classroom.read_json(output / 'sessions/hd_multi.sessiondef')
        for name, comp in session['computations'].items():
            if name != '(client)':
                self.assertNotIn('environment', comp)
                self.assertEqual(comp['requirements']['packaging_system'], 'current-environment')
        self.assertEqual(session['computations']['(client)']['messages'], {'merge': '*'})
        co = Coord()
        a, b = register(co, '127.0.0.1'), register(co, 'localhost')
        request = co.create_session_request({'sessionDef': session})
        active = co.sessions[request['sessionId']]
        workers = [comp for comp in active.computations.values() if comp.basename == 'mcrt']
        self.assertEqual(len(workers), 2)
        self.assertEqual(len({comp.node_id for comp in workers}), 2)
        self.assertEqual({comp.config['machineId'] for comp in workers}, {0, 1})
        self.assertTrue(all(comp.config['numMachines'] == 2 for comp in workers))
        self.assertIn('mcrt_i0', active.message_filter)
        self.assertIn('merge', active.message_filter['mcrt_i0'])
        self.assertIn('merge', active.message_filter['mcrt_i1'])
        self.assertIn('(client)', active.message_filter['merge'])
        self.assertEqual(a.resources.free.cores + b.resources.free.cores, 0)
        co.terminate_session_request(active.id, 'test complete')
        self.assertEqual(a.resources.free.cores + b.resources.free.cores, 8)
        self.assertEqual((args.bundle / 'host/moonray.json').read_bytes(), original)
        with self.assertRaises(ValueError):
            classroom.prepare(args.bundle, self.value, output)

    def test_asset_mismatch_and_missing_worker_are_reported(self):
        asset = self.root / 'texture.tx'
        asset.write_bytes(b'original fixture')
        manifest = self.root / 'assets.json'
        classroom.write_json(manifest, {'files': [{'path': str(asset), 'sha256': classroom.sha256(asset)}]})
        self.assertEqual(classroom.check(args.bundle, self.value, assets=manifest)['asset_mismatches'], [])
        asset.write_bytes(b'different fixture')
        result = classroom.check(args.bundle, self.value, assets=manifest)
        self.assertEqual(result['asset_mismatches'], [str(asset)])
        self.assertFalse(result['distributed_render_validated'])
        self.assertTrue(result['missing_native_worker_files'])
        self.assertFalse(result['prerequisites_present'])

    def test_config_rejects_invalid_values_and_reserves_a_cpu(self):
        for key, value in [('coordinator', 'http://host/'), ('render_workers', 0), ('worker_threads', True), ('fps', 40)]:
            cfg = dict(self.value, **{key: value})
            path = self.root / 'invalid.json'
            classroom.write_json(path, cfg)
            with self.assertRaises(ValueError):
                classroom.config(path)
        with patch('classroom.os.cpu_count', return_value=4):
            self.assertEqual(classroom.check(args.bundle, self.value)['proposed_worker_threads'], 3)


class Loopback(unittest.TestCase):
    def start(self, action):
        with socket.socket() as bound:
            bound.bind(('127.0.0.1', 0))
            port = bound.getsockname()[1]
        cfg = classroom.config(classroom.HERE / 'classroom.example.json')
        cfg['coordinator_port'] = port
        path = args.output / (action + '-config.json')
        classroom.write_json(path, cfg)
        log = (args.output / (action + '.log')).open('w')
        process = subprocess.Popen([sys.executable, '-E', '-s', str(classroom.HERE / 'classroom.py'),
            action, '--bundle', str(args.bundle), '--config', str(path), '--bind', '127.0.0.1',
            '--port', str(port), '--duration', '4'], stdout=log, stderr=subprocess.STDOUT)
        def cleanup():
            try:
                process.wait(timeout=7)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            finally:
                log.close()
        self.addCleanup(cleanup)
        url = f'http://127.0.0.1:{port}'
        endpoint = '/status' if action == 'coordinator' else '/moonray-network-probe'
        until = time.monotonic() + 3
        while True:
            try:
                status = classroom.get_json(url + endpoint, timeout=0.3)
                break
            except Exception:
                if process.poll() is not None or time.monotonic() > until:
                    raise
                time.sleep(0.05)
        return url, status

    def test_real_minicoord_http_rejection_and_status(self):
        url, status = self.start('coordinator')
        self.assertEqual(status, {'nodes': 0, 'sessions': 0})
        opener = build_opener(ProxyHandler({}))
        for _ in range(2):
            request = Request(url + '/coordinator/1/sessions', data=json.dumps(single(2)).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(HTTPError) as error:
                opener.open(request, timeout=2)
            self.assertEqual(error.exception.code, 503)
        self.assertEqual(classroom.get_json(url + '/status')['sessions'], 0)

    def test_probe_reaches_real_tcp_listener_without_impersonating_worker(self):
        url, status = self.start('listen')
        self.assertEqual(status, {'protocol': 'moonray-classroom-probe-v1', 'render_worker': False})
        with self.assertRaises(HTTPError) as error:
            classroom.get_json(url + '/private-file')
        self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    classroom.write_json(args.output / 'validation.json', {
        'passed': result.wasSuccessful(), 'tests': result.testsRun,
        'render_workers_started': 0, 'network': 'loopback only',
        'distributed_render_validated': False,
        'limits': ['Native Windows node/router port required', 'No second PC or real multi-worker render tested']})
    sys.exit(0 if result.wasSuccessful() else 1)

from collections import deque
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import appserver_dispatch as runner


class RpcDeadlines(unittest.TestCase):
    def client(self):
        client = runner.RpcClient.__new__(runner.RpcClient)
        client.buffer = b''
        client.lines = deque()
        client.notifications = deque()
        client.next_id = 0
        return client

    def test_expired_read_does_not_consume_queued_response(self):
        client = self.client()
        client.lines.append(b'{"id":1,"result":{}}')
        with patch.object(runner.time, 'monotonic', side_effect=[0.0, 0.2]):
            with self.assertRaises(TimeoutError):
                client.read(0.1)
        self.assertEqual(len(client.lines), 1)

    def test_rpc_deadline_expires_with_queued_notifications(self):
        client = self.client()
        client.lines.extend([b'{"method":"event","params":{}}'] * 100)
        client.lines.append(b'{"id":1,"result":{}}')
        clock = itertools.count(0.0, 0.01)
        with patch.object(client, 'send'), patch.object(runner.time, 'monotonic', side_effect=lambda: next(clock)):
            with self.assertRaises(TimeoutError):
                client.request('turn/interrupt', {}, timeout=0.1)
        self.assertGreater(len(client.lines), 0)
        self.assertGreater(len(client.notifications), 0)

    def test_response_that_arrives_after_deadline_is_not_success(self):
        client = self.client()
        with patch.object(client, 'send'), patch.object(client, 'read', return_value={'id': 1, 'result': {}}), \
                patch.object(runner.time, 'monotonic', side_effect=[0.0, 0.0, 0.2]):
            with self.assertRaises(TimeoutError):
                client.request('thread/start', {}, timeout=0.1)

    def fake(self, mode):
        root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-rpc-tests'))) / uuid.uuid4().hex
        root.mkdir(parents=True)
        script = root / 'fake_server.py'
        script.write_text('''import json, sys, time
mode = sys.argv[1]
flood = (json.dumps({'method': 'event', 'params': {'delta': 'x' * 80}}) + '\\n') * 100000
print(json.dumps({'ready': True}), flush=True)
if mode == 'blocked-input':
    time.sleep(30)
else:
    for line in sys.stdin:
        request = json.loads(line)
        sys.stdout.write(flood + json.dumps({'id': request['id'], 'result': {}}) + '\\n')
        sys.stdout.flush()
''')
        client = self.client()
        client.process = subprocess.Popen([sys.executable, str(script), mode], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        os.set_blocking(client.process.stdin.fileno(), False)
        self.addCleanup(client.close)
        self.assertTrue(client.read(5)['ready'])
        return client, root

    def test_streaming_fake_server_obeys_total_deadline(self):
        client, root = self.fake('flood')
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            client.request('turn/interrupt', {}, timeout=0.02)
        elapsed = time.monotonic() - started
        (root / 'result.json').write_text(json.dumps({'elapsed': elapsed, 'deadline': 0.02,
                                                    'notifications': len(client.notifications)}))
        self.assertLess(elapsed, 1.0)

    def test_blocked_pipe_write_shares_rpc_deadline(self):
        client, root = self.fake('blocked-input')
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, 'write timed out'):
            client.request('turn/start', {'input': 'x' * 2_000_000}, timeout=0.05)
        elapsed = time.monotonic() - started
        (root / 'result.json').write_text(json.dumps({'elapsed': elapsed, 'deadline': 0.05}))
        self.assertLess(elapsed, 1.0)


class ProjectAndPermissionBoundary(unittest.TestCase):
    def root(self):
        root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-rpc-tests'))) / uuid.uuid4().hex
        root.mkdir(parents=True)
        return root

    def test_same_project_allows_source_subdirectory_and_destination_root(self):
        root = self.root()
        source = root / 'subdir'
        source.mkdir()
        inventory = [{'id': 'project', 'roots': [{'path': str(root)}]}]
        runner.verify_project(inventory, 'project', source, root)
        context = {'sandboxMode': 'workspace-write', 'sandboxPolicy': {'writableRoots': [str(root)]}}
        runner.verify_destination_permissions(context, source, root)
        context['sandboxPolicy']['writableRoots'] = []
        with self.assertRaisesRegex(ValueError, 'expand source writable access'):
            runner.verify_destination_permissions(context, source, root)

    def test_nested_repository_and_foreign_source_are_rejected(self):
        root = self.root()
        source = root / 'nested'
        source.mkdir()
        subprocess.run(['git', 'init', str(source)], check=True, capture_output=True)
        inventory = [{'id': 'project', 'roots': [{'path': str(root)}]}]
        with self.assertRaisesRegex(RuntimeError, 'checkout'):
            runner.verify_project(inventory, 'project', source, root)
        with self.assertRaisesRegex(RuntimeError, 'checkout'):
            runner.verify_project(inventory, 'project', root.parent, root)


if __name__ == '__main__':
    unittest.main()

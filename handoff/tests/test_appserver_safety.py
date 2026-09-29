import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import appserver_dispatch as runner
import dispatch


FAKE = r'''#!/usr/bin/env python3
import fcntl, json, os, sys
from pathlib import Path
root = Path(os.environ['HANDOFF_FAKE_ROOT'])
lock = (root / 'writer.lock').open('w')
fcntl.flock(lock, fcntl.LOCK_EX)
mode = os.environ.get('HANDOFF_FAKE_MODE', '')
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    r = json.loads(line)
    if 'method' not in r or 'id' not in r:
        continue
    m, p = r['method'], r.get('params', {})
    with (root / 'requests.jsonl').open('a') as f:
        f.write(json.dumps(r) + '\n')
    if m == 'initialize':
        result = {}
    elif m == 'project/list':
        result = {'data': [{'id': 'project-test', 'roots': [{'path': str(root)}]}], 'nextCursor': None}
    elif m == 'thread/start':
        policy = {'type': 'dangerFullAccess'}
        if p['sandbox'] == 'workspace-write':
            policy = {'type': 'workspaceWrite', 'networkAccess': p['config']['sandbox_workspace_write.network_access'],
                      'writableRoots': p['config']['sandbox_workspace_write.writable_roots'],
                      'excludeTmpdirEnvVar': p['config']['sandbox_workspace_write.exclude_tmpdir_env_var'],
                      'excludeSlashTmp': p['config']['sandbox_workspace_write.exclude_slash_tmp']}
        if mode == 'mismatch':
            policy = {'type': 'workspaceWrite'}
        result = {'thread': {'id': 'thread-test', 'projectId': 'project-test', 'cwd': str(root)},
                  'model': p['model'], 'modelProvider': 'wrong-provider' if mode == 'provider-mismatch' else p['modelProvider'],
                  'reasoningEffort': p['config']['model_reasoning_effort'],
                  'approvalPolicy': p['approvalPolicy'], 'approvalsReviewer': p['approvalsReviewer'],
                  'sandbox': policy, 'runtimeWorkspaceRoots': ['/unexpected'] if mode == 'roots-mismatch' else p['runtimeWorkspaceRoots']}
    elif m == 'thread/name/set':
        result = {}
    elif m == 'turn/start':
        result = {'turn': {'id': 'turn-test'}}
        # A server request can use the same numeric ID as an in-flight client request.
        # It must not be mistaken for the turn/start response.
        if mode.startswith('item/') or mode.startswith('mcpServer/') or mode.startswith('future/'):
            send({'method': 'turn/completed', 'params': {'threadId': 'another-thread',
                  'turn': {'id': 'another-turn', 'status': 'completed'}}})
            send({'id': r['id'], 'method': mode,
                  'params': {'threadId': 'thread-test', 'turnId': 'turn-test'}})
        elif mode == 'foreign-request':
            send({'id': r['id'], 'method': 'future/request',
                  'params': {'threadId': 'foreign-thread', 'turnId': 'foreign-turn'}})
    elif m == 'turn/interrupt':
        result = {}
    elif m == 'thread/read':
        result = {'thread': {'id': 'thread-test', 'projectId': 'project-test', 'cwd': str(root), 'name': 'Next'}}
    else:
        send({'id': r['id'], 'error': {'message': 'unexpected method'}})
        continue
    send({'id': r['id'], 'result': result})
    if m == 'turn/start' and mode == 'complete':
        send({'method': 'turn/completed', 'params': {'threadId': 'thread-test',
              'turn': {'id': 'turn-test', 'status': 'completed'}}})
    if m == 'turn/start' and mode == 'failed':
        send({'method': 'turn/completed', 'params': {'threadId': 'thread-test',
              'turn': {'id': 'turn-test', 'status': 'failed',
                       'error': {'message': 'Synthetic rate limit', 'codexErrorInfo': 'usageLimitExceeded'}}}})
'''


class DispatchSafety(unittest.TestCase):
    def fixture(self, mode, workspace=False, nested_source=False):
        root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-safety-tests'))) / uuid.uuid4().hex
        root.mkdir(parents=True)
        source_workspace = root / 'source-subdir' if nested_source else root
        source_workspace.mkdir(exist_ok=True)
        (root / 'codex').write_text(FAKE)
        (root / 'codex').chmod(0o755)
        packet, prompt, source = root / 'packet.md', root / 'prompt.txt', root / 'source.jsonl'
        packet.write_text('# Next action\nContinue existing work.\n')
        prompt.write_text('Read packet.md and continue.')
        policy = {'type': 'workspace-write', 'network_access': False, 'writable_roots': [str(root)],
                  'exclude_tmpdir_env_var': True, 'exclude_slash_tmp': True} if workspace else {'type': 'danger-full-access'}
        context = {'cwd': str(source_workspace), 'model': 'observed-source-model', 'effort': 'high',
                   'approval_policy': 'on-request' if workspace else 'never',
                   'approvals_reviewer': 'user', 'sandbox_policy': policy, 'workspace_roots': [str(root)]}
        source.write_text(json.dumps({'type': 'session_meta', 'payload': {
                              'id': 'source-test', 'model_provider': 'observed-provider'}}) + '\n' +
                          json.dumps({'type': 'turn_context', 'payload': context}) + '\n')
        receipt = root / 'packet.receipt.json'
        dispatch.prepare(receipt, packet, 'invocation-test', 'source-test', source_workspace,
                         destination_workspace=root if nested_source else None)
        attempt = dispatch.claim(receipt)['receipt']['attempt_id']
        command = [sys.executable, str(SCRIPTS / 'appserver_dispatch.py'), '--receipt', str(receipt),
                   '--attempt-id', attempt, '--packet', str(packet), '--project-id', 'project-test',
                   '--cwd', str(root), '--title', 'Next', '--prompt-file', str(prompt),
                   '--source-rollout', str(source)]
        env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                   HANDOFF_FAKE_ROOT=str(root), HANDOFF_FAKE_MODE=mode)
        return root, receipt, attempt, command, env

    def test_interactive_requests_release_writer_without_grant_or_duplicate(self):
        for method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval',
                       'item/permissions/requestApproval', 'item/tool/requestUserInput',
                       'mcpServer/elicitation/request', 'future/request'):
            with self.subTest(method=method):
                root, receipt, attempt, command, env = self.fixture(method)
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 3, result.stderr + result.stdout)
                state = json.loads(runner.runtime_path(receipt, attempt).read_text())
                self.assertEqual(state['state'], 'attention_required')
                self.assertTrue(state['writerReleased'])
                self.assertEqual(state['requestMethod'], method)
                with (root / 'writer.lock').open() as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                requests = [json.loads(l) for l in (root / 'requests.jsonl').read_text().splitlines()]
                self.assertEqual(sum(r['method'] == 'thread/start' for r in requests), 1)
                self.assertEqual(requests[-1]['method'], 'turn/interrupt')
                self.assertFalse(any('accept' in json.dumps(r) for r in requests))
                self.assertEqual(dispatch.read(receipt)['dispatch_state'], 'created')
                self.assertFalse(dispatch.claim(receipt)['may_create'])

    def test_preserves_restricted_source_and_model(self):
        root, receipt, attempt, command, env = self.fixture('complete', workspace=True)
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        requests = [json.loads(l) for l in (root / 'requests.jsonl').read_text().splitlines()]
        started = next(r['params'] for r in requests if r['method'] == 'thread/start')
        self.assertEqual(started['modelProvider'], 'observed-provider')
        initialized = next(r['params'] for r in requests if r['method'] == 'initialize')
        self.assertEqual(initialized['clientInfo']['version'], (SCRIPTS.parent / 'VERSION').read_text().strip())
        turn = next(r['params'] for r in requests if r['method'] == 'turn/start')
        self.assertEqual(turn['model'], 'observed-source-model')
        self.assertEqual(turn['effort'], 'high')
        self.assertEqual(turn['approvalPolicy'], 'on-request')
        self.assertEqual(turn['sandboxPolicy'], {'type': 'workspaceWrite', 'networkAccess': False,
                         'writableRoots': [str(root)], 'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True})
        self.assertTrue(json.loads(runner.runtime_path(receipt, attempt).read_text())['writerReleased'])

    def test_nested_source_keeps_source_identity_and_uses_claimed_destination(self):
        root, receipt, attempt, command, env = self.fixture('complete', workspace=True, nested_source=True)
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        record = dispatch.read(receipt)
        self.assertEqual(record['source_workspace'], str(root / 'source-subdir'))
        self.assertEqual(record['destination_workspace'], str(root))
        requests = [json.loads(line) for line in (root / 'requests.jsonl').read_text().splitlines()]
        start = next(request['params'] for request in requests if request['method'] == 'thread/start')
        self.assertEqual(start['cwd'], str(root))
        self.assertEqual(start['runtimeWorkspaceRoots'], [str(root)])
        self.assertTrue(json.loads(runner.runtime_path(receipt, attempt).read_text())['writerReleased'])

    def test_permission_mismatch_stops_before_model_turn_and_releases(self):
        root, receipt, attempt, command, env = self.fixture('mismatch')
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
        self.assertNotEqual(result.returncode, 0)
        requests = [json.loads(l) for l in (root / 'requests.jsonl').read_text().splitlines()]
        self.assertFalse(any(r['method'] == 'turn/start' for r in requests))
        state = json.loads(runner.runtime_path(receipt, attempt).read_text())
        self.assertTrue(state['writerReleased'])
        self.assertEqual(state['threadId'], 'thread-test')
        self.assertFalse(dispatch.claim(receipt)['may_create'])

    def test_provider_and_explicit_empty_roots_mismatches_stop_before_turn(self):
        for mode in ('provider-mismatch', 'roots-mismatch'):
            with self.subTest(mode=mode):
                root, receipt, attempt, command, env = self.fixture(mode)
                source = root / 'source.jsonl'
                events = [json.loads(line) for line in source.read_text().splitlines()]
                events[-1]['payload']['workspace_roots'] = []
                source.write_text(''.join(json.dumps(event) + '\n' for event in events))
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
                self.assertNotEqual(result.returncode, 0)
                requests = [json.loads(line) for line in (root / 'requests.jsonl').read_text().splitlines()]
                self.assertFalse(any(request['method'] == 'turn/start' for request in requests))
                started = next(request['params'] for request in requests if request['method'] == 'thread/start')
                self.assertEqual(started['runtimeWorkspaceRoots'], [])
                state = json.loads(runner.runtime_path(receipt, attempt).read_text())
                self.assertTrue(state['writerReleased'])
                self.assertFalse(dispatch.claim(receipt)['may_create'])

    def test_unknown_provider_or_roots_stops_before_server(self):
        for payload_index, field in ((0, 'model_provider'), (1, 'workspace_roots')):
            with self.subTest(field=field):
                root, receipt, attempt, command, env = self.fixture('complete')
                source = root / 'source.jsonl'
                events = [json.loads(line) for line in source.read_text().splitlines()]
                del events[payload_index]['payload'][field]
                source.write_text(''.join(json.dumps(event) + '\n' for event in events))
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / 'requests.jsonl').exists())

    def test_failure_keeps_diagnostics_and_created_identity_after_release(self):
        root, receipt, attempt, command, env = self.fixture('failed')
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 1)
        state = json.loads(runner.runtime_path(receipt, attempt).read_text())
        self.assertTrue(state['writerReleased'])
        self.assertEqual(state['turnError']['message'], 'Synthetic rate limit')
        self.assertEqual(state['turnError']['codexErrorInfo'], 'usageLimitExceeded')
        self.assertIn('Synthetic rate limit', result.stdout)
        self.assertEqual(dispatch.read(receipt)['dispatch_state'], 'created')
        self.assertFalse(dispatch.claim(receipt)['may_create'])
        with (root / 'writer.lock').open() as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_foreign_request_releases_own_client_without_interrupting_foreign_turn(self):
        root, receipt, attempt, command, env = self.fixture('foreign-request')
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 3, result.stderr + result.stdout)
        state = json.loads(runner.runtime_path(receipt, attempt).read_text())
        self.assertTrue(state['writerReleased'])
        self.assertEqual(state['requestThreadId'], 'foreign-thread')
        self.assertEqual(state['requestTurnId'], 'foreign-turn')
        requests = [json.loads(line) for line in (root / 'requests.jsonl').read_text().splitlines()]
        self.assertFalse(any(request['method'] == 'turn/interrupt' for request in requests))
        with (root / 'writer.lock').open() as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_worker_claim_blocks_second_foreground_dispatch(self):
        root, receipt, attempt, command, env = self.fixture('complete')
        runner.runtime_path(receipt, attempt).with_suffix('.worker-claim').write_text('existing worker')
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((root / 'requests.jsonl').exists())
        self.assertFalse(dispatch.claim(receipt)['may_create'])

    def test_receipt_symlink_cannot_bypass_existing_worker_claim(self):
        for detached in (False, True):
            with self.subTest(detached=detached):
                root, receipt, attempt, command, env = self.fixture('complete')
                owner = runner.runtime_path(receipt, attempt).with_suffix('.worker-claim')
                owner.write_text('existing canonical worker')
                alias = root / 'receipt-alias.json'
                alias.symlink_to(receipt)
                command[command.index('--receipt') + 1] = str(alias)
                if detached:
                    command.extend(['--detach', '--startup-timeout', '3'])
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / 'requests.jsonl').exists())
                self.assertEqual(owner.read_text(), 'existing canonical worker')
                self.assertFalse(runner.runtime_path(alias, attempt).with_suffix('.worker-claim').exists())
                self.assertFalse(dispatch.claim(receipt)['may_create'])

    def test_unknown_permission_profile_stops_before_server(self):
        root, receipt, attempt, command, env = self.fixture('complete')
        source = root / 'source.jsonl'
        records = [json.loads(line) for line in source.read_text().splitlines()]
        records[-1]['payload']['active_permission_profile'] = {'id': 'custom-permissions'}
        source.write_text(''.join(json.dumps(r) + '\n' for r in records))
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((root / 'requests.jsonl').exists())

    def test_foreign_source_and_changed_packet_stop_before_server(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                root, receipt, attempt, command, env = self.fixture('complete')
                if foreign:
                    source = root / 'source.jsonl'
                    source.write_text(source.read_text().replace('source-test', 'someone-else'))
                else:
                    (root / 'packet.md').write_text('changed after claim')
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=8)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / 'requests.jsonl').exists())


if __name__ == '__main__':
    unittest.main()

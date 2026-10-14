"""Independent protocol failure injection. Never connects to a real App Server."""
import contextlib
import io
import json
import os
from collections import deque
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import appserver_dispatch as runner
import dispatch
import history
import native_result
import prepare_handoff


class ProtocolFailures(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-protocol-tests'))) / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.plan = {'output_dir': str(self.root / 'outputs'), 'workspace': str(self.root),
                     'source_thread_id': 'source-fixture', 'source_host': 'local',
                     'invocation_id': 'one-invocation', 'project_id': 'project-fixture',
                     'title': 'Fixture continuation', 'summary': 'Edit the authorized existing draft.',
                     'next_action': 'Continue the agreed edit.'}

    def test_native_result_write_denial_blocks_recreation_and_keeps_raw_fixture(self):
        prepared = prepare_handoff.prepare(self.plan)
        result = {'isError': False, 'structuredContent': {'threadId': 'ready-fixture', 'hostId': 'local'}}
        (self.root / 'actual-native-result.json').write_text(json.dumps(result) + '\n')
        before = Path(prepared['receipt']).read_bytes()
        with patch.object(dispatch, 'atomic', side_effect=PermissionError('injected receipt write denied')):
            with self.assertRaisesRegex(PermissionError, 'write denied'):
                native_result.record(prepared['receipt'], prepared['attempt_id'], result)
        self.assertEqual(Path(prepared['receipt']).read_bytes(), before)
        self.assertFalse(dispatch.claim(prepared['receipt'])['may_create'])
        recovered = native_result.record(prepared['receipt'], prepared['attempt_id'], result)
        self.assertEqual(recovered['destination']['threadId'], 'ready-fixture')

    def test_prompt_publish_denial_remains_preclaim_and_reuses_bound_text(self):
        real_publish = history.publish_snapshot
        def denied_prompt(dest, body):
            if str(dest).endswith('.receiver-prompt.txt'):
                raise PermissionError('injected prompt publication denied')
            return real_publish(dest, body)
        with patch.object(history, 'publish_snapshot', side_effect=denied_prompt):
            with self.assertRaisesRegex(PermissionError, 'publication denied'):
                prepare_handoff.prepare(self.plan)
        output = Path(self.plan['output_dir'])
        self.assertFalse(list(output.glob('*.receipt.json')))
        self.assertFalse(list(output.glob('*.request.json')))
        self.assertEqual(len(list(output.glob('*.prompt-integrity.json'))), 1)
        self.assertTrue(prepare_handoff.prepare(self.plan)['may_create'])
        self.assertFalse(prepare_handoff.prepare(self.plan)['may_create'])

    def fixture_runner(self):
        prepared = prepare_handoff.prepare(self.plan)
        receipt = Path(prepared['receipt'])
        source = self.root / 'source.jsonl'
        source.write_text(json.dumps({'type': 'session_meta', 'payload': {
            'id': 'source-fixture', 'model_provider': 'fixture-provider'}}) + '\n' +
            json.dumps({'type': 'turn_context', 'payload': {
                'cwd': str(self.root), 'model': 'fixture-model', 'effort': 'high',
                'approval_policy': 'never', 'approvals_reviewer': 'user',
                'sandbox_policy': {'type': 'workspace-write', 'writable_roots': [str(self.root)]},
                'workspace_roots': [str(self.root)]}}) + '\n')
        argv = ['appserver_dispatch.py', '--receipt', str(receipt),
                '--attempt-id', prepared['attempt_id'], '--packet', prepared['packet'],
                '--project-id', 'project-fixture', '--cwd', str(self.root),
                '--title', self.plan['title'], '--prompt-file', prepared['prompt_file'],
                '--source-rollout', str(source)]
        root = self.root
        requests = []
        class FakeRpc:
            def __init__(self):
                self.notifications = deque()
            def request(self, method, params, timeout=30):
                requests.append({'method': method, 'params': params})
                thread = {'id': 'thread-fixture', 'projectId': 'project-fixture', 'cwd': str(root)}
                if method == 'initialize':
                    return {}
                if method == 'project/list':
                    return {'data': [{'id': 'project-fixture', 'roots': [{'path': str(root)}]}], 'nextCursor': None}
                if method == 'thread/start':
                    return {'thread': thread, 'model': params['model'], 'modelProvider': params['modelProvider'],
                            'reasoningEffort': params['config']['model_reasoning_effort'],
                            'approvalPolicy': params['approvalPolicy'], 'approvalsReviewer': params['approvalsReviewer'],
                            'sandbox': {'type': 'workspaceWrite', 'writableRoots': [str(root)]},
                            'runtimeWorkspaceRoots': params['runtimeWorkspaceRoots']}
                if method == 'turn/start':
                    self.notifications.append({'method': 'turn/completed', 'params': {
                        'threadId': 'thread-fixture', 'turn': {'id': 'turn-fixture', 'status': 'completed'}}})
                    return {'turn': {'id': 'turn-fixture'}}
                if method == 'thread/read':
                    return {'thread': thread}
                if method in ('thread/name/set', 'turn/interrupt'):
                    return {}
                raise AssertionError('Unexpected method ' + method)
            def send(self, message):
                pass
            def close(self):
                requests.append({'method': 'fake-close'})
        return prepared, receipt, argv, FakeRpc, requests

    def test_appserver_created_receipt_directory_sync_failure_preserves_primary_error(self):
        prepared, receipt, argv, FakeRpc, requests = self.fixture_runner()
        real_atomic = dispatch.atomic
        saved_created = []
        def fail_created_after_replace(path, text):
            result = real_atomic(path, text)
            if Path(path) == receipt and json.loads(text).get('dispatch_state') == 'created':
                saved_created.append(receipt.read_bytes())
                raise OSError('injected created receipt directory sync failure')
            return result
        output = io.StringIO()
        error = None
        with patch.object(sys, 'argv', argv), patch.object(runner, 'RpcClient', FakeRpc), \
                patch.object(dispatch, 'atomic', side_effect=fail_created_after_replace), \
                contextlib.redirect_stdout(output):
            try:
                runner.main()
            except Exception as exc:
                error = exc
        (self.root / 'runner-output.txt').write_text(output.getvalue())
        (self.root / 'runner-exception.json').write_text(json.dumps({
            'type': type(error).__name__, 'message': str(error)}, indent=2) + '\n')
        (self.root / 'fake-requests.json').write_text(json.dumps(requests, indent=2) + '\n')
        self.assertEqual(sum(r['method'] == 'thread/start' for r in requests), 1)
        self.assertEqual(sum(r['method'] == 'turn/start' for r in requests), 1)
        self.assertEqual(dispatch.read(receipt)['dispatch_state'], 'created')
        self.assertEqual(receipt.read_bytes(), saved_created[0])
        self.assertFalse(dispatch.claim(receipt)['may_create'])
        self.assertIsInstance(error, OSError)
        self.assertIn('injected created receipt directory sync failure', str(error))
        runtime = json.loads(runner.runtime_path(receipt, prepared['attempt_id']).read_text())
        self.assertEqual(runtime['failureStage'], 'turn_start')
        self.assertIn('directory sync failure', runtime['error'])
        self.assertEqual(runtime['turnId'], 'turn-fixture')
        self.assertTrue(runtime['writerReleased'])

    def test_appserver_secondary_receipt_denial_does_not_hide_project_failure(self):
        prepared, receipt, argv, FakeRpc, requests = self.fixture_runner()
        class ProjectFailureRpc(FakeRpc):
            def request(self, method, params, timeout=30):
                if method == 'project/list':
                    raise RuntimeError('injected primary project verification failure')
                return super().request(method, params, timeout)
        output = io.StringIO()
        error = None
        with patch.object(sys, 'argv', argv), patch.object(runner, 'RpcClient', ProjectFailureRpc), \
                patch.object(dispatch, 'save', side_effect=PermissionError('injected secondary receipt write denied')), \
                contextlib.redirect_stdout(output):
            try:
                runner.main()
            except Exception as exc:
                error = exc
        (self.root / 'runner-output.txt').write_text(output.getvalue())
        (self.root / 'runner-exception.json').write_text(json.dumps({
            'type': type(error).__name__, 'message': str(error)}, indent=2) + '\n')
        self.assertFalse(any(r['method'] == 'thread/start' for r in requests))
        self.assertEqual(dispatch.read(receipt)['dispatch_state'], 'dispatching')
        self.assertFalse(dispatch.claim(receipt)['may_create'])
        self.assertIsInstance(error, RuntimeError)
        self.assertIn('primary project verification failure', str(error))
        runtime = json.loads(runner.runtime_path(receipt, prepared['attempt_id']).read_text())
        self.assertEqual(runtime['failureStage'], 'project_verification')
        self.assertIn('primary project verification failure', runtime['error'])
        self.assertFalse(runtime['creationAttempted'])
        self.assertTrue(runtime['writerReleased'])

    def test_appserver_receipt_and_runtime_denials_keep_primary_error_in_output(self):
        prepared, receipt, argv, FakeRpc, requests = self.fixture_runner()
        class ProjectFailureRpc(FakeRpc):
            def request(self, method, params, timeout=30):
                if method == 'project/list':
                    raise RuntimeError('injected primary project verification failure')
                return super().request(method, params, timeout)
        real_write_runtime = runner.write_runtime
        def deny_failed_runtime(path, state, **fields):
            if state == 'failed':
                raise PermissionError('injected secondary runtime write denied')
            return real_write_runtime(path, state, **fields)
        output = io.StringIO()
        error = None
        with patch.object(sys, 'argv', argv), patch.object(runner, 'RpcClient', ProjectFailureRpc), \
                patch.object(dispatch, 'save', side_effect=PermissionError('injected secondary receipt write denied')), \
                patch.object(runner, 'write_runtime', side_effect=deny_failed_runtime), \
                contextlib.redirect_stdout(output):
            try:
                runner.main()
            except Exception as exc:
                error = exc
        (self.root / 'runner-output.txt').write_text(output.getvalue())
        self.assertIsInstance(error, RuntimeError)
        self.assertIn('primary project verification failure', str(error))
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        primary = next(item for item in messages if item['event'] == 'error')
        self.assertEqual(primary['stage'], 'project_verification')
        self.assertEqual(primary['detail'], str(error))
        self.assertTrue(any(item['event'] == 'receipt_record_error' for item in messages))
        self.assertTrue(any(item['event'] == 'runtime_record_error' for item in messages))
        self.assertFalse(any(r['method'] == 'thread/start' for r in requests))
        self.assertFalse(dispatch.claim(receipt)['may_create'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

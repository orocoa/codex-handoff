import json
import os
from pathlib import Path
import sys
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import dispatch
import native_result
import prepare_handoff


class NativeResult(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-result-tests'))) / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.plan = {'output_dir': str(self.root / 'work' / 'handoffs'),
                     'workspace': str(self.root), 'source_thread_id': 'observed-source',
                     'source_host': 'local', 'invocation_id': 'same-invocation',
                     'project_id': 'observed-project', 'title': 'Test continuation',
                     'summary': 'Existing authorized task.', 'next_action': 'Continue the existing correction.'}
        self.prepared = prepare_handoff.prepare(self.plan)

    def finish(self, response):
        return native_result.record(self.prepared['receipt'], self.prepared['attempt_id'], response)

    def response(self, payload):
        return {'content': [{'type': 'text', 'text': json.dumps(payload)}], 'isError': False}

    def test_ready_destination_is_recorded_without_another_creation_claim(self):
        result = self.finish(self.response({'threadId': 'ready', 'hostId': 'local'}))
        self.assertEqual(result['dispatch_state'], 'created')
        self.assertEqual(result['destination'], {'threadId': 'ready', 'hostId': 'local'})
        self.assertFalse(prepare_handoff.prepare(self.plan)['may_create'])

    def test_client_id_stays_queued(self):
        result = self.finish(self.response({'clientThreadId': 'queued', 'hostId': 'local'}))
        self.assertEqual(result['dispatch_state'], 'queued')
        self.assertNotIn('threadId', result['destination'])
        self.assertFalse(dispatch.claim(Path(self.prepared['receipt']))['may_create'])

    def test_exact_pre_execution_policy_rejection_retains_packet_and_invocation(self):
        packet = Path(self.prepared['packet']).read_bytes()
        result = self.finish({'isError': True, 'content': [{'type': 'text', 'text': native_result.APPROVAL_CONFLICT}]})
        self.assertEqual(result['dispatch_state'], 'failed')
        self.assertEqual(result['reason'], 'approval_policy_conflict')
        self.assertFalse(result['may_create'])  # Recording never authorizes a retry.
        state = dispatch.read(Path(self.prepared['receipt']))
        self.assertEqual(state['invocation_id'], 'same-invocation')
        self.assertEqual(Path(self.prepared['packet']).read_bytes(), packet)
        # A new claim after a separately verified settings change uses one identity.
        retry = prepare_handoff.prepare(self.plan)
        self.assertTrue(retry['may_create'])
        self.assertEqual(retry['packet'], self.prepared['packet'])
        self.assertNotEqual(retry['attempt_id'], self.prepared['attempt_id'])

    def test_unknown_errors_and_denials_never_enable_blind_retry(self):
        for message in ['timeout', 'Auto-review denied this action', 'prefix ' + native_result.APPROVAL_CONFLICT]:
            with self.subTest(message=message):
                self.assertEqual(native_result.classify({'isError': True, 'content': [{'type': 'text', 'text': message}]})['outcome'], 'uncertain')
        result = self.finish({'isError': True, 'content': [{'type': 'text', 'text': 'timeout'}]})
        self.assertEqual(result['dispatch_state'], 'uncertain')
        self.assertFalse(prepare_handoff.prepare(self.plan)['may_create'])

    def test_conflict_phrase_with_destination_is_ambiguous(self):
        response = {'isError': True, 'structuredContent': {'threadId': 'possibly-created'},
                    'content': [{'type': 'text', 'text': native_result.APPROVAL_CONFLICT}]}
        self.assertEqual(self.finish(response)['dispatch_state'], 'uncertain')

    def test_review_denial_keeps_observed_reason_without_authorizing_retry(self):
        message = 'Auto-review denied this action: destination is outside the allowed project'
        result = self.finish({'isError': True, 'content': [{'type': 'text', 'text': message}]})
        self.assertEqual(result['dispatch_state'], 'uncertain')
        self.assertEqual(result['observed_error'], message)
        state = dispatch.read(Path(self.prepared['receipt']))
        self.assertIn(message, state['resolution_note'])
        self.assertFalse(prepare_handoff.prepare(self.plan)['may_create'])

    def test_structured_error_keeps_message_without_calling_it_a_policy_conflict(self):
        response = {'isError': True, 'structuredContent': {'error': {'message': 'Service unavailable'}}}
        result = self.finish(response)
        self.assertEqual(result['reason'], 'creation_result_uncertain')
        self.assertEqual(result['observed_error'], 'Service unavailable')
        self.assertFalse(result['may_create'])

    def test_ready_destination_does_not_label_success_text_as_an_error(self):
        response = {'structuredContent': {'threadId': 'ready', 'hostId': 'local'},
                    'content': [{'type': 'text', 'text': 'Action completed.'}]}
        result = self.finish(response)
        self.assertEqual(result['dispatch_state'], 'created')
        self.assertNotIn('observed_error', result)

    def test_policy_conflict_mixed_with_another_error_is_uncertain(self):
        response = {'isError': True, 'content': [
            {'type': 'text', 'text': native_result.APPROVAL_CONFLICT},
            {'type': 'text', 'text': 'A later creation response timed out'}]}
        self.assertEqual(self.finish(response)['dispatch_state'], 'uncertain')

    def test_disagreeing_payloads_cannot_select_a_destination(self):
        response = self.response({'threadId': 'one'})
        response['structuredContent'] = {'threadId': 'two'}
        self.assertEqual(self.finish(response)['dispatch_state'], 'uncertain')

    def test_malformed_results_are_uncertain(self):
        for response in [None, {}, {'threadId': ''}, {'threadId': 3}, {'threadId': 'one', 'isError': 'false'},
                         {'threadId': 'one', 'error': 'failed'}, {'hostId': 'local'}]:
            with self.subTest(response=response):
                self.assertEqual(native_result.classify(response)['outcome'], 'uncertain')

    def test_stale_attempt_cannot_change_receipt(self):
        before = Path(self.prepared['receipt']).read_bytes()
        with self.assertRaisesRegex(ValueError, 'Stale'):
            native_result.record(self.prepared['receipt'], 'other-attempt', self.response({'threadId': 'one'}))
        self.assertEqual(Path(self.prepared['receipt']).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

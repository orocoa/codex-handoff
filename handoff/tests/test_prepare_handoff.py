import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import dispatch
import prepare_handoff


class FastPreparation(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-fast-tests'))) / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.plan = {'output_dir': str(self.root / 'outputs' / 'handoffs'),
                     'workspace': str(self.root), 'source_thread_id': 'source-task',
                     'source_host': 'local', 'invocation_id': 'one-user-request',
                     'project_id': 'verified-project', 'title': 'Existing task continuation',
                     'summary': 'Goal: revise existing draft. User approved editing only. Draft remains in place.',
                     'next_action': 'Read the existing draft and apply the agreed correction.'}

    def test_batch_publishes_history_and_claim_before_create(self):
        r = prepare_handoff.prepare(self.plan)
        self.assertTrue(r['may_create'])
        receipt = dispatch.read(Path(r['receipt']))
        self.assertEqual(receipt['dispatch_state'], 'dispatching')
        packet = Path(r['packet'])
        history = json.loads((packet.parent / 'history' / 'catalog.json').read_text())
        self.assertEqual(len(history['entries']), 1)
        self.assertEqual(history['entries'][0]['sha256'], receipt['packet_sha256'])
        self.assertEqual(Path(history['entries'][0]['snapshot']).read_bytes(), packet.read_bytes())
        self.assertEqual(r['target'], {'type': 'project', 'projectId': 'verified-project',
                                      'environment': {'type': 'local'}})
        self.assertEqual(Path(r['prompt_file']).read_text(), r['prompt'])
        self.assertEqual(receipt['source_workspace'], str(self.root))

    def test_retry_retains_one_attempt_and_history_entry(self):
        first = prepare_handoff.prepare(self.plan)
        retry = prepare_handoff.prepare(self.plan)
        self.assertFalse(retry['may_create'])
        self.assertEqual(first['attempt_id'], retry['attempt_id'])
        self.assertEqual(first['packet'], retry['packet'])
        catalog = Path(first['packet']).parent / 'history' / 'catalog.json'
        self.assertEqual(len(json.loads(catalog.read_text())['entries']), 1)

    def test_noninteractive_preflight_saves_without_claim_and_recovers_same_request(self):
        blocked = prepare_handoff.prepare(self.plan, approval_policy='never')
        self.assertFalse(blocked['may_create'])
        self.assertEqual(blocked['dispatch_state'], 'prepared')
        self.assertIsNone(blocked['attempt_id'])
        self.assertEqual(blocked['blocker'], 'effective_approval_policy_never')
        original = Path(blocked['packet']).read_bytes()
        again = prepare_handoff.prepare(self.plan, approval_policy='never')
        self.assertIsNone(again['attempt_id'])
        allowed = prepare_handoff.prepare(self.plan, approval_policy='on-request')
        self.assertTrue(allowed['may_create'])
        self.assertEqual(allowed['packet'], blocked['packet'])
        self.assertEqual(Path(allowed['packet']).read_bytes(), original)
        self.assertFalse(prepare_handoff.prepare(self.plan, approval_policy='on-request')['may_create'])

    def test_noninteractive_preflight_does_not_change_an_existing_destination(self):
        first = prepare_handoff.prepare(self.plan, approval_policy='on-request')
        dispatch.finish(Path(first['receipt']), first['attempt_id'], 'created', thread_id='existing-successor')
        again = prepare_handoff.prepare(self.plan, approval_policy='never')
        self.assertFalse(again['may_create'])
        self.assertEqual(again['dispatch_state'], 'created')
        self.assertEqual(again['destination']['threadId'], 'existing-successor')
        self.assertNotIn('blocker', again)

    def test_changed_input_does_not_replace_claimed_packet(self):
        first = prepare_handoff.prepare(self.plan)
        original = Path(first['packet']).read_bytes()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            prepare_handoff.prepare(dict(self.plan, summary='Different decisions'))
        self.assertEqual(Path(first['packet']).read_bytes(), original)
        self.assertEqual(dispatch.read(Path(first['receipt']))['attempt_id'], first['attempt_id'])

    def test_uncertain_result_cannot_be_recreated(self):
        first = prepare_handoff.prepare(self.plan)
        dispatch.finish(Path(first['receipt']), first['attempt_id'], 'uncertain', note='response lost')
        again = prepare_handoff.prepare(self.plan)
        self.assertFalse(again['may_create'])
        self.assertEqual(again['dispatch_state'], 'uncertain')

    def test_concurrent_preparers_get_one_creation_claim(self):
        def run(_):
            p = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_handoff.py')],
                               input=json.dumps(self.plan), capture_output=True, text=True, timeout=10)
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        self.assertEqual(sum(r['may_create'] for r in results), 1)
        self.assertEqual(len({r['attempt_id'] for r in results}), 1)

    def test_manual_history_conflict_preserves_files_and_does_not_claim(self):
        archive = self.root / 'existing-history'
        archive.mkdir()
        index = archive / 'INDEX.md'
        index.write_text('User-maintained history')
        with self.assertRaisesRegex(ValueError, 'not generated'):
            prepare_handoff.prepare(dict(self.plan, history_dir=str(archive)))
        self.assertEqual(index.read_text(), 'User-maintained history')
        self.assertFalse(list(Path(self.plan['output_dir']).glob('*.receipt.json')))
        self.assertFalse(list(Path(self.plan['output_dir']).glob('*.request.json')))
        repaired = prepare_handoff.prepare(dict(self.plan, history_dir=str(self.root / 'new-history')))
        self.assertTrue(repaired['may_create'])
        self.assertEqual(index.read_text(), 'User-maintained history')

    def test_outside_workspace_and_remote_host_rejected(self):
        for changes in ({'output_dir': str(self.root.parent)}, {'history_dir': str(self.root.parent)},
                        {'source_host': 'remote'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare_handoff.prepare(dict(self.plan, **changes))
        self.assertFalse(Path(self.plan['output_dir']).exists())

    def test_large_summary_preserved_instead_of_truncated(self):
        summary = 'Required detail and constraints. ' * 100
        r = prepare_handoff.prepare(dict(self.plan, summary=summary))
        self.assertIn(summary.strip(), Path(r['packet']).read_text())
        self.assertTrue(r['size_note'])


    def test_nested_source_preserves_distinct_destination(self):
        source = self.root / 'packages' / 'feature'
        source.mkdir(parents=True)
        plan = dict(self.plan, workspace=str(source), destination_workspace=str(self.root))
        r = prepare_handoff.prepare(plan)
        receipt = dispatch.read(Path(r['receipt']))
        self.assertEqual(receipt['source_workspace'], str(source))
        self.assertEqual(receipt['destination_workspace'], str(self.root))
        self.assertIn('接收 cwd：' + str(self.root) + '。', r['prompt'])
        self.assertIn(str(source), Path(r['packet']).read_text())
        self.assertEqual(r['create_args']['target'], r['target'])

    def test_destination_outside_source_project_rejected(self):
        other = self.root / 'other'
        other.mkdir()
        with self.assertRaisesRegex(ValueError, 'outside'):
            prepare_handoff.prepare(dict(self.plan, destination_workspace=str(other)))

    def test_model_overrides_only_appear_when_supplied(self):
        default = prepare_handoff.prepare(self.plan)
        self.assertNotIn('model', default['create_args'])
        self.assertNotIn('thinking', default['create_args'])
        explicit = prepare_handoff.prepare(dict(self.plan, invocation_id='explicit-model',
                                               model='gpt-6-astra', thinking='ultra'))
        self.assertEqual(explicit['create_args']['model'], 'gpt-6-astra')
        self.assertEqual(explicit['create_args']['thinking'], 'ultra')

    def test_same_input_keeps_saved_receiver_prompt_on_upgrade(self):
        # A saved prompt is part of an existing invocation, independent of the
        # currently installed renderer. New wording must not overwrite it.
        first = prepare_handoff.prepare(self.plan)
        original_prompt = Path(first['prompt_file']).read_bytes()
        retry = prepare_handoff.prepare(self.plan)
        self.assertFalse(retry['may_create'])
        self.assertEqual(retry['prompt'].encode(), original_prompt)
        self.assertEqual(Path(first['prompt_file']).read_bytes(), original_prompt)

    def test_history_failure_does_not_freeze_request_or_allow_claim(self):
        with patch.object(prepare_handoff.history, 'publish', side_effect=OSError('injected history failure')):
            with self.assertRaises(OSError):
                prepare_handoff.prepare(self.plan)
        output = Path(self.plan['output_dir'])
        self.assertFalse(list(output.glob('*.request.json')))
        self.assertFalse(list(output.glob('*.receipt.json')))
        self.assertTrue(prepare_handoff.prepare(dict(self.plan, history_dir=str(self.root / 'alternative')))['may_create'])

    def test_unchanged_retry_repairs_missing_history_index(self):
        original_atomic = prepare_handoff.history.atomic
        def fail_index(path, text):
            if path.name == 'INDEX.md':
                raise OSError('injected index failure')
            return original_atomic(path, text)
        with patch.object(prepare_handoff.history, 'atomic', side_effect=fail_index):
            with self.assertRaises(OSError):
                prepare_handoff.prepare(self.plan)
        index = Path(self.plan['output_dir']) / 'history' / 'INDEX.md'
        self.assertFalse(index.exists())
        retry = prepare_handoff.prepare(self.plan)
        self.assertTrue(retry['may_create'])
        self.assertTrue(index.is_file())
        self.assertFalse(prepare_handoff.prepare(self.plan)['may_create'])

    def test_compact_cli_keeps_creation_args_without_duplicate_prompt(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_handoff.py'), '--compact'],
                                input=json.dumps(self.plan), capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertTrue(data['may_create'])
        self.assertNotIn('prompt', data)
        self.assertNotIn('target', data)
        self.assertEqual(data['create_args']['prompt'], Path(data['prompt_file']).read_text())
        self.assertEqual(data['create_args']['target']['projectId'], self.plan['project_id'])

    def test_unfrozen_retry_reuses_prompt_only_after_matching_packet(self):
        output = Path(self.plan['output_dir'])
        with patch.object(prepare_handoff.history, 'publish', side_effect=OSError('history unavailable')):
            with self.assertRaises(OSError):
                prepare_handoff.prepare(self.plan)
        prompt_file = next(output.glob('*.receiver-prompt.txt'))
        saved = prompt_file.read_text()
        self.assertFalse(list(output.glob('*.request.json')))
        # A future renderer changes wording, while old evidence stays in place.
        with patch.object(prepare_handoff, 'receiver_prompt', return_value='Future renderer wording'):
            repaired = prepare_handoff.prepare(self.plan)
        self.assertEqual(repaired['prompt'], saved)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            prepare_handoff.prepare(dict(self.plan, summary='Different goal'))


if __name__ == '__main__':
    unittest.main()

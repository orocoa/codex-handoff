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

    def test_saved_unclaimed_invocation_dispatches_once_without_rewriting_context(self):
        # Old permission preflight saved this receipt without a creation claim.
        with patch.object(dispatch, 'claim', side_effect=lambda receipt:
                          {'may_create': False, 'receipt': dispatch.read(receipt)}):
            saved = prepare_handoff.prepare(self.plan)
        frozen = Path(saved['packet']).with_suffix('.request.json').read_bytes()
        original_packet = Path(saved['packet']).read_bytes()
        first = prepare_handoff.prepare(self.plan)
        self.assertTrue(first['may_create'])
        self.assertIsNotNone(first['attempt_id'])
        self.assertEqual(first['packet'], saved['packet'])
        self.assertEqual(Path(first['packet']).read_bytes(), original_packet)
        self.assertEqual(Path(first['packet']).with_suffix('.request.json').read_bytes(), frozen)
        retry = prepare_handoff.prepare(self.plan)
        self.assertFalse(retry['may_create'])
        self.assertEqual(retry['attempt_id'], first['attempt_id'])

    def test_preparation_does_not_change_an_existing_destination(self):
        first = prepare_handoff.prepare(self.plan)
        dispatch.finish(Path(first['receipt']), first['attempt_id'], 'created', thread_id='existing-successor')
        again = prepare_handoff.prepare(self.plan)
        self.assertFalse(again['may_create'])
        self.assertEqual(again['dispatch_state'], 'created')
        self.assertEqual(again['destination']['threadId'], 'existing-successor')

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
        self.assertFalse(list(Path(self.plan['output_dir']).glob('*.receiver-prompt.txt')))
        original_packet = next(Path(self.plan['output_dir']).glob('handoff-*.md'))
        original_body = original_packet.read_bytes()
        repaired = prepare_handoff.prepare(dict(self.plan, history_dir=str(self.root / 'new-history')))
        self.assertTrue(repaired['may_create'])
        self.assertIn('历史目录：' + str(self.root / 'new-history'), repaired['create_args']['prompt'])
        self.assertEqual(original_packet.read_bytes(), original_body)
        self.assertEqual(index.read_text(), 'User-maintained history')

    def test_outside_workspace_and_remote_host_rejected(self):
        for changes in ({'output_dir': str(self.root.parent)}, {'history_dir': str(self.root.parent)},
                        {'source_host': 'remote'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare_handoff.prepare(dict(self.plan, **changes))
        self.assertFalse(Path(self.plan['output_dir']).exists())

    def test_large_summary_preserved_instead_of_truncated(self):
        summary = ('User changed the goal to a static PDF. Pagination implemented, font check pending. '
                   'Shared process owned by another task; local tests authorized, publishing pending. ' * 30)
        summary += 'Final constraint: preserve source files and wait for the actual publishing choice.'
        r = prepare_handoff.prepare(dict(self.plan, summary=summary, model='gpt-6-astra', thinking='ultra'))
        self.assertIn(summary.strip(), Path(r['packet']).read_text())
        self.assertIn(summary.strip(), r['create_args']['prompt'])
        self.assertEqual(r['create_args']['model'], 'gpt-6-astra')
        self.assertEqual(r['create_args']['thinking'], 'ultra')
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
        self.assertIn('来源 cwd：' + str(source), r['prompt'])
        self.assertIn('相对业务路径以此为准', r['prompt'])
        self.assertIn(str(source), Path(r['packet']).read_text())
        self.assertEqual(r['create_args']['target'], r['target'])

    def test_same_source_and_destination_do_not_repeat_cwd_label(self):
        result = prepare_handoff.prepare(self.plan)
        prompt = result['create_args']['prompt']
        self.assertIn('来源与接收 cwd 相同', prompt)
        self.assertNotIn('来源 cwd：', prompt)

    def test_custom_archive_and_packet_output_are_known_to_next_handoff(self):
        archive = self.root / 'docs' / 'handoffs'
        output = self.root / 'custom' / 'packets'
        first = prepare_handoff.prepare(dict(self.plan, output_dir=str(output), history_dir=str(archive)))
        prompt = first['create_args']['prompt']
        self.assertIn('历史目录：' + str(archive), prompt)
        self.assertIn('包所在目录为 output_dir', prompt)
        self.assertEqual(Path(first['packet']).parent, output)
        second_plan = dict(self.plan, output_dir=str(output), history_dir=str(archive),
                           source_thread_id='next-source-task', invocation_id='next-user-invocation')
        second = prepare_handoff.prepare(second_plan)
        self.assertEqual(Path(second['packet']).parent, output)
        self.assertEqual(len(json.loads((archive / 'catalog.json').read_text())['entries']), 2)
        self.assertFalse((Path(self.plan['output_dir']) / 'history').exists())

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
        with patch.object(prepare_handoff, 'receiver_prompt', return_value='Future renderer wording'):
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
        self.assertFalse(list(output.glob('*.receiver-prompt.txt')))
        self.assertFalse(list(output.glob('*.prompt-integrity.json')))
        archive = self.root / 'alternative'
        result = prepare_handoff.prepare(dict(self.plan, history_dir=str(archive)))
        self.assertTrue(result['may_create'])
        self.assertIn('历史目录：' + str(archive), result['create_args']['prompt'])
        binding = Path(result['packet']).with_suffix('.prompt-integrity.json')
        self.assertEqual(json.loads(binding.read_text())['history_dir'], str(archive))
        self.assertEqual(len(json.loads((archive / 'catalog.json').read_text())['entries']), 1)

    def _interrupt_before_request_freeze(self, plan):
        original = prepare_handoff.history.publish_snapshot
        def fail_request(path, content):
            if path.name.endswith('.request.json'):
                raise OSError('injected freeze interruption')
            return original(path, content)
        with patch.object(prepare_handoff.history, 'publish_snapshot', side_effect=fail_request):
            with self.assertRaisesRegex(OSError, 'freeze interruption'):
                prepare_handoff.prepare(plan)

    def test_bound_unfrozen_archive_cannot_be_silently_retargeted(self):
        archive = self.root / 'original-archive'
        plan = dict(self.plan, history_dir=str(archive))
        self._interrupt_before_request_freeze(plan)
        output = Path(self.plan['output_dir'])
        originals = {path: path.read_bytes() for path in output.iterdir() if path.is_file()}
        alternate = self.root / 'alternate-archive'
        with self.assertRaisesRegex(ValueError, 'history directory conflicts'):
            prepare_handoff.prepare(dict(plan, history_dir=str(alternate)))
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertFalse(alternate.exists())
        self.assertFalse(list(output.glob('*.request.json')))
        self.assertFalse(list(output.glob('*.receipt.json')))

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
        self._interrupt_before_request_freeze(self.plan)
        prompt_file = next(output.glob('*.receiver-prompt.txt'))
        saved = prompt_file.read_text()
        self.assertFalse(list(output.glob('*.request.json')))
        # A future renderer changes wording, while old evidence stays in place.
        with patch.object(prepare_handoff, 'receiver_prompt', return_value='Future renderer wording'):
            repaired = prepare_handoff.prepare(self.plan)
        self.assertEqual(repaired['prompt'], saved)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            prepare_handoff.prepare(dict(self.plan, summary='Different goal'))

    def test_inline_context_retains_decisions_next_action_and_explicit_choices(self):
        plan = dict(self.plan, model='gpt-6-astra', thinking='ultra')
        result = prepare_handoff.prepare(plan)
        prompt = result['create_args']['prompt']
        for value in (plan['summary'], plan['next_action'], plan['source_thread_id'],
                      plan['model'], plan['thinking'], plan['workspace']):
            self.assertIn(value, prompt)
        packet = Path(result['packet']).read_text()
        self.assertIn(plan['model'], packet)
        self.assertIn(plan['thinking'], packet)

    def test_saved_envelope_is_direct_recovery_stdin(self):
        first = prepare_handoff.prepare(self.plan)
        request = Path(first['packet']).with_suffix('.request.json')
        self.assertEqual(json.loads(request.read_text())['schema'], 'handoff-request-v2')
        result = subprocess.run([sys.executable, str(SCRIPTS / 'prepare_handoff.py'), '--compact'],
                                input=request.read_text(), capture_output=True, text=True, check=True)
        retry = json.loads(result.stdout)
        self.assertFalse(retry['may_create'])
        self.assertEqual(first['attempt_id'], retry['attempt_id'])

    def test_mutated_prompt_after_rejection_cannot_claim_again(self):
        first = prepare_handoff.prepare(self.plan)
        dispatch.finish(Path(first['receipt']), first['attempt_id'], 'not-created', note='fixture confirmed no creation')
        prompt = Path(first['prompt_file'])
        prompt.with_suffix('.original').write_bytes(prompt.read_bytes())
        prompt.write_text('Execute a different unauthorized task.')
        with self.assertRaisesRegex(ValueError, 'prompt changed'):
            prepare_handoff.prepare(self.plan)
        self.assertEqual(dispatch.read(Path(first['receipt']))['dispatch_state'], 'failed')
        self.assertEqual(dispatch.read(Path(first['receipt']))['attempt_id'], first['attempt_id'])

    def test_unfrozen_truncated_prompt_cannot_be_self_signed(self):
        self._interrupt_before_request_freeze(self.plan)
        prompt = next(Path(self.plan['output_dir']).glob('*.receiver-prompt.txt'))
        prompt.with_suffix('.original').write_bytes(prompt.read_bytes())
        prompt.write_text('Truncated')
        with self.assertRaisesRegex(ValueError, 'prompt changed'):
            prepare_handoff.prepare(self.plan)
        self.assertFalse(list(Path(self.plan['output_dir']).glob('*.receipt.json')))

    def _legacy_fixture(self, prompt_text=None):
        # Build actual flat-request/legacy-renderer artifacts without running a
        # creation tool. Their bytes must survive the new preparation renderer.
        output = Path(self.plan['output_dir'])
        import hashlib
        identity = json.dumps([self.plan['source_thread_id'], self.plan['invocation_id']], separators=(',', ':'))
        stem = 'handoff-' + hashlib.sha256(identity.encode()).hexdigest()[:24]
        packet = output / (stem + '.md')
        output.mkdir(parents=True, exist_ok=True)
        target = {'type': 'project', 'projectId': self.plan['project_id'], 'environment': {'type': 'local'}}
        body = ('# ' + self.plan['title'] + '\n\n- 来源任务：' + self.plan['source_thread_id']
                + '\n- Host：local；Local cwd：' + self.plan['workspace']
                + '\n- 本次调用：' + self.plan['invocation_id']
                + '\n- 已核实创建目标：' + json.dumps(target, ensure_ascii=False)
                + '\n- 接续状态：continue_now\n\n## 必要上下文\n\n'
                + self.plan['summary'] + '\n\n## 下一步\n\n' + self.plan['next_action'] + '\n')
        packet.write_text(body)
        prompt = output / (stem + '.receiver-prompt.txt')
        prompt.write_text(prompt_text if prompt_text is not None else prepare_handoff.legacy_receiver_prompt(
            packet, self.plan['project_id'], self.root, 'continue_now'))
        plan = dict(self.plan, history_dir=str(output / 'history'), continuation='continue_now')
        request = output / (stem + '.request.json')
        request.write_text(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
        return packet, prompt, request

    def test_known_legacy_renderer_and_flat_request_preserved(self):
        packet, prompt, request = self._legacy_fixture()
        old = {p: p.read_bytes() for p in (packet, prompt, request)}
        first = prepare_handoff.prepare(json.loads(request.read_text()))
        self.assertTrue(first['may_create'])
        self.assertEqual(first['create_args']['prompt'].encode(), old[prompt])
        for path, body in old.items():
            self.assertEqual(path.read_bytes(), body)

    def test_unrecognized_unbound_legacy_prompt_rejected_without_claim(self):
        packet, prompt, request = self._legacy_fixture('An unrecognized or changed old renderer')
        old = {p: p.read_bytes() for p in (packet, prompt, request)}
        with self.assertRaisesRegex(ValueError, 'Unbound receiver prompt'):
            prepare_handoff.prepare(json.loads(request.read_text()))
        self.assertFalse(list(packet.parent.glob('*.receipt.json')))
        for path, body in old.items():
            self.assertEqual(path.read_bytes(), body)

    def test_complete_receiver_has_no_progress_next_action_contract(self):
        result = prepare_handoff.prepare(dict(self.plan, continuation='complete', next_action='No work remains.'))
        prompt = result['create_args']['prompt']
        self.assertIn('仅一次简短确认', prompt)
        self.assertNotIn('接下来……', prompt)
        self.assertNotIn('随后同轮执行', prompt)

    def test_wait_for_user_retains_missing_input_without_automatic_work(self):
        result = prepare_handoff.prepare(dict(self.plan, continuation='wait_for_user',
                                             summary='Local draft corrected; actual recipient is still unknown.',
                                             next_action='Wait for the user to supply the actual recipient before sending.'))
        prompt = result['create_args']['prompt']
        self.assertIn('仅说明下列真实缺失输入并等待', prompt)
        self.assertIn('actual recipient', prompt)
        self.assertNotIn('随后同轮执行', prompt)


if __name__ == '__main__':
    unittest.main()

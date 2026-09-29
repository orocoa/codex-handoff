import concurrent.futures
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'context_check.py'
SPEC = importlib.util.spec_from_file_location('cached_context_check', SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def compact(number):
    return {'type': 'compacted', 'payload': {'window_id': 'window-' + str(number),
                                            'message': 'private-message-not-for-cache'}}


def encoded(rows):
    return b''.join((json.dumps(row) + '\n').encode() for row in rows)


class CachedContext(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'context-cache-tests'))) / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.log = self.root / 'synthetic.jsonl'
        self.state = self.root / 'state'
        self.thread = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        self.cache_threshold = patch.object(M, 'CACHE_MIN_BYTES', 0)
        self.cache_threshold.start()
        self.addCleanup(self.cache_threshold.stop)

    def count(self, claim=False):
        return M.advisory(self.log, self.thread, state_dir=self.state, claim=claim)

    def cache(self):
        return next(self.state.glob('*.scan'))

    def jsonl_decodes(self, fn):
        original = json.loads
        lines = []
        def tracked(value, *args, **kwargs):
            if isinstance(value, bytes):
                lines.append(value)
            return original(value, *args, **kwargs)
        with patch.object(M.json, 'loads', tracked):
            result = fn()
        return result, lines

    def test_below_threshold_cached_and_unchanged_skips_jsonl_decoding_and_write(self):
        self.log.write_bytes(encoded([compact(1)]))
        self.assertFalse(self.count()['remind'])
        self.assertTrue(self.cache().exists())
        with patch.object(M, '_atomic_json', side_effect=AssertionError('unchanged cache rewritten')):
            result, lines = self.jsonl_decodes(self.count)
        self.assertEqual(result['observed_compactions'], 1)
        self.assertEqual(lines, [])
        self.assertNotIn('private-message-not-for-cache', self.cache().read_text())
        self.assertNotIn('window-1', self.cache().read_text())

    def test_append_decodes_only_new_complete_lines_and_keeps_cross_segment_dedupe(self):
        no_id = {'type': 'compacted', 'payload': {'message': 'fallback key'}}
        ordinal = {'type': 'compacted', 'ordinal': 7, 'payload': {'message': 'ordinal'}}
        self.log.write_bytes(encoded([compact(1), no_id, ordinal]))
        self.count()
        rows = [compact(1), no_id, ordinal, compact(2),
                {'type': 'event_msg', 'payload': {'type': 'ContextCompaction'}},
                {'type': 'response_item', 'payload': {'text': 'compacted'}}]
        with self.log.open('ab') as stream:
            stream.write(encoded(rows))
        result, lines = self.jsonl_decodes(self.count)
        self.assertEqual(len(lines), len(rows))
        self.assertEqual(result['observed_compactions'], 4)
        self.assertEqual(M.count_compactions(self.log), (4, 0, False))

    def test_canonical_id_priority_and_string_coercion_survive_cache_boundary(self):
        rows = [{'type': 'compacted', 'payload': {'compaction_response_id': 'preferred', 'window_id': 'one'}},
                {'type': 'compacted', 'payload': {'compaction_response_id': 'preferred', 'window_id': 'two'}},
                {'type': 'compacted', 'payload': {'window_id': 1}},
                {'type': 'compacted', 'payload': {'window_id': '1'}},
                {'type': 'compacted', 'payload': {'window_id': '\ud800'}},
                {'type': 'compacted', 'payload': {'window_id': {'secret': 'id-content-not-for-cache'}}}]
        self.log.write_bytes(encoded(rows))
        self.assertEqual(self.count()['observed_compactions'], 4)
        with self.log.open('ab') as stream:
            stream.write(encoded(rows))
        self.assertEqual(self.count()['observed_compactions'], 4)
        self.assertNotIn('id-content-not-for-cache', self.cache().read_text())

    def test_partial_tail_is_retried_after_newline_and_malformed_is_not_double_counted(self):
        partial = json.dumps(compact(2)).encode()
        self.log.write_bytes(encoded([compact(1)]) + b'bad-json\n' + partial[:20])
        first = self.count()
        self.assertTrue(first['partial_tail'])
        self.assertEqual(first['malformed_lines'], 1)
        self.assertEqual(self.count()['malformed_lines'], 1)
        with self.log.open('ab') as stream:
            stream.write(partial[20:] + b'\n' + encoded([{'type': 'compacted', 'payload': []}]))
        result, lines = self.jsonl_decodes(self.count)
        self.assertEqual(len(lines), 2)
        self.assertEqual(result['observed_compactions'], 2)
        self.assertEqual(result['malformed_lines'], 2)
        self.assertFalse(result['partial_tail'])
        self.assertEqual(result['status'], 'partial')

    def test_same_size_in_place_rewrite_with_restored_mtime_invalidates_prefix(self):
        first, changed = encoded([compact(1), compact(2)]), encoded([compact(1), compact(1)])
        self.assertEqual(len(first), len(changed))
        self.log.write_bytes(first)
        self.count()
        previous = self.log.stat()
        self.log.write_bytes(changed)
        os.utime(self.log, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        result, lines = self.jsonl_decodes(self.count)
        self.assertEqual(result['observed_compactions'], 1)
        self.assertEqual(len(lines), 2)

    def test_prefix_rewrite_plus_append_does_not_reuse_old_seen(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        self.count()
        self.log.write_bytes(encoded([compact(1), compact(1), compact(3)]))
        result = self.count()
        self.assertEqual(result['observed_compactions'], 2)

    def test_replacement_and_truncation_rescan(self):
        self.log.write_bytes(encoded([compact(1), compact(2), compact(3)]))
        self.count()
        replacement = self.root / 'replacement.jsonl'
        replacement.write_bytes(encoded([compact(4), compact(5)]))
        os.replace(replacement, self.log)
        result, lines = self.jsonl_decodes(self.count)
        self.assertEqual(result['observed_compactions'], 2)
        self.assertEqual(len(lines), 2)
        self.log.write_bytes(encoded([compact(4)]))
        self.assertEqual(self.count()['observed_compactions'], 1)

    def test_corrupt_or_incompatible_cache_falls_back(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        self.count()
        cache = self.cache()
        valid = json.loads(cache.read_text())
        malformed_checksum = dict(valid, seen=[])
        invalid_schema = dict(valid, schema='unknown')
        invalid_schema.pop('checksum')
        invalid_schema['checksum'] = M._checksum(invalid_schema)
        invalid_offset = dict(valid, offset=True)
        invalid_offset.pop('checksum')
        invalid_offset['checksum'] = M._checksum(invalid_offset)
        for raw in ('{broken', '[]', json.dumps(malformed_checksum), json.dumps(invalid_schema), json.dumps(invalid_offset)):
            with self.subTest(raw=raw[:80]):
                cache.write_text(raw)
                result, lines = self.jsonl_decodes(self.count)
                self.assertEqual(result['observed_compactions'], 2)
                self.assertEqual(len(lines), 2)

    def test_busy_cache_lock_falls_back_without_waiting(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        self.count()
        with next(self.state.glob('*.scan.lock')).open('a+') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, lines = self.jsonl_decodes(self.count)
        self.assertEqual(result['observed_compactions'], 2)
        self.assertEqual(len(lines), 2)

    def test_unwritable_state_still_counts_and_reminds(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        with patch.object(M, '_private_lock', side_effect=PermissionError('synthetic read-only state')):
            result = self.count(claim=True)
        self.assertEqual(result['observed_compactions'], 2)
        self.assertTrue(result['remind'])

    def test_cache_write_failure_does_not_break_notice_deduplication(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        original = M._atomic_json
        def fail_cache(path, data):
            if path.suffix == '.scan':
                raise OSError('synthetic cache failure')
            return original(path, data)
        with patch.object(M, '_atomic_json', fail_cache):
            self.assertTrue(self.count(claim=True)['remind'])
            self.assertFalse(self.count(claim=True)['remind'])
        self.assertFalse(list(self.state.glob('*.scan')))

    def test_permission_repair_failure_does_not_repeat_recorded_notice(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        self.assertTrue(self.count(claim=True)['remind'])
        with patch.object(M.os, 'chmod', side_effect=PermissionError('synthetic chmod failure')):
            self.assertFalse(self.count(claim=True)['remind'])

    def test_concurrent_callers_have_one_notice_and_valid_private_state(self):
        # Subprocesses use the real 4 MiB threshold, unlike in-process unit tests.
        ordinary = encoded([{'type': 'response_item', 'payload': {'text': 'x' * 1000}}])
        self.log.write_bytes(encoded([compact(1), compact(2)])
                             + ordinary * ((4 * 1024 * 1024) // len(ordinary) + 1))
        command = [sys.executable, str(SCRIPT), '--thread', self.thread, '--transcript', str(self.log),
                   '--state-dir', str(self.state), '--claim-notice']
        def run(number):
            result = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            (self.root / ('caller-%d.json' % number)).write_text(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        old = os.umask(0)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(run, range(4)))
        finally:
            os.umask(old)
        self.assertEqual(sum(row['remind'] for row in results), 1)
        self.assertTrue(all(row['observed_compactions'] == 2 for row in results))
        self.assertIsNotNone(M._read_cache(self.cache()))
        for path in self.state.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, str(path))

    def test_notice_replace_failure_retains_previous_receipt(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        self.assertTrue(self.count(claim=True)['remind'])
        receipt = next(self.state.glob('*.json'))
        original_receipt = receipt.read_bytes()
        with self.log.open('ab') as stream:
            stream.write(encoded([compact(3), compact(4)]))
        replace = os.replace
        def fail_notice(source, destination):
            if Path(destination).suffix == '.json':
                raise OSError('synthetic rename failure')
            return replace(source, destination)
        with patch.object(M.os, 'replace', fail_notice):
            result = self.count(claim=True)
        self.assertTrue(result['remind'])
        self.assertEqual(receipt.read_bytes(), original_receipt)
        self.assertTrue(self.count(claim=True)['remind'])
        self.assertFalse(self.count(claim=True)['remind'])

    def test_transcript_changed_during_scan_does_not_publish_torn_cache(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        self.count()
        original = M._scan
        calls = []
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            if not calls:
                calls.append(True)
                self.log.write_bytes(encoded([compact(1), compact(1)]))
            return result
        with patch.object(M, '_scan', changed), patch.object(M, '_atomic_json', side_effect=AssertionError('unstable cache published')):
            self.assertEqual(self.count()['observed_compactions'], 1)
        self.assertEqual(self.count()['observed_compactions'], 1)

    def test_explicit_transcript_without_state_or_claim_remains_read_only(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        codex_home = self.root / 'unused-codex-home'
        result = subprocess.run([sys.executable, str(SCRIPT), '--thread', self.thread,
                                 '--transcript', str(self.log), '--codex-home', str(codex_home)],
                                capture_output=True, text=True, timeout=10,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['observed_compactions'], 2)
        self.assertFalse(codex_home.exists())

    def test_small_log_skips_cache_and_scan_lock_but_preserves_notice_dedupe(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        with patch.object(M, 'CACHE_MIN_BYTES', 4 * 1024 * 1024), patch.object(
                M, '_cached_count', side_effect=AssertionError('small log used cache')):
            self.assertTrue(self.count(claim=True)['remind'])
            self.assertFalse(self.count(claim=True)['remind'])
        self.assertFalse(list(self.state.glob('*.scan')))
        self.assertFalse(list(self.state.glob('*.scan.lock')))

    def test_truncated_small_log_does_not_use_or_delete_existing_cache(self):
        self.log.write_bytes(encoded([compact(1), compact(2)]))
        self.count()
        cache = self.cache()
        old_bytes, old_stat = cache.read_bytes(), cache.stat()
        self.log.write_bytes(encoded([compact(1)]))
        with patch.object(M, 'CACHE_MIN_BYTES', 4 * 1024 * 1024), patch.object(
                M, '_cached_count', side_effect=AssertionError('small log used cache')):
            self.assertEqual(self.count()['observed_compactions'], 1)
        self.assertEqual(cache.read_bytes(), old_bytes)
        self.assertEqual(cache.stat().st_mtime_ns, old_stat.st_mtime_ns)


if __name__ == '__main__':
    unittest.main()

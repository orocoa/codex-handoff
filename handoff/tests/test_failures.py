import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import history
import dispatch


class Isolated(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work/handoff-failures'))) / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.packet = self.root / 'packet.md'
        self.packet.write_text('# Goal\nUse existing format because consumers depend on it.\n')
        self.archive = self.root / 'archive'
        self.receipt = self.root / 'receipt.json'

    def publish(self):
        return history.publish(self.archive, self.packet, 'packet-1', 'title', 'source')

    def prepare(self):
        return dispatch.prepare(self.receipt, self.packet, 'invocation-1', 'source', self.root)


class ArchiveFailures(Isolated):
    def test_flush_failure_never_exposes_partial_snapshot(self):
        with patch.object(history.os, 'fsync', side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertFalse((self.archive / 'snapshots/packet-1.md').exists())
        result = self.publish()
        self.assertEqual(Path(result['snapshot']).read_bytes(), self.packet.read_bytes())

    def test_process_killed_before_publication_can_retry(self):
        code = """import sys,os,signal
sys.path.insert(0, sys.argv[1])
import history
def stop(*args): os.kill(os.getpid(), signal.SIGKILL)
history.os.link=stop
history.publish(sys.argv[2],sys.argv[3],'packet-1','title','source')
"""
        result = subprocess.run([sys.executable, '-c', code, str(SCRIPTS), str(self.archive), str(self.packet)], capture_output=True)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse((self.archive / 'snapshots/packet-1.md').exists())
        self.assertTrue(list((self.archive / 'snapshots').glob('.packet-1.md.*')))
        result = self.publish()
        self.assertEqual(Path(result['snapshot']).read_bytes(), self.packet.read_bytes())

    def test_catalog_write_failure_recovers_complete_orphan(self):
        with patch.object(history, 'atomic', side_effect=OSError('catalog write failed')):
            with self.assertRaises(OSError):
                self.publish()
        snapshot = self.archive / 'snapshots/packet-1.md'
        inode = snapshot.stat().st_ino
        self.assertFalse((self.archive / 'catalog.json').exists())
        result = self.publish()
        self.assertEqual(snapshot.stat().st_ino, inode)
        self.assertEqual(result['total_entries'], 1)

    def test_index_write_failure_rebuilds_without_duplicate(self):
        original = history.atomic
        def fail_index(path, body):
            if path.name == 'INDEX.md':
                raise OSError('index write failed')
            original(path, body)
        with patch.object(history, 'atomic', side_effect=fail_index):
            with self.assertRaises(OSError):
                self.publish()
        self.assertTrue((self.archive / 'catalog.json').exists())
        result = self.publish()
        self.assertTrue(result['already_registered'])
        self.assertEqual(result['total_entries'], 1)
        self.assertEqual(len((self.archive / 'INDEX.md').read_text().splitlines()), 8)

    def test_existing_partial_snapshot_is_preserved(self):
        folder = self.archive / 'snapshots'
        folder.mkdir(parents=True)
        partial = folder / 'packet-1.md'
        partial.write_text('partial from older version')
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(partial.read_text(), 'partial from older version')

    def test_snapshot_is_private_under_permissive_umask(self):
        old = os.umask(0)
        try:
            result = self.publish()
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(Path(result['snapshot']).stat().st_mode), 0o600)

    def test_invalid_catalog_preserved(self):
        self.archive.mkdir()
        p = self.archive / 'catalog.json'
        for body in ('[]', '{"schema":"handoff-history-v1","entries":[{}]}'):
            p.write_text(body)
            with self.assertRaises(ValueError):
                self.publish()
            self.assertEqual(p.read_text(), body)


class DispatchFailures(Isolated):
    def test_same_invocation_reuses_receipt_and_claims_once(self):
        self.prepare()
        self.prepare()
        self.assertTrue(dispatch.claim(self.receipt)['may_create'])
        self.assertFalse(dispatch.claim(self.receipt)['may_create'])

    def test_concurrent_claim_only_one_winner(self):
        import concurrent.futures
        self.prepare()
        def run(_):
            r = subprocess.run([sys.executable, str(SCRIPTS / 'dispatch.py'), 'claim', '--receipt', str(self.receipt)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)['may_create']
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(run, range(4))), 1)

    def test_lost_create_response_does_not_repeat_side_effect(self):
        self.prepare()
        claim = dispatch.claim(self.receipt)
        attempts = []
        if claim['may_create']:
            attempts.append('simulated-created-task')  # Adapter performs create, then drops reply.
        self.assertFalse(dispatch.claim(self.receipt)['may_create'])
        token = claim['receipt']['attempt_id']
        dispatch.finish(self.receipt, token, 'uncertain', note='injected timeout after external creation')
        self.assertFalse(dispatch.claim(self.receipt)['may_create'])
        dispatch.finish(self.receipt, token, 'created', thread_id=attempts[0], host_id='local', note='matched unique packet marker')
        self.assertFalse(dispatch.claim(self.receipt)['may_create'])
        self.assertEqual(len(attempts), 1)

    def test_queued_resolves_without_new_claim(self):
        self.prepare()
        token = dispatch.claim(self.receipt)['receipt']['attempt_id']
        dispatch.finish(self.receipt, token, 'queued', client_id='client-1')
        self.assertFalse(dispatch.claim(self.receipt)['may_create'])
        result = dispatch.finish(self.receipt, token, 'created', thread_id='thread-1', host_id='local')
        self.assertEqual(result['destination'], {'clientThreadId': 'client-1', 'threadId': 'thread-1', 'hostId': 'local'})

    def test_proven_not_created_allows_retry_with_new_token(self):
        self.prepare()
        token = dispatch.claim(self.receipt)['receipt']['attempt_id']
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'not-created')
        dispatch.finish(self.receipt, token, 'not-created', note='adapter rejected before submitting creation')
        claim = dispatch.claim(self.receipt)
        self.assertTrue(claim['may_create'])
        self.assertNotEqual(token, claim['receipt']['attempt_id'])
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'created', thread_id='stale-thread')

    def test_conflicting_identity_or_packet_cannot_dispatch(self):
        self.prepare()
        with self.assertRaises(ValueError):
            dispatch.prepare(self.receipt, self.packet, 'other-invocation', 'source', self.root)
        self.packet.write_text('changed after preparation')
        with self.assertRaises(ValueError):
            dispatch.claim(self.receipt)

    def test_created_destination_cannot_be_replaced_or_downgraded(self):
        self.prepare()
        token = dispatch.claim(self.receipt)['receipt']['attempt_id']
        dispatch.finish(self.receipt, token, 'created', thread_id='thread-1')
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'created', thread_id='thread-2')
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'uncertain')

    def test_unpersisted_empty_appserver_thread_can_be_replaced_with_evidence(self):
        self.prepare()
        token = dispatch.claim(self.receipt)['receipt']['attempt_id']
        dispatch.finish(self.receipt, token, 'created', thread_id='empty-thread')
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'not-persisted')
        evidence = 'process exited before first turn; resume: no rollout; exhaustive list: absent'
        record = dispatch.finish(self.receipt, token, 'not-persisted', note=evidence)
        self.assertEqual(record['dispatch_state'], 'orphaned')
        self.assertFalse(record['destination'] is None)
        claim = dispatch.claim(self.receipt)
        self.assertTrue(claim['may_create'])
        self.assertNotEqual(token, claim['receipt']['attempt_id'])
        self.assertEqual(claim['receipt']['orphaned_destinations'][0]['destination']['threadId'], 'empty-thread')
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'created', thread_id='stale-thread')

    def test_failed_receipt_write_does_not_allow_create(self):
        self.prepare()
        with patch.object(dispatch, 'atomic', side_effect=OSError('receipt disk full')):
            with self.assertRaises(OSError):
                dispatch.claim(self.receipt)
        self.assertEqual(dispatch.read(self.receipt)['dispatch_state'], 'prepared')

    def test_result_write_failure_remains_unclaimable_and_can_reconcile(self):
        self.prepare()
        token = dispatch.claim(self.receipt)['receipt']['attempt_id']
        with patch.object(dispatch, 'atomic', side_effect=OSError('lost result write')):
            with self.assertRaises(OSError):
                dispatch.finish(self.receipt, token, 'created', thread_id='actual-thread')
        self.assertEqual(dispatch.read(self.receipt)['dispatch_state'], 'dispatching')
        self.assertFalse(dispatch.claim(self.receipt)['may_create'])
        result = dispatch.finish(self.receipt, token, 'created', thread_id='actual-thread', note='matched initial prompt marker')
        self.assertEqual(result['destination']['threadId'], 'actual-thread')

    def test_queued_without_client_identity_is_rejected(self):
        self.prepare()
        token = dispatch.claim(self.receipt)['receipt']['attempt_id']
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'queued')
        self.assertEqual(dispatch.read(self.receipt)['dispatch_state'], 'dispatching')

    def test_corrupt_receipt_is_not_reset(self):
        self.receipt.write_text('{broken')
        with self.assertRaises(ValueError):
            dispatch.claim(self.receipt)
        self.assertEqual(self.receipt.read_text(), '{broken')

    def test_inconsistent_state_with_destination_cannot_reopen_dispatch(self):
        self.prepare()
        dispatch.claim(self.receipt)
        data = json.loads(self.receipt.read_text())
        for state in ('prepared', 'failed', 'dispatching', 'uncertain'):
            data.update(dispatch_state=state, destination={'threadId': 'already-created'}, resolution_note='corrupted state')
            raw = json.dumps(data)
            self.receipt.write_text(raw)
            with self.assertRaises(ValueError):
                dispatch.claim(self.receipt)
            self.assertEqual(self.receipt.read_text(), raw)

    def test_destination_ids_must_be_strings(self):
        self.prepare()
        token = dispatch.claim(self.receipt)['receipt']['attempt_id']
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'created', thread_id=123)
        with self.assertRaises(ValueError):
            dispatch.finish(self.receipt, token, 'queued', thread_id='thread-1', client_id='client-1')
        self.assertEqual(dispatch.read(self.receipt)['dispatch_state'], 'dispatching')

    def test_receipt_is_private(self):
        self.prepare()
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o600)


if __name__ == '__main__':
    unittest.main(verbosity=2)

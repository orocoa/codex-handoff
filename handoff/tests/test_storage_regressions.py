import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import dispatch
import history


class StorageFixture(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work/storage-tests')))
        self.root = base / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.archive = self.workspace / 'history'
        self.packet = self.workspace / 'packet.md'
        self.packet.write_text('Synthetic packet: keep authorized scope.\n')
        self.receipt = self.workspace / 'receipt.json'

    def publish(self, **kwargs):
        return history.publish(self.archive, self.packet, 'packet-one', 'Title', 'source', **kwargs)

    def prepare(self, **kwargs):
        return dispatch.prepare(self.receipt, self.packet, 'invocation', 'source', self.workspace, **kwargs)


class HistoryBoundaries(StorageFixture):
    def test_preflight_missing_archive_is_read_only(self):
        state = history.preflight(self.archive, self.workspace)
        self.assertEqual(state['archive'], self.archive)
        self.assertEqual(state['data']['entries'], [])
        self.assertFalse(self.archive.exists())

    def test_preflight_manual_index_and_invalid_catalog_are_retained(self):
        manual = self.workspace / 'manual-history'
        manual.mkdir()
        index = manual / 'INDEX.md'
        index.write_text('User maintained index\n')
        with self.assertRaisesRegex(ValueError, 'not generated'):
            history.preflight(manual)
        self.assertEqual(index.read_text(), 'User maintained index\n')
        self.assertEqual(list(manual.iterdir()), [index])
        invalid = self.workspace / 'invalid-history'
        invalid.mkdir()
        catalog = invalid / 'catalog.json'
        catalog.write_text('{"schema":"unrelated"}')
        with self.assertRaisesRegex(ValueError, 'Unrecognized catalog'):
            history.preflight(invalid)
        self.assertEqual(catalog.read_text(), '{"schema":"unrelated"}')
        self.assertEqual(list(invalid.iterdir()), [catalog])

    def test_snapshot_directory_cannot_escape_workspace(self):
        self.archive.mkdir()
        outside = self.root / 'other-project'
        outside.mkdir()
        alias = self.archive / 'snapshots'
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'boundary'):
            history.preflight(self.archive, self.workspace)
        with self.assertRaisesRegex(ValueError, 'boundary'):
            self.publish(workspace=self.workspace)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.archive / 'catalog.json').exists())

    def test_default_archive_boundary_and_explicit_workspace_override(self):
        self.archive.mkdir()
        sibling = self.workspace / 'shared-snapshots'
        sibling.mkdir()
        alias = self.archive / 'snapshots'
        alias.symlink_to(sibling, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'boundary'):
            self.publish()
        result = self.publish(workspace=self.workspace)
        self.assertEqual(Path(result['snapshot']).parent, sibling)
        self.assertEqual(Path(result['snapshot']).read_bytes(), self.packet.read_bytes())
        self.assertTrue(alias.is_symlink())

    def test_archive_outside_workspace_is_rejected_before_mkdir(self):
        outside = self.root / 'outside-history'
        with self.assertRaisesRegex(ValueError, 'boundary'):
            history.publish(outside, self.packet, 'packet-one', 'Title', 'source', workspace=self.workspace)
        self.assertFalse(outside.exists())

    def test_boundary_is_rechecked_after_history_lock(self):
        self.archive.mkdir()
        outside = self.root / 'outside-after-check'
        outside.mkdir()
        original = history.fcntl.flock
        def acquire_and_change(fd, operation):
            original(fd, operation)
            (self.archive / 'snapshots').symlink_to(outside, target_is_directory=True)
        with patch.object(history.fcntl, 'flock', side_effect=acquire_and_change):
            with self.assertRaisesRegex(ValueError, 'boundary'):
                self.publish(workspace=self.workspace)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.archive / 'catalog.json').exists())


class StorageDurability(StorageFixture):
    def test_identical_history_retry_creates_no_tempfiles_or_new_inodes(self):
        first = self.publish()
        paths = [Path(first[key]) for key in ('snapshot', 'catalog', 'index')]
        before = [(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in paths]
        with patch.object(history.tempfile, 'mkstemp', side_effect=AssertionError('unnecessary write')):
            second = self.publish()
        self.assertTrue(second['already_registered'])
        self.assertEqual([(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in paths], before)

    def test_snapshot_retry_syncs_after_link_succeeded_and_directory_sync_failed(self):
        target = self.workspace / 'durable-snapshot.md'
        with patch.object(history, 'sync_directory', side_effect=OSError('directory sync failed')):
            with self.assertRaises(OSError):
                history.publish_snapshot(target, b'Complete snapshot\n')
        inode = target.stat().st_ino
        with patch.object(history.tempfile, 'mkstemp', side_effect=AssertionError('unnecessary write')):
            with patch.object(history, 'sync_directory', wraps=history.sync_directory) as synced:
                self.assertFalse(history.publish_snapshot(target, b'Complete snapshot\n'))
                synced.assert_called_once_with(target.parent)
        self.assertEqual(target.stat().st_ino, inode)

    def test_atomic_retry_syncs_after_replace_succeeded_and_directory_sync_failed(self):
        target = self.workspace / 'durable-receipt.json'
        with patch.object(history, 'sync_directory', side_effect=OSError('directory sync failed')):
            with self.assertRaises(OSError):
                history.atomic(target, '{"complete": true}\n')
        inode = target.stat().st_ino
        with patch.object(history.tempfile, 'mkstemp', side_effect=AssertionError('unnecessary write')):
            with patch.object(history, 'sync_directory', wraps=history.sync_directory) as synced:
                self.assertFalse(history.atomic(target, '{"complete": true}\n'))
                synced.assert_called_once_with(target.parent)
        self.assertEqual(target.stat().st_ino, inode)

    def test_catalog_sync_failure_repairs_missing_index_without_rewriting_catalog(self):
        original = history.sync_directory
        def fail_after_catalog_replace(path):
            if path == self.archive and (path / 'catalog.json').exists():
                raise OSError('catalog parent sync failed')
            original(path)
        with patch.object(history, 'sync_directory', side_effect=fail_after_catalog_replace):
            with self.assertRaises(OSError):
                self.publish()
        catalog = self.archive / 'catalog.json'
        self.assertTrue(catalog.exists())
        self.assertFalse((self.archive / 'INDEX.md').exists())
        inode = catalog.stat().st_ino
        result = self.publish()
        self.assertTrue(result['already_registered'])
        self.assertEqual(catalog.stat().st_ino, inode)
        self.assertTrue((self.archive / 'INDEX.md').exists())


class ReceiptAliases(StorageFixture):
    def test_symlink_claim_updates_original_and_preserves_alias(self):
        self.prepare()
        alias = self.workspace / 'receipt-alias.json'
        alias.symlink_to(self.receipt)
        first = dispatch.claim(alias)
        second = dispatch.claim(self.receipt)
        self.assertTrue(first['may_create'])
        self.assertFalse(second['may_create'])
        self.assertEqual(first['receipt']['attempt_id'], second['receipt']['attempt_id'])
        dispatch.finish(alias, first['receipt']['attempt_id'], 'created', thread_id='synthetic-target')
        self.assertEqual(dispatch.read(self.receipt)['destination']['threadId'], 'synthetic-target')
        self.assertTrue(alias.is_symlink())
        self.assertTrue(alias.samefile(self.receipt))

    def test_concurrent_aliases_share_one_claim(self):
        self.prepare()
        aliases = [self.receipt]
        for number in range(3):
            alias = self.workspace / ('alias-%s.json' % number)
            alias.symlink_to(self.receipt)
            aliases.append(alias)
        def run(path):
            result = subprocess.run([sys.executable, str(SCRIPTS / 'dispatch.py'), 'claim',
                                     '--receipt', str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, aliases))
        self.assertEqual(sum(r['may_create'] for r in results), 1)
        self.assertEqual(len({r['receipt']['attempt_id'] for r in results}), 1)
        self.assertTrue(all(alias.is_symlink() for alias in aliases[1:]))

    def test_hardlinks_are_rejected_without_splitting_receipt(self):
        self.prepare()
        alias = self.workspace / 'hardlink.json'
        os.link(self.receipt, alias)
        before = self.receipt.read_bytes()
        for path in (self.receipt, alias):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'Hard-linked'):
                dispatch.claim(path)
        self.assertTrue(alias.samefile(self.receipt))
        self.assertEqual(self.receipt.read_bytes(), before)


class DestinationIdentity(StorageFixture):
    def test_destination_ancestor_is_recorded_and_legacy_field_stays_optional(self):
        data = self.prepare(destination_workspace=self.root)
        self.assertEqual(data['destination_workspace'], str(self.root))
        self.assertTrue(dispatch.claim(self.receipt)['may_create'])
        legacy = self.workspace / 'legacy-receipt.json'
        old = dispatch.prepare(legacy, self.packet, 'legacy', 'source', self.workspace)
        self.assertNotIn('destination_workspace', old)
        self.assertTrue(dispatch.claim(legacy)['may_create'])

    def test_invalid_destination_does_not_publish_receipt(self):
        for destination in ('relative/path', self.root / 'different-project'):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                self.prepare(destination_workspace=destination)
            self.assertFalse(self.receipt.exists())


if __name__ == '__main__':
    unittest.main()

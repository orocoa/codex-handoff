import importlib.util
from pathlib import Path
import unittest
import subprocess
import tempfile
import sys
import os
import uuid
from contextlib import contextmanager
from unittest.mock import patch

P = Path(__file__).resolve().parents[1] / 'scripts' / 'resolve_target.py'
S = importlib.util.spec_from_file_location('resolve_target', P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)


FIXTURE_ROOT = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-destination-tests'))) / uuid.uuid4().hex
FIXTURE_ROOT.mkdir(parents=True)


def observed_path(path):
    if path.startswith(('/projects/', '/worktrees/', '/other/')):
        return FIXTURE_ROOT / path.lstrip('/')
    return Path(path)


@contextmanager
def retained_directory():
    yield tempfile.mkdtemp(prefix='inventory-', dir=FIXTURE_ROOT)


def project(pid='pc', path='/projects/PC', git=False, host='local', label='PC'):
    path = observed_path(path)
    path.mkdir(parents=True, exist_ok=True)
    if git:
        subprocess.run(['git', 'init', '-q', str(path)], check=True)
    return {'projectId': pid, 'path': str(path), 'isGitRepository': git,
            'hostId': host, 'label': label, 'projectKind': 'local'}


class DestinationTests(unittest.TestCase):
    def run_plan(self, projects=None, workspace='/projects/PC', **kw):
        actual = observed_path(workspace)
        if actual.is_absolute():
            actual.mkdir(parents=True, exist_ok=True)
        return M.resolve({'projects': projects if projects is not None else [project()]},
                         str(actual), 'local', '最终模型核对', '20260913-1300', **kw)

    def test_non_git_saved_pc_is_project_local(self):
        r = self.run_plan()
        self.assertEqual(r['target'], {'type': 'project', 'projectId': 'pc',
                                      'environment': {'type': 'local'}})
        self.assertEqual(r['title'], 'PC · 最终模型核对 · 接续 20260913-1300')

    def test_app_server_inventory_matches_saved_local_root(self):
        with retained_directory() as root:
            data = {'data': [{'id': 'saved-project', 'name': '3dprint',
                              'roots': [{'path': root}]}]}
            r = M.resolve(data, root, 'local', '架构讨论', '20260923-2120')
            self.assertEqual(r['target']['projectId'], 'saved-project')
            self.assertEqual(r['expected_cwd'], str(Path(root).resolve()))
            self.assertEqual(r['title'], '3dprint · 架构讨论 · 接续 20260923-2120')

    def test_app_server_duplicate_project_roots_are_ambiguous(self):
        with retained_directory() as root:
            data = {'data': [{'id': 'one', 'name': 'A', 'roots': [{'path': root}]},
                             {'id': 'two', 'name': 'B', 'roots': [{'path': root}]}]}
            r = M.resolve(data, root, 'local', '架构讨论', '20260923-2120')
            self.assertEqual(r['reason'], 'ambiguous_project_match')

    def test_git_defaults_to_approved_local_directory(self):
        self.assertEqual(self.run_plan([project(git=True)])['target']['environment'], {'type': 'local'})

    def test_same_directory_cannot_silently_leave_source_worktree(self):
        r = self.run_plan([project(git=True)], '/worktrees/feature',
                          source_project_id='pc')
        self.assertEqual(r['reason'], 'source_checkout_differs_from_project_local')
        self.assertNotIn('target', r)

    def test_local_plan_exposes_saved_cwd_without_transfer(self):
        r = self.run_plan(workspace='/projects/PC/output')
        self.assertEqual(r['expected_cwd'], str(observed_path('/projects/PC')))

    def test_nested_git_checkout_is_not_the_saved_checkout(self):
        fixture_root = Path.cwd() / 'work' / 'handoff-destination-tests'
        fixture_root.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix='nested-', dir=fixture_root))
        nested = root / 'nested'
        nested.mkdir()
        for path in (root, nested):
            subprocess.run(['git', 'init', '-q', str(path)], check=True)
        r = self.run_plan([project(path=str(root), git=True)], str(nested),
                          source_project_id='pc')
        self.assertEqual(r['reason'], 'source_checkout_differs_from_project_local')
        local = self.run_plan([project(path=str(root), git=True)], str(root),
                              source_project_id='pc')
        self.assertEqual(local['target']['environment'], {'type': 'local'})

    def test_linked_source_is_outside_local_scope_and_files_stay_intact(self):
        fixture_root = Path.cwd() / 'work' / 'handoff-destination-tests'
        fixture_root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='linked-', dir=fixture_root))
        main, linked = folder / 'main', folder / 'linked'
        subprocess.run(['git', 'init', '-q', str(main)], check=True)
        subprocess.run(['git', '-C', str(main), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false',
                        'commit', '--allow-empty', '-qm', 'fixture'], check=True)
        subprocess.run(['git', '-C', str(main), 'worktree', 'add', '-q', '--detach', str(linked)], check=True)
        (main / 'state.txt').write_text('original')
        (linked / 'state.txt').write_text('latest uncommitted work')
        r = self.run_plan([project(path=str(main), git=True)], str(linked), source_project_id='pc')
        self.assertEqual(r['reason'], 'source_checkout_differs_from_project_local')
        self.assertNotIn('target', r)
        self.assertEqual((main / 'state.txt').read_text(), 'original')
        self.assertEqual((linked / 'state.txt').read_text(), 'latest uncommitted work')
        unverified = self.run_plan([project(path=str(main), git=True)], str(linked))
        self.assertEqual(unverified['status'], 'unresolved')

    def test_nested_workspace_chooses_deepest_root(self):
        r = self.run_plan([project(), project('models', '/projects/PC/models')], '/projects/PC/models/output')
        self.assertEqual(r['target']['projectId'], 'models')

    def test_component_boundary_avoids_pc_copy(self):
        self.assertEqual(self.run_plan(workspace='/projects/PC-copy')['status'], 'unresolved')

    def test_same_name_elsewhere_does_not_match(self):
        self.assertEqual(self.run_plan([project(path='/other/PC')])['status'], 'unresolved')

    def test_other_host_same_path_does_not_match(self):
        self.assertEqual(self.run_plan([project(host='remote')])['status'], 'unresolved')

    def test_duplicate_matching_roots_are_ambiguous(self):
        self.assertEqual(self.run_plan([project(), project('second')])['reason'], 'ambiguous_project_match')

    def test_default_local_rejects_external_source_worktree(self):
        r = self.run_plan([project(git=True)], '/worktrees/feature', source_project_id='pc')
        self.assertEqual(r['reason'], 'source_checkout_differs_from_project_local')

    def test_stale_source_id_does_not_silently_path_fallback(self):
        self.assertEqual(self.run_plan(source_project_id='gone')['status'], 'unresolved')

    def test_unknown_git_status_does_not_guess(self):
        self.assertEqual(self.run_plan([project(git=None)])['status'], 'unresolved')

    def test_no_project_does_not_silently_create_projectless(self):
        r = self.run_plan([])
        self.assertEqual(r['status'], 'unresolved')
        self.assertNotIn('target', r)

    def test_explicit_title_and_retry_stability(self):
        self.assertEqual(self.run_plan(title='我的最终模型')['title'], '我的最终模型')
        self.assertEqual(self.run_plan(), self.run_plan())

    def test_failed_inventory_is_not_empty_inventory(self):
        with self.assertRaises(ValueError):
            M.resolve({'error': 'unavailable'}, str(FIXTURE_ROOT), 'local', '核对', '20260913-1300')

    def test_relative_workspace_rejected(self):
        with self.assertRaises(ValueError):
            self.run_plan(workspace='PC')

    def test_removed_directory_flags_are_rejected(self):
        for flag in ('--new-worktree', '--same-directory', '--projectless'):
            result = subprocess.run([sys.executable, str(P), '--projects-json', 'unused.json',
                                     '--workspace', '/projects/PC', '--host-id', 'local',
                                     '--topic', '继续', '--stamp', '20260916-1500', flag],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('unrecognized arguments', result.stderr)


class RoutingRegressions(unittest.TestCase):
    def setUp(self):
        self.root = FIXTURE_ROOT / uuid.uuid4().hex
        self.root.mkdir()

    def resolve(self, data, root=None, **kw):
        return M.resolve(data, str(root or self.root), 'local', 'Continue', '20260929-1200', **kw)

    def test_no_git_probe_for_unrelated_inventory_roots(self):
        roots = []
        for i in range(100):
            path = self.root / str(i)
            path.mkdir()
            roots.append({'id': str(i), 'name': str(i), 'roots': [{'path': str(path)}]})
        with patch.object(M, 'git_root', return_value=None) as probe:
            result = self.resolve({'data': roots}, self.root / '99')
        self.assertEqual(result['target']['projectId'], '99')
        probe.assert_called_once_with(self.root / '99')

    def test_verified_id_with_multiple_roots_selects_containing_root(self):
        other = self.root / 'other'
        other.mkdir()
        data = {'data': [{'id': 'p', 'name': 'P', 'roots': [{'path': str(other)}, {'path': str(self.root)}]}]}
        result = self.resolve(data, source_project_id='p')
        self.assertEqual(result['expected_cwd'], str(self.root))

    def test_missing_workspace_never_resolves(self):
        absent = self.root / 'absent'
        for is_git in (True, False):
            data = {'projects': [{'projectId': 'p', 'path': str(absent), 'hostId': 'local',
                                  'label': 'P', 'isGitRepository': is_git}]}
            with self.subTest(is_git=is_git), patch.object(M, 'git_root') as probe:
                result = self.resolve(data, absent)
                self.assertEqual(result['reason'], 'source_workspace_missing')
                probe.assert_not_called()

    def test_non_git_saved_container_does_not_hide_nested_repository(self):
        nested = self.root / 'nested'
        subprocess.run(['git', 'init', '-q', str(nested)], check=True)
        data = {'projects': [project('p', str(self.root), git=False)]}
        self.assertEqual(self.resolve(data, nested)['reason'], 'source_checkout_differs_from_project_local')

    def test_probe_timeout_fails_closed(self):
        data = {'data': [{'id': 'p', 'name': 'P', 'roots': [{'path': str(self.root)}]}]}
        with patch.object(M, 'git_root', side_effect=subprocess.TimeoutExpired('git', 10)):
            self.assertEqual(self.resolve(data)['reason'], 'source_git_checkout_unverified')

    def test_invalid_remote_host_never_probes_git(self):
        with patch.object(M, 'git_root') as probe, self.assertRaises(ValueError):
            M.resolve({'data': []}, str(self.root), 'remote', 'Continue', '20260929-1200')
        probe.assert_not_called()

    def test_relative_appserver_root_is_rejected(self):
        with self.assertRaises(ValueError):
            self.resolve({'data': [{'id': 'p', 'name': 'P', 'roots': [{'path': 'relative'}]}]})


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Read-only local Project/title plan from a fresh desktop or App Server inventory."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def clean(text):
    return ' '.join(text.replace('·', ' ').replace('|', ' ').replace('｜', ' ').split())


def git_root(path):
    """Probe only a selected path; never fan out over unrelated projects."""
    probe = subprocess.run(['git', '-C', str(path), 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, timeout=10)
    return Path(probe.stdout.strip()).resolve() if probe.returncode == 0 else None


def resolve(data, workspace, host_id, topic, stamp, source_project_id=None,
            title=None):
    if host_id != 'local':
        raise ValueError('This local path helper cannot resolve another host; match on its owning host')
    if not Path(workspace).is_absolute():
        raise ValueError('Workspace must be an observed absolute path')
    root = Path(workspace).resolve()
    if not root.is_dir():
        return {'status': 'unresolved', 'reason': 'source_workspace_missing', 'workspace': str(root)}
    if not re.fullmatch(r'\d{8}-\d{4}', stamp) or not clean(topic):
        raise ValueError('Provide a preparation timestamp YYYYMMDD-HHmm and a concise topic')
    if not isinstance(data, dict):
        raise ValueError('Expected a decoded Project inventory object')
    appserver = False
    if isinstance(data.get('projects'), list):
        inventory = data['projects']
    elif isinstance(data.get('data'), list):
        appserver = True
        inventory = []
        for project in data['data']:
            if not isinstance(project, dict):
                continue
            for entry in project.get('roots', []):
                if isinstance(entry, dict) and entry.get('path'):
                    inventory.append({'hostId': 'local', 'path': entry['path'],
                                      'projectId': project.get('id'), 'label': project.get('name')})
    else:
        raise ValueError('Expected native projects or App Server data list')
    projects = [p for p in inventory if isinstance(p, dict)
                and p.get('hostId') == host_id and p.get('path') and p.get('projectId')]
    if source_project_id:
        projects = [p for p in projects if p['projectId'] == source_project_id]
        if not projects:
            return {'status': 'unresolved', 'reason': 'verified_source_project_not_unique_in_fresh_list'}
    matches = []
    for project in projects:
        path = Path(project['path'])
        if not path.is_absolute():
            raise ValueError('Project paths must be absolute')
        path = path.resolve()
        if root == path or path in root.parents:
            matches.append((len(path.parts), project, path))
    if not matches:
        reason = 'source_checkout_differs_from_project_local' if source_project_id else 'no_saved_project_for_workspace'
        return {'status': 'unresolved', 'reason': reason, 'workspace': str(root)}
    depth = max(m[0] for m in matches)
    closest = [m for m in matches if m[0] == depth]
    if len(closest) != 1:
        return {'status': 'unresolved', 'reason': 'ambiguous_project_match',
                'candidates': [m[1]['projectId'] for m in closest]}
    _, match, project_path = closest[0]
    if not project_path.is_dir():
        return {'status': 'unresolved', 'reason': 'saved_project_directory_missing'}
    if not isinstance(match.get('label'), str) or not clean(match['label']):
        return {'status': 'unresolved', 'reason': 'missing_project_label_or_git_status'}
    if not appserver and type(match.get('isGitRepository')) is not bool:
        return {'status': 'unresolved', 'reason': 'missing_project_label_or_git_status'}
    # A nested source needs a checkout check even when the saved container is non-Git.
    # For an exact native non-Git root, the fresh inventory already supplies this fact.
    if appserver or match.get('isGitRepository') or root != project_path:
        try:
            checkout = git_root(root)
        except (OSError, subprocess.TimeoutExpired):
            return {'status': 'unresolved', 'reason': 'source_git_checkout_unverified'}
        if match.get('isGitRepository') and checkout is None:
            return {'status': 'unresolved', 'reason': 'source_git_checkout_unverified'}
        if checkout is not None and checkout != project_path:
            # A non-Git saved folder may itself be inside a larger checkout;
            # reject only an unrelated checkout nested within the saved folder.
            if match.get('isGitRepository') or project_path in checkout.parents:
                return {'status': 'unresolved', 'reason': 'source_checkout_differs_from_project_local',
                        'source_workspace': str(root), 'matched_project_path': str(project_path)}
    basis = ('verified_source_task_project_id' if source_project_id else
             'canonical_exact_path' if root == project_path else 'deepest_containing_project')
    label = match['label']
    resolved_title = title if title is not None else f'{clean(label)} · {clean(topic)} · 接续 {stamp}'
    if not isinstance(resolved_title, str) or not resolved_title.strip():
        raise ValueError('Title cannot be empty')
    target = {'type': 'project', 'projectId': match['projectId'], 'environment': {'type': 'local'}}
    return {'status': 'resolved', 'basis': basis, 'source_workspace': str(root),
            'matched_project_path': str(project_path), 'expected_cwd': str(project_path),
            'project_label': label, 'target': target, 'title': resolved_title}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('projects-json', 'workspace', 'host-id', 'topic', 'stamp'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--verified-source-project-id')
    p.add_argument('--title')
    a = p.parse_args()
    try:
        result = resolve(json.loads(Path(a.projects_json).read_text()), a.workspace,
                         a.host_id, a.topic, a.stamp, a.verified_source_project_id,
                         a.title)
    except (ValueError, OSError, TypeError) as e:
        p.exit(1, str(e) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] != 'resolved':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

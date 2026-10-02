#!/usr/bin/env python3
"""Create one project-aware handoff thread via the documented Codex App Server.

The caller must prepare and claim a dispatch receipt first. A detached worker
keeps the stdio connection alive after the first turn starts; no ambiguous
thread/start request is retried automatically.
"""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

import dispatch


def source_context(path, record):
    """Read only the identified source rollout, never guess a task by recency."""
    identity, context = None, None
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                raise ValueError('Incomplete source rollout; retry reading this same source')
            if event.get('type') == 'session_meta':
                identity = event.get('payload', {})
            elif event.get('type') == 'turn_context':
                context = event.get('payload', {})
    if not identity or identity.get('id') != record['source_thread_id'] or not context:
        raise ValueError('Source rollout identity/context does not match receipt')
    if (not isinstance(context.get('cwd'), str) or not Path(context['cwd']).is_absolute() or
            Path(context['cwd']).resolve() != Path(record['source_workspace']).resolve()):
        raise ValueError('Source execution context cwd does not match receipt')
    profile = context.get('active_permission_profile') or {}
    if profile.get('id') and not profile['id'].startswith(':'):
        raise ValueError('Named permission profiles require native desktop dispatch')
    raw = context.get('sandbox_policy', {})
    mode = raw.get('type')
    modes = {'danger-full-access': 'dangerFullAccess', 'workspace-write': 'workspaceWrite',
             'read-only': 'readOnly'}
    if mode not in modes:
        raise ValueError('Unsupported source permissions; use native desktop dispatch')
    fields = {'network_access': 'networkAccess', 'writable_roots': 'writableRoots',
              'exclude_tmpdir_env_var': 'excludeTmpdirEnvVar', 'exclude_slash_tmp': 'excludeSlashTmp'}
    if set(raw) - {'type', *fields}:
        raise ValueError('Unknown source sandbox fields; refusing lossy permission transfer')
    sandbox = {'type': modes[mode]}
    sandbox.update({fields[k]: v for k, v in raw.items() if k != 'type'})
    approval = context.get('approval_policy')
    require_interactive_policy(approval)
    model, effort = context.get('model'), context.get('effort')
    provider = identity.get('model_provider')
    reviewer = context.get('approvals_reviewer')
    if (any(not isinstance(value, str) or not value.strip() for value in (model, effort, provider)) or
            reviewer not in ('user', 'auto_review')):
        raise ValueError('Incomplete source model/provider/effort/reviewer; do not assume CLI defaults')
    if 'workspace_roots' not in context:
        raise ValueError('Source workspace roots are unknown; use native desktop dispatch')
    roots = context['workspace_roots']
    if not isinstance(roots, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in roots):
        raise ValueError('Invalid source workspace roots; use native desktop dispatch')
    return {'model': model, 'modelProvider': provider, 'effort': effort, 'approvalPolicy': approval,
            'approvalsReviewer': reviewer, 'sandboxPolicy': sandbox, 'sandboxMode': mode,
            'runtimeWorkspaceRoots': roots}


def require_interactive_policy(approval):
    if approval != 'on-request':
        raise ValueError('App Server handoff requires effective approval_policy=on-request; '
                         'do not copy never or retired policies into a successor. '
                         'Select interactive permissions before recovery; unsupported granular policies need native dispatch.')


def start_settings(context):
    """Preserve observed settings for this new thread; never edit global config."""
    require_interactive_policy(context.get('approvalPolicy'))
    config = {'model_reasoning_effort': context['effort']}
    if context['sandboxMode'] == 'workspace-write':
        fields = {'networkAccess': 'network_access', 'writableRoots': 'writable_roots',
                  'excludeTmpdirEnvVar': 'exclude_tmpdir_env_var', 'excludeSlashTmp': 'exclude_slash_tmp'}
        defaults = {'networkAccess': False, 'writableRoots': [],
                    'excludeTmpdirEnvVar': False, 'excludeSlashTmp': False}
        config.update({'sandbox_workspace_write.' + dest: context['sandboxPolicy'].get(src, defaults[src])
                       for src, dest in fields.items()})
    elif context['sandboxMode'] == 'read-only' and context['sandboxPolicy'].get('networkAccess'):
        raise ValueError('Read-only network override requires native desktop dispatch')
    result = {'model': context['model'], 'modelProvider': context['modelProvider'],
            'approvalPolicy': context['approvalPolicy'],
            'approvalsReviewer': context['approvalsReviewer'], 'sandbox': context['sandboxMode'],
            'config': config, 'runtimeWorkspaceRoots': context['runtimeWorkspaceRoots']}
    return result


def normalized_sandbox(policy):
    result = dict(policy)
    if result.get('type') in ('workspaceWrite', 'readOnly'):
        result.setdefault('networkAccess', False)
    if result.get('type') == 'workspaceWrite':
        for key, value in (('writableRoots', []), ('excludeTmpdirEnvVar', False), ('excludeSlashTmp', False)):
            result.setdefault(key, value)
    return result


def verify_settings(response, context):
    for key, expected in (('model', context['model']), ('modelProvider', context['modelProvider']),
                          ('reasoningEffort', context['effort']),
                          ('approvalPolicy', context['approvalPolicy']),
                          ('approvalsReviewer', context['approvalsReviewer'])):
        if response.get(key) != expected:
            raise RuntimeError('Effective ' + key + ' differs from source; no turn started')
    if normalized_sandbox(response.get('sandbox', {})) != normalized_sandbox(context['sandboxPolicy']):
        raise RuntimeError('Effective sandbox differs from source; no turn started')
    if response.get('runtimeWorkspaceRoots') != context['runtimeWorkspaceRoots']:
        raise RuntimeError('Effective workspace roots differ from source; no turn started')


def runtime_path(receipt, attempt):
    return receipt.with_name(receipt.name + '.' + attempt + '.runtime.json')


def write_runtime(path, state, **fields):
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update(state=state, updated_at=dispatch.now(), **fields)
    dispatch.atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return data


class RpcClient:
    def __init__(self):
        self.process = subprocess.Popen(
            ['codex', 'app-server', '--stdio'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        self.buffer = b''
        self.lines = deque()
        self.notifications = deque()
        self.next_id = 0

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()

    def send(self, message, deadline=None):
        deadline = time.monotonic() + 30 if deadline is None else deadline
        pending = memoryview((json.dumps(message, ensure_ascii=False) + '\n').encode())
        descriptor = self.process.stdin.fileno()
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('App Server request write timed out')
            _, writable, _ = select.select([], [descriptor], [], remaining)
            if not writable:
                raise TimeoutError('App Server request write timed out')
            try:
                written = os.write(descriptor, pending)
            except BlockingIOError:
                continue
            if not written:
                raise RuntimeError('App Server closed the input connection')
            pending = pending[written:]

    def read(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('App Server response timed out')
            if self.lines:
                return json.loads(self.lines.popleft())
            readable, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not readable:
                raise TimeoutError('App Server response timed out')
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('App Server closed the connection')
            lines = (self.buffer + chunk).split(b'\n')
            self.buffer = lines.pop()
            self.lines.extend(line for line in lines if line)

    def request(self, method, params, timeout=30):
        self.next_id += 1
        request_id = self.next_id
        deadline = time.monotonic() + timeout
        self.send({'id': request_id, 'method': method, 'params': params}, deadline=deadline)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method + ': App Server response timed out')
            message = self.read(remaining)
            if time.monotonic() >= deadline:
                raise TimeoutError(method + ': App Server response timed out')
            if 'method' in message or message.get('id') != request_id:
                self.notifications.append(message)
                continue
            if 'error' in message:
                raise RuntimeError(f'{method}: {message["error"]}')
            return message['result']


def list_projects(rpc):
    """Read the complete saved Project inventory before matching an ID."""
    projects, seen, cursor = [], set(), None
    for _ in range(100):
        params = {'limit': 100}
        if cursor:
            params['cursor'] = cursor
        page = rpc.request('project/list', params)
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise RuntimeError('Invalid Project list response')
        projects.extend(page['data'])
        cursor = page.get('nextCursor')
        if cursor is None:
            return projects
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise RuntimeError('Invalid or repeated Project list cursor')
        seen.add(cursor)
    raise RuntimeError('Project list exceeded 100 pages; refusing incomplete verification')


def contains(root, path):
    return path == root or root in path.parents


def verify_project(projects, project_id, source, destination):
    """Both observed directories must belong to the same saved Local checkout."""
    matches = [project for project in projects if project.get('id') == project_id]
    if len(matches) != 1:
        raise RuntimeError('Claimed Project ID is not unique in the fresh saved Project list')
    source, destination = Path(source).resolve(), Path(destination).resolve()
    for entry in matches[0].get('roots', []):
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            continue
        root = Path(entry['path'])
        if not root.is_absolute() or not root.is_dir():
            continue
        root = root.resolve()
        if not all(contains(root, path) for path in (source, destination)):
            continue
        # Matching path ancestry alone must not accept a nested Git repository.
        checkouts = []
        for path in dict.fromkeys((root, source, destination)):
            probe = subprocess.run(['git', '-C', str(path), 'rev-parse', '--show-toplevel'],
                                   capture_output=True, text=True, timeout=5)
            checkouts.append(Path(probe.stdout.strip()).resolve() if probe.returncode == 0 else None)
        if all(checkout == checkouts[0] for checkout in checkouts):
            return
    raise RuntimeError('Source/destination cwd no longer share the claimed saved Project checkout')


def verify_destination_permissions(context, source, destination):
    """Changing implicit writable cwd must not grant access above the source."""
    if context['sandboxMode'] != 'workspace-write':
        return
    roots = [Path(source).resolve()]
    roots.extend(Path(path).resolve() for path in context['sandboxPolicy'].get('writableRoots', []))
    if not any(contains(root, Path(destination).resolve()) for root in roots):
        raise ValueError('Destination cwd would expand source writable access; use native desktop dispatch')


def monitor_turn(rpc, thread_id, turn_id, runtime):
    """A headless client cannot present human requests. Interrupt, then release."""
    while True:
        try:
            message = rpc.notifications.popleft() if rpc.notifications else rpc.read(60)
        except TimeoutError:
            continue  # Healthy work has no arbitrary duration limit.
        method, params = message.get('method', ''), message.get('params', {})
        event_turn = params.get('turnId') or params.get('turn', {}).get('id')
        same_turn = params.get('threadId', thread_id) == thread_id and (not event_turn or event_turn == turn_id)
        # All server requests need a client response, including future request types.
        # turn/interrupt clears pending requests without granting permission or
        # inventing an answer. Closing our own server below releases its writer.
        if ('id' in message and method) or method == 'turn/approvalRequested':
            write_runtime(runtime, 'attention_required', requestMethod=method,
                          requestId=message.get('id'), requestThreadId=params.get('threadId'),
                          requestTurnId=event_turn, writerReleased=False)
            print(json.dumps({'event': 'attention_required', 'threadId': thread_id,
                              'method': method,
                              'action': 'interrupt_and_release' if same_turn else 'release_own_client'}), flush=True)
            if same_turn:
                try:
                    rpc.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id}, timeout=5)
                except (RuntimeError, TimeoutError) as exc:
                    write_runtime(runtime, 'attention_required', interruptError=str(exc))
            return 'attention_required'
        if not same_turn:
            continue
        if method == 'turn/completed':
            turn = params.get('turn', {})
            status = turn.get('status', 'unknown')
            print(json.dumps({'event': 'turn_completed', 'threadId': thread_id,
                              'status': status, 'error': turn.get('error')}), flush=True)
            write_runtime(runtime, status, turnStatus=status, turnError=turn.get('error'))
            return status


def start_detached(args, receipt):
    """Return after turn/start while a separate client monitors the first turn."""
    log = receipt.with_name(receipt.name + '.' + args.attempt_id + '.appserver.log')
    fd = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    command = [sys.executable, str(Path(__file__).resolve())]
    for name in ('receipt', 'attempt_id', 'packet', 'project_id', 'cwd', 'title', 'prompt_file', 'source_rollout'):
        command.extend(['--' + name.replace('_', '-'), str(getattr(args, name))])
    with os.fdopen(fd, 'wb') as output:
        worker = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                  stderr=output, start_new_session=True, close_fds=True)
    deadline = time.monotonic() + args.startup_timeout
    runtime = runtime_path(receipt, args.attempt_id)
    while time.monotonic() < deadline:
        state = dispatch.read(receipt)
        live = json.loads(runtime.read_text()) if runtime.exists() else {}
        if worker.poll() is not None and (worker.returncode != 0 or state['dispatch_state'] != 'created'):
            print(json.dumps({'event': 'startup_failed', 'monitorPid': worker.pid,
                              'exitCode': worker.returncode, 'log': str(log),
                              'receiptState': state['dispatch_state'], 'runtime': str(runtime),
                              'runtimeState': live.get('state'), 'threadId': live.get('threadId'),
                              'writerReleased': live.get('writerReleased', False)}, ensure_ascii=False), flush=True)
            return 1
        if state['dispatch_state'] == 'created':
            needs_attention = live.get('state') in ('attention_required', 'failed', 'interrupted')
            print(json.dumps({'event': 'turn_started', 'threadId': state['destination']['threadId'],
                              'monitorPid': worker.pid, 'log': str(log), 'runtime': str(runtime),
                              'runtimeState': live.get('state'),
                              'writerReleased': live.get('writerReleased', False),
                              'needsAttention': needs_attention,
                              'desktopReady': False}, ensure_ascii=False), flush=True)
            return 3 if needs_attention else 0
        time.sleep(0.1)
    print(json.dumps({'event': 'startup_pending', 'monitorPid': worker.pid,
                      'log': str(log), 'runtime': str(runtime),
                      'receiptState': dispatch.read(receipt)['dispatch_state']},
                     ensure_ascii=False), flush=True)
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('receipt', 'attempt-id', 'packet', 'project-id', 'cwd', 'title', 'prompt-file', 'source-rollout'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--detach', action='store_true', help='Return after turn/start; keep the worker alive')
    parser.add_argument('--startup-timeout', type=int, default=30)
    args = parser.parse_args()
    receipt = Path(args.receipt).resolve()
    args.receipt = str(receipt)  # Detached children must use the same worker identity.
    record = dispatch.read(receipt)
    if record['dispatch_state'] != 'dispatching' or record['attempt_id'] != args.attempt_id:
        parser.error('receipt is not claimed by this attempt; refusing thread/start')
    if Path(args.packet).resolve() != Path(record['packet_path']):
        parser.error('packet does not match claimed receipt')
    if hashlib.sha256(Path(args.packet).read_bytes()).hexdigest() != record['packet_sha256']:
        parser.error('packet changed after claim; refusing thread/start')
    if Path(args.cwd).resolve() != Path(record.get('destination_workspace', record['source_workspace'])).resolve():
        parser.error('destination cwd differs from the claimed destination workspace')
    if (not Path(args.cwd).is_absolute() or not Path(args.cwd).is_dir() or
            not Path(record['source_workspace']).is_dir() or not Path(args.prompt_file).is_file()):
        parser.error('source/destination cwd must exist and destination must be absolute; prompt file must exist')
    prompt = Path(args.prompt_file).read_text()
    if Path(args.packet).name not in prompt:
        parser.error('receiver prompt must contain the unique packet filename')
    if args.startup_timeout < 1:
        parser.error('startup-timeout must be positive')
    try:
        context = source_context(args.source_rollout, record)
        settings = start_settings(context)
        verify_destination_permissions(context, record['source_workspace'], args.cwd)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.detach:
        raise SystemExit(start_detached(args, receipt))

    runtime = runtime_path(receipt, args.attempt_id)
    # A claim authorizes one worker even when someone invokes the foreground
    # helper twice. Never remove this marker to retry an uncertain attempt.
    owner = runtime.with_suffix('.worker-claim')
    fd = os.open(owner, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    write_runtime(runtime, 'starting', writerReleased=False, executionContext=context)
    rpc = None
    created = False
    result_status = None
    try:
        rpc = RpcClient()
        rpc.request('initialize', {
            'clientInfo': {'name': 'handoff_skill', 'title': 'Codex Handoff Skill',
                           'version': (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()},
            'capabilities': {'experimentalApi': True}})
        rpc.send({'method': 'initialized', 'params': {}})
        projects = list_projects(rpc)
        verify_project(projects, args.project_id, record['source_workspace'], args.cwd)

        response = rpc.request('thread/start', {
            'projectId': args.project_id, 'cwd': str(Path(args.cwd).resolve()), 'ephemeral': False,
            **settings})
        thread = response['thread']
        thread_id = thread['id']
        write_runtime(runtime, 'starting', threadId=thread_id)
        verify_settings(response, context)
        print(json.dumps({'event': 'thread_started', 'threadId': thread_id,
                          'projectId': thread.get('projectId'), 'cwd': thread.get('cwd')},
                         ensure_ascii=False), flush=True)
        observed = thread
        if not observed.get('projectId') or not observed.get('cwd'):
            observed = rpc.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']
        if (observed.get('projectId') != args.project_id or not observed.get('cwd') or
                Path(observed['cwd']).resolve() != Path(args.cwd).resolve()):
            raise RuntimeError('Thread Project/cwd verification failed before first turn')
        rpc.request('thread/name/set', {'threadId': thread_id, 'name': args.title})
        turn = rpc.request('turn/start', {'threadId': thread_id,
                            'model': context['model'], 'effort': context['effort'],
                            'approvalPolicy': context['approvalPolicy'],
                            'approvalsReviewer': context['approvalsReviewer'],
                            'sandboxPolicy': context['sandboxPolicy'],
                            'input': [{'type': 'text', 'text': prompt}]}, timeout=60)
        turn_id = turn['turn']['id']
        dispatch.finish(receipt, args.attempt_id, 'created', thread_id=thread_id, host_id='local')
        created = True
        write_runtime(runtime, 'running', turnId=turn_id)
        print(json.dumps({'event': 'turn_started', 'threadId': thread_id,
                          'projectId': args.project_id, 'cwd': args.cwd}, ensure_ascii=False), flush=True)
        result_status = monitor_turn(rpc, thread_id, turn_id, runtime)
        if result_status == 'attention_required':
            return 3
        detail = rpc.request('thread/read', {'threadId': thread_id, 'includeTurns': False})['thread']
        print(json.dumps({'event': 'verified_thread', 'threadId': thread_id,
                          'projectId': detail.get('projectId'), 'cwd': detail.get('cwd'),
                          'name': detail.get('name')}, ensure_ascii=False), flush=True)
        if (detail.get('projectId') != args.project_id or not detail.get('cwd') or
                Path(detail['cwd']).resolve() != Path(args.cwd).resolve()):
            raise RuntimeError('Persisted thread Project/cwd verification failed')
        return 0 if result_status == 'completed' else 1
    except Exception as exc:
        if not created:
            # A timeout after thread/start was sent is ambiguous. The durable
            # receipt prevents a blind second creation attempt.
            dispatch.finish(receipt, args.attempt_id, 'uncertain', note=str(exc))
        print(json.dumps({'event': 'error', 'created': created, 'detail': str(exc)}, ensure_ascii=False), flush=True)
        write_runtime(runtime, 'failed', error=str(exc))
        raise
    finally:
        if rpc is not None:
            rpc.close()
        current = json.loads(runtime.read_text())
        write_runtime(runtime, current['state'], writerReleased=True, released_at=dispatch.now())
        print(json.dumps({'event': 'writer_released', 'state': current['state']}), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())

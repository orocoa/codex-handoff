#!/usr/bin/env python3
"""Local dispatch receipt for Codex desktop. Never creates a task itself."""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid

from history import atomic

SCHEMA = 'codex-handoff-dispatch-v1'
STATES = {'prepared', 'dispatching', 'uncertain', 'failed', 'queued', 'created', 'orphaned'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@contextmanager
def locked(path):
    # Aliases must share both the lock and the file replaced by atomic writes.
    # Hard links have no unique canonical pathname; reject rather than split them.
    path = Path(path).resolve()
    def check_identity():
        if path.resolve() != path:
            raise ValueError('Receipt path changed while locking; original retained')
        try:
            links = path.stat().st_nlink
        except FileNotFoundError:
            return
        if links > 1:
            raise ValueError('Hard-linked receipts are unsupported; original retained')
    check_identity()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        check_identity()
        yield path


def validate(data):
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('dispatch_state') not in STATES:
        raise ValueError('Unrecognized receipt; preserve it and reconcile manually')
    for key in ('packet_path', 'packet_sha256', 'invocation_id', 'source_thread_id', 'source_workspace'):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError('Invalid receipt identity; original retained')
    if 'destination_workspace' in data:
        destination = data['destination_workspace']
        if not isinstance(destination, str) or not destination.strip() or not Path(destination).is_absolute():
            raise ValueError('Invalid destination workspace; original retained')
        source = Path(data['source_workspace']).resolve()
        if Path(destination).resolve() not in (source, *source.parents):
            raise ValueError('Destination workspace must contain the source; original retained')
    state = data['dispatch_state']
    attempt = data.get('attempt_id')
    if state != 'prepared' and (not isinstance(attempt, str) or not attempt.strip()):
        raise ValueError('Missing attempt identity; original retained')
    destination = data.get('destination')
    if state == 'prepared' and attempt is not None:
        raise ValueError('Prepared receipt already has an attempt; original retained')
    if state in {'prepared', 'dispatching', 'uncertain', 'failed'} and destination is not None:
        raise ValueError('Unresolved receipt contains a destination; reconcile instead of retrying')
    if state in {'failed', 'orphaned'} and (not isinstance(data.get('resolution_note'), str) or not data['resolution_note'].strip()):
        raise ValueError('Missing non-creation evidence; original retained')
    if state in {'queued', 'created', 'orphaned'}:
        key = 'threadId' if state in {'created', 'orphaned'} else 'clientThreadId'
        if not isinstance(destination, dict) or key not in destination:
            raise ValueError('Missing destination identity; original retained')
        if any(key not in {'threadId', 'clientThreadId', 'hostId'} or not isinstance(value, str) or not value.strip()
               for key, value in destination.items()):
            raise ValueError('Invalid destination identity; original retained')
        if state == 'queued' and 'threadId' in destination:
            raise ValueError('Queued receipt already has a ready task; reconcile first')
    return data


def read(path):
    return validate(json.loads(path.read_text(encoding='utf-8')))


def save(path, data):
    validate(data)
    data['updated_at'] = now()
    atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def prepare(path, packet, invocation_id, source_thread_id, source_workspace, destination_workspace=None):
    packet = Path(packet).resolve()
    identity = {'packet_path': str(packet), 'packet_sha256': hashlib.sha256(packet.read_bytes()).hexdigest(),
                'invocation_id': invocation_id, 'source_thread_id': source_thread_id,
                'source_workspace': str(Path(source_workspace).resolve())}
    if destination_workspace is not None:
        if not isinstance(destination_workspace, (str, Path)) or not Path(destination_workspace).is_absolute():
            raise ValueError('Destination workspace must be an absolute path')
        identity['destination_workspace'] = str(Path(destination_workspace).resolve())
    if not invocation_id or not source_thread_id:
        raise ValueError('Actual invocation and source task identities are required')
    with locked(path) as path:
        if path.exists():
            data = read(path)
            if any(data.get(key) != value for key, value in identity.items()):
                raise ValueError('Receipt identity conflicts; do not replace an existing invocation')
            return data
        data = dict(identity, schema=SCHEMA, created_at=now(), dispatch_state='prepared',
                    attempt_id=None, destination=None)
        save(path, data)
        return data


def claim(path):
    with locked(path) as path:
        data = read(path)
        if data['dispatch_state'] not in {'prepared', 'failed', 'orphaned'}:
            return {'may_create': False, 'receipt': data}
        packet = Path(data['packet_path'])
        if hashlib.sha256(packet.read_bytes()).hexdigest() != data['packet_sha256']:
            raise ValueError('Packet changed since preparation; do not dispatch it')
        if data['dispatch_state'] == 'orphaned':
            data.setdefault('orphaned_destinations', []).append({
                'destination': data['destination'], 'note': data['resolution_note'], 'recorded_at': now()})
        data.update(dispatch_state='dispatching', attempt_id=uuid.uuid4().hex, destination=None, resolution_note=None)
        save(path, data)  # Persist before giving the caller permission to invoke create.
        return {'may_create': True, 'receipt': data}


def finish(path, attempt_id, outcome, thread_id=None, client_id=None, host_id=None, note=None):
    if outcome not in {'created', 'queued', 'uncertain', 'not-created', 'not-persisted'}:
        raise ValueError('Unsupported outcome')
    if any(value is not None and (not isinstance(value, str) or not value.strip()) for value in (thread_id, client_id, host_id)):
        raise ValueError('Destination IDs must be nonempty strings')
    if outcome == 'queued' and thread_id:
        raise ValueError('A ready thread ID must use the created outcome')
    if outcome == 'created' and not thread_id or outcome == 'queued' and not client_id:
        raise ValueError('A verified destination identifier is required')
    if outcome in {'not-created', 'not-persisted'} and not note:
        raise ValueError('Record evidence that creation did not occur; a timeout is insufficient')
    if outcome in {'uncertain', 'not-created', 'not-persisted'} and (thread_id or client_id or host_id):
        raise ValueError('Uncertain/absent results cannot introduce a destination')
    with locked(path) as path:
        data = read(path)
        if not attempt_id or attempt_id != data.get('attempt_id'):
            raise ValueError('Stale or missing attempt; original retained')
        state = data['dispatch_state']
        if state not in {'dispatching', 'uncertain', 'queued', 'created'}:
            raise ValueError('No active dispatch to reconcile')
        if outcome == 'not-persisted' and state != 'created':
            raise ValueError('Only a created but conclusively absent destination can be marked orphaned')
        dest = data.get('destination') or {}
        for key, value in (('threadId', thread_id), ('clientThreadId', client_id), ('hostId', host_id)):
            if value and dest.get(key) and dest[key] != value:
                raise ValueError('Destination conflicts; original retained')
        if state == 'created' and outcome not in {'created', 'not-persisted'} or state == 'queued' and outcome not in {'queued', 'created'}:
            raise ValueError('Do not downgrade an existing destination')
        for key, value in (('threadId', thread_id), ('clientThreadId', client_id), ('hostId', host_id)):
            if value:
                dest[key] = value
        new_state = 'failed' if outcome == 'not-created' else 'orphaned' if outcome == 'not-persisted' else outcome
        data.update(dispatch_state=new_state,
                    destination=dest or None, resolution_note=note)
        save(path, data)
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'claim', 'show', 'finish'])
    parser.add_argument('--receipt', required=True)
    for flag in ('packet', 'invocation-id', 'source-thread', 'source-workspace', 'destination-workspace', 'attempt-id',
                 'outcome', 'thread-id', 'client-id', 'host-id', 'note'):
        parser.add_argument('--' + flag)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            if not all((args.packet, args.invocation_id, args.source_thread, args.source_workspace)):
                raise ValueError('prepare requires packet, invocation-id, source-thread and source-workspace')
            result = prepare(args.receipt, args.packet, args.invocation_id, args.source_thread,
                             args.source_workspace, args.destination_workspace)
        elif args.action == 'claim':
            result = claim(args.receipt)
        elif args.action == 'finish':
            result = finish(args.receipt, args.attempt_id, args.outcome, args.thread_id, args.client_id, args.host_id, args.note)
        else:
            with locked(args.receipt) as path:
                result = read(path)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, 'Dispatch stopped: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

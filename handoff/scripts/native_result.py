#!/usr/bin/env python3
"""Record an observed native create_thread result; never creates or retries a task.

Pass the actual tool result as JSON stdin. Only the known pre-execution
approval-policy conflict proves non-creation. Other errors stay uncertain.
"""
import argparse
import json
from pathlib import Path
import sys

import dispatch

APPROVAL_CONFLICT = 'MCP tool call requires approval, but approval policy is never'
IDENTIFIERS = ('threadId', 'clientThreadId', 'hostId')


def classify(result):
    uncertain = {'outcome': 'uncertain', 'reason': 'creation_result_uncertain',
                 'note': 'Native creation response is ambiguous; reconcile the existing attempt, do not create again.'}
    if not isinstance(result, dict):
        return uncertain
    payloads = [result]
    messages = []
    if isinstance(result.get('structuredContent'), dict):
        payloads.append(result['structuredContent'])
    for block in result.get('content', []) if isinstance(result.get('content', []), list) else []:
        if not isinstance(block, dict) or block.get('type') != 'text' or not isinstance(block.get('text'), str):
            continue
        message = block['text'].strip()
        messages.append(message)
        try:
            payload = json.loads(message)
        except ValueError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    # Conflicting, malformed or error-bearing identity is never a clean success.
    values = {key: [] for key in IDENTIFIERS}
    for payload in payloads:
        for key in IDENTIFIERS:
            if key in payload:
                value = payload[key]
                if not isinstance(value, str) or not value.strip():
                    return uncertain
                if value not in values[key]:
                    values[key].append(value)
    if any(len(v) > 1 for v in values.values()):
        return uncertain
    identity = {k: v[0] for k, v in values.items() if v}
    errors = [p['isError'] for p in payloads if 'isError' in p]
    if any(not isinstance(e, bool) for e in errors):
        return uncertain
    if any(errors):
        # Exact platform rejection, no returned identity. An arbitrary timeout,
        # review denial or embedded phrase does not establish non-creation.
        if not identity and messages == [APPROVAL_CONFLICT] and not any(
                'error' in p for p in payloads):
            return {'outcome': 'not-created', 'reason': 'approval_policy_conflict',
                    'note': 'Native create_thread was rejected before execution: ' + APPROVAL_CONFLICT}
        return uncertain
    if any('error' in p for p in payloads):
        return uncertain
    if 'threadId' in identity:
        return {'outcome': 'created', 'reason': 'created', 'thread_id': identity['threadId'],
                **({'client_id': identity['clientThreadId']} if 'clientThreadId' in identity else {}),
                **({'host_id': identity['hostId']} if 'hostId' in identity else {})}
    if 'clientThreadId' in identity:
        return {'outcome': 'queued', 'reason': 'queued', 'client_id': identity['clientThreadId'],
                **({'host_id': identity['hostId']} if 'hostId' in identity else {})}
    return uncertain


def failure_detail(result):
    """Keep a bounded excerpt of the observed error, without guessing its cause."""
    if not isinstance(result, dict):
        return result[:1600] if isinstance(result, str) else None
    payloads = [result]
    messages = []
    if isinstance(result.get('structuredContent'), dict):
        payloads.append(result['structuredContent'])
    blocks = result.get('content', [])
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or block.get('type') != 'text':
            continue
        message = block.get('text')
        if not isinstance(message, str) or not message.strip():
            continue
        try:
            payload = json.loads(message)
        except ValueError:
            messages.append(message.strip())
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
        elif isinstance(payload, str):
            messages.append(payload)
    for payload in payloads:
        error = payload.get('error')
        if isinstance(error, dict):
            error = error.get('message')
        if isinstance(error, str) and error.strip():
            messages.append(error.strip())
        message = payload.get('message')
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    return '\n'.join(dict.fromkeys(messages))[:1600] or None


def record(receipt, attempt_id, result):
    decision = classify(result)
    detail = failure_detail(result) if decision['outcome'] in ('uncertain', 'not-created') else None
    note = decision.get('note')
    if detail and detail not in (note or ''):
        note = (note or '') + ' Observed native response: ' + detail
    state = dispatch.finish(Path(receipt), attempt_id, decision['outcome'],
                            thread_id=decision.get('thread_id'), client_id=decision.get('client_id'),
                            host_id=decision.get('host_id'), note=note)
    guidance = {
        'approval_policy_conflict': (
            'Keep the packet, invocation and receipt. Full Access is not required: use an interactive '
            'approval policy (on-request, with user or auto_review) permitted by the host. '
            'Do not change settings automatically or switch to another creation interface. '
            'Retry the same saved request only after a verified permission change and a new claim.'),
        'creation_result_uncertain': 'Reconcile this attempt through native task evidence; do not retry creation.',
        'created': 'Take one native startup snapshot; creation alone does not prove continuation has started.',
        'queued': 'Report queued; clientThreadId is not a ready thread ID. Recover this same operation.',
    }[decision['reason']]
    return {'dispatch_state': state['dispatch_state'], 'destination': state.get('destination'),
            'reason': decision['reason'], 'guidance': guidance, 'may_create': False,
            **({'observed_error': detail} if detail else {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--attempt-id', required=True)
    args = parser.parse_args()
    try:
        result = record(args.receipt, args.attempt_id, json.load(sys.stdin))
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, 'Result recording stopped; retain the attempt and do not create again: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

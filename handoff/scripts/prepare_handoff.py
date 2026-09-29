#!/usr/bin/env python3
"""Publish a compact packet, history and claimed receipt in one local call.

Read the observed routing metadata and human-written summary from JSON stdin.
This helper never contacts Codex or creates a task. Only may_create=true from
this invocation authorizes the caller to make its one external creation call.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import dispatch
import history


def receiver_prompt(packet, project_id, destination, continuation):
    behavior = {
        'continue_now': '随后立即继续包内已授权下一步，不必等用户再说继续；不要扩写成新的大任务。',
        'wait_for_user': '说明包内实际缺失的输入，等待用户；不要自行开始依赖该输入的工作。',
        'complete': '工作已完成，简要确认保存的结果，不创造新的工作。',
    }[continuation]
    return (f'接续已有任务。读取交接包 {packet}；已核实 Local 项目 {project_id}，'
              f'接收 cwd：{destination}。核对实际 cwd 与已有项目元数据；冲突时报告并停止依赖写入，不另建任务。'
              '先用一条进度说明“上下文已接收；接下来……”；' + behavior
              + '保留包内审批、身份、访问边界、强制检查及共享改动；仅在使用相关文件前检查其当前状态。'
              '复用已有证据，区分用户决定与助手建议。无异常时不重查项目列表、读取 handoff 规则、'
              '扫描历史或写接收验收报告。不复制迁移代码，不自动再次 handoff。\n')


def prepare(plan):
    required = ('output_dir', 'workspace', 'source_thread_id', 'source_host',
                'invocation_id', 'project_id', 'title', 'summary', 'next_action')
    if not isinstance(plan, dict) or any(not isinstance(plan.get(k), str) or not plan[k].strip()
                                         for k in required):
        raise ValueError('Missing observed routing metadata, summary or next action')
    allowed = set(required) | {'history_dir', 'continuation', 'destination_workspace', 'model', 'thinking'}
    if set(plan) - allowed:
        raise ValueError('Unknown plan fields: ' + ', '.join(sorted(set(plan) - allowed)))
    plan = dict(plan)
    plan.setdefault('continuation', 'continue_now')
    if plan['continuation'] not in ('continue_now', 'wait_for_user', 'complete'):
        raise ValueError('Invalid continuation state')
    for key in ('model', 'thinking'):
        if key in plan and (not isinstance(plan[key], str) or not plan[key].strip()):
            raise ValueError(key + ' must be an explicit nonempty choice')
    if 'thinking' in plan and plan['thinking'] not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ValueError('Unsupported thinking value; check the current native schema')
    if plan['source_host'] != 'local':
        raise ValueError('This helper supports verified local-host projects only')
    for key in ('workspace', 'output_dir'):
        if not Path(plan[key]).is_absolute():
            raise ValueError(key + ' must be an absolute observed path')
        plan[key] = str(Path(plan[key]).resolve())
    workspace, output = Path(plan['workspace']), Path(plan['output_dir'])
    if not workspace.is_dir():
        raise ValueError('Source workspace does not exist')
    destination = Path(plan.get('destination_workspace', str(workspace)))
    if not destination.is_absolute() or not destination.is_dir():
        raise ValueError('Destination must be an existing absolute saved-project directory')
    destination = destination.resolve()
    if destination not in (workspace, *workspace.parents):
        raise ValueError('Source cwd is outside the saved destination project')
    if 'destination_workspace' in plan:
        plan['destination_workspace'] = str(destination)
    archive = Path(plan.get('history_dir', str(output / 'history')))
    if not archive.is_absolute():
        raise ValueError('history_dir must be absolute')
    archive = archive.resolve()
    for path in (output, archive):
        if destination not in (path, *path.parents):
            raise ValueError('Keep packet/history inside the verified workspace')
    plan['history_dir'] = str(archive)
    identity = json.dumps([plan['source_thread_id'], plan['invocation_id']], separators=(',', ':'))
    packet_id = 'handoff-' + hashlib.sha256(identity.encode()).hexdigest()[:24]
    output.mkdir(parents=True, exist_ok=True)
    packet = output / (packet_id + '.md')
    prompt_file = output / (packet_id + '.receiver-prompt.txt')
    receipt = output / (packet_id + '.receipt.json')
    request = output / (packet_id + '.request.json')
    target = {'type': 'project', 'projectId': plan['project_id'], 'environment': {'type': 'local'}}
    body = ('# ' + plan['title'] + '\n\n'
            + '- 来源任务：' + plan['source_thread_id'] + '\n'
            + '- Host：local；Local cwd：' + plan['workspace'] + '\n'
            + (('- 接收 cwd：' + str(destination) + '\n') if 'destination_workspace' in plan else '')
            + '- 本次调用：' + plan['invocation_id'] + '\n'
            + '- 已核实创建目标：' + json.dumps(target, ensure_ascii=False) + '\n'
            + '- 接续状态：' + plan['continuation'] + '\n\n'
            + '## 必要上下文\n\n' + plan['summary'].strip() + '\n\n'
            + '## 下一步\n\n' + plan['next_action'].strip() + '\n')
    prompt = receiver_prompt(packet, plan['project_id'], destination, plan['continuation'])
    encoded = (json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    # This lock covers publication and claim, not the external task creation.
    with dispatch.locked(output / (packet_id + '.prepare')):
        # Preserve rendering from older installed versions on same-input retries.
        # Check the frozen request BEFORE touching any history or output artifact.
        if request.exists():
            if request.read_bytes() != encoded:
                raise ValueError('Snapshot content conflicts; existing request retained. '
                                 'For a pre-claim legacy history conflict, use the documented receipt recovery.')
        history.publish_snapshot(packet, body.encode())
        # A history failure can leave a verified packet/prompt before request freeze.
        # Reuse that prompt across renderer upgrades only AFTER packet validation.
        if prompt_file.is_file():
            prompt = prompt_file.read_text(encoding='utf-8')
        history.publish_snapshot(prompt_file, prompt.encode())
        history.publish(archive, packet, packet_id, plan['title'], plan['source_thread_id'],
                        workspace=destination)
        # An incompatible archive must not freeze an otherwise recoverable request.
        history.publish_snapshot(request, encoded)
        dispatch.prepare(receipt, packet, plan['invocation_id'], plan['source_thread_id'], workspace,
                         destination_workspace=plan.get('destination_workspace'))
        result = dispatch.claim(receipt)
    record = result['receipt']
    create_args = {'target': target, 'title': plan['title'], 'prompt': prompt}
    create_args.update({key: plan[key] for key in ('model', 'thinking') if key in plan})
    return {'create_args': create_args, 'may_create': result['may_create'], 'packet': str(packet), 'receipt': str(receipt),
            'attempt_id': record['attempt_id'], 'dispatch_state': record['dispatch_state'],
            'destination': record.get('destination'), 'target': target, 'title': plan['title'],
            'prompt': prompt, 'prompt_file': str(prompt_file),
            'summary_characters': len(plan['summary']),
            'size_note': 'Consider linking existing detail instead of repeating it' if len(plan['summary']) > 1600 else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compact', action='store_true', help='Omit duplicated legacy creation fields from stdout')
    args = parser.parse_args()
    try:
        result = prepare(json.load(sys.stdin))
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit('Preparation stopped; retain this invocation and reconcile: ' + str(exc))
    if args.compact:
        for key in ('target', 'title', 'prompt'):
            result.pop(key, None)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

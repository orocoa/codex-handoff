import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import unittest
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import appserver_dispatch
import dispatch


class ProjectPages(unittest.TestCase):
    def test_repeated_cursor_fails_closed(self):
        class FakeRpc:
            def request(self, method, params):
                return {'data': [], 'nextCursor': 'repeat'}

        with self.assertRaisesRegex(RuntimeError, 'repeated Project list cursor'):
            appserver_dispatch.list_projects(FakeRpc())


class DetachedHandoff(unittest.TestCase):
    def test_second_project_page_and_detached_turn(self):
        root = Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd() / 'work' / 'handoff-appserver-tests'))) / uuid.uuid4().hex
        root.mkdir(parents=True)
        fake_codex = root / 'codex'
        fake_codex.write_text('''#!/usr/bin/env python3
import json, os, sys, time

def send(value):
    sys.stdout.write(json.dumps(value) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    params = request.get("params", {})
    if method == "initialize":
        result = {}
    elif method == "project/list":
        result = ({"data": [{"id": "other", "roots": [{"path": "/other"}]}],
                   "nextCursor": "page-two"} if not params.get("cursor") else
                  {"data": [{"id": "project-test", "roots": [{"path": os.environ["HANDOFF_FAKE_CWD"]}]}],
                   "nextCursor": None})
    elif method == "thread/start":
        with open(os.environ["HANDOFF_FAKE_COUNT"], "a") as stream:
            stream.write("start\\n")
        result = {"thread": {"id": "thread-test", "projectId": "project-test",
                             "cwd": os.environ["HANDOFF_FAKE_CWD"]},
                  "model": params["model"], "modelProvider": params["modelProvider"],
                  "reasoningEffort": params["config"]["model_reasoning_effort"],
                  "approvalPolicy": params["approvalPolicy"], "approvalsReviewer": params["approvalsReviewer"],
                  "sandbox": {"type": "dangerFullAccess"}, "runtimeWorkspaceRoots": params["runtimeWorkspaceRoots"]}
    elif method == "thread/name/set":
        result = {}
    elif method == "thread/read":
        result = {"thread": {"id": "thread-test", "projectId": "project-test",
                             "cwd": os.environ["HANDOFF_FAKE_CWD"], "name": "Next"}}
    elif method == "turn/start":
        result = {"turn": {"id": "turn-test"}}
    else:
        send({"id": request["id"], "error": {"message": "unexpected method"}})
        continue
    if method == "turn/start":
        time.sleep(float(os.environ.get("HANDOFF_FAKE_PRESTART_DELAY", "0")))
    send({"id": request["id"], "result": result})
    if method == "turn/start":
        if os.environ.get("HANDOFF_FAKE_CRASH_AFTER_START"):
            os._exit(7)
        gate = os.environ.get("HANDOFF_FAKE_TURN_GATE")
        if gate:
            deadline = time.monotonic() + 10
            while not os.path.exists(gate) and time.monotonic() < deadline:
                time.sleep(0.05)
        else:
            time.sleep(1)
        send({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
''')
        fake_codex.chmod(0o755)
        packet = root / 'packet.md'
        packet.write_text('# Goal\nContinue safely.\n')
        prompt = root / 'prompt.txt'
        prompt.write_text('Read packet.md and continue.')
        receipt = root / 'packet.receipt.json'
        dispatch.prepare(receipt, packet, 'invocation-test', 'source-test', root)
        attempt = dispatch.claim(receipt)['receipt']['attempt_id']
        source = root / 'source.jsonl'
        source.write_text(json.dumps({'type': 'session_meta', 'payload': {
                              'id': 'source-test', 'model_provider': 'observed-provider'}}) + '\n' +
                          json.dumps({'type': 'turn_context', 'payload': {
                              'cwd': str(root), 'model': 'source-model', 'effort': 'high',
                              'approval_policy': 'on-request', 'approvals_reviewer': 'user',
                              'sandbox_policy': {'type': 'danger-full-access'}, 'workspace_roots': []}}) + '\n')
        count = root / 'count.txt'
        env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ.get('PATH', ''),
                   HANDOFF_FAKE_CWD=str(root), HANDOFF_FAKE_COUNT=str(count))
        command = [sys.executable, str(SCRIPTS / 'appserver_dispatch.py'),
                   '--receipt', str(receipt), '--attempt-id', attempt,
                   '--packet', str(packet), '--project-id', 'project-test',
                   '--cwd', str(root), '--title', 'Next', '--prompt-file', str(prompt),
                   '--source-rollout', str(source), '--detach', '--startup-timeout', '10']
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        started = json.loads(result.stdout)
        self.assertEqual(started['event'], 'turn_started')
        self.assertEqual(started['threadId'], 'thread-test')
        log = Path(started['log'])
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and 'writer_released' not in log.read_text():
            time.sleep(0.05)
        self.assertIn('turn_completed', log.read_text())
        self.assertIn('verified_thread', log.read_text())
        self.assertEqual(count.read_text(), 'start\n')
        self.assertEqual(dispatch.read(receipt)['dispatch_state'], 'created')
        duplicate = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(count.read_text(), 'start\n')

        # Launcher timeout reports pending but leaves the worker alive to finish startup.
        pending_packet = root / 'pending-packet.md'
        pending_packet.write_text('# Goal\nContinue after slow startup.\n')
        pending_prompt = root / 'pending-prompt.txt'
        pending_prompt.write_text('Read pending-packet.md and continue.')
        pending_receipt = root / 'pending.receipt.json'
        dispatch.prepare(pending_receipt, pending_packet, 'invocation-pending', 'source-test', root)
        pending_attempt = dispatch.claim(pending_receipt)['receipt']['attempt_id']
        slow_env = dict(env, HANDOFF_FAKE_PRESTART_DELAY='2')
        slow_command = [sys.executable, str(SCRIPTS / 'appserver_dispatch.py'),
                        '--receipt', str(pending_receipt), '--attempt-id', pending_attempt,
                        '--packet', str(pending_packet), '--project-id', 'project-test',
                        '--cwd', str(root), '--title', 'Next', '--prompt-file', str(pending_prompt),
                        '--source-rollout', str(source), '--detach', '--startup-timeout', '1']
        pending = subprocess.run(slow_command, env=slow_env, capture_output=True, text=True, timeout=5)
        self.assertEqual(pending.returncode, 2, pending.stderr + pending.stdout)
        pending_event = json.loads(pending.stdout)
        self.assertEqual(pending_event['event'], 'startup_pending')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and dispatch.read(pending_receipt)['dispatch_state'] != 'created':
            time.sleep(0.05)
        self.assertEqual(dispatch.read(pending_receipt)['dispatch_state'], 'created')
        pending_log = Path(pending_event['log'])
        while time.monotonic() < deadline and 'turn_completed' not in pending_log.read_text():
            time.sleep(0.05)
        self.assertIn('turn_completed', pending_log.read_text())
        self.assertEqual(count.read_text(), 'start\nstart\n')

        # The source returns after startup; receiving work can finish later.
        long_packet = root / 'long-packet.md'
        long_packet.write_text('# Goal\nContinue the receiving work.\n')
        long_prompt = root / 'long-prompt.txt'
        long_prompt.write_text('Read long-packet.md and continue.')
        long_receipt = root / 'long.receipt.json'
        dispatch.prepare(long_receipt, long_packet, 'invocation-long', 'source-test', root)
        long_attempt = dispatch.claim(long_receipt)['receipt']['attempt_id']
        turn_gate = root / 'allow-long-turn-completion'
        long_env = dict(env, HANDOFF_FAKE_TURN_GATE=str(turn_gate))
        long_command = [sys.executable, str(SCRIPTS / 'appserver_dispatch.py'),
                        '--receipt', str(long_receipt), '--attempt-id', long_attempt,
                        '--packet', str(long_packet), '--project-id', 'project-test',
                        '--cwd', str(root), '--title', 'Next', '--prompt-file', str(long_prompt),
                        '--source-rollout', str(source), '--detach', '--startup-timeout', '10']
        long_result = subprocess.run(long_command, env=long_env, capture_output=True, text=True, timeout=15)
        self.assertEqual(long_result.returncode, 0, long_result.stderr + long_result.stdout)
        long_log = Path(json.loads(long_result.stdout)['log'])
        self.assertNotIn('turn_completed', long_log.read_text())
        turn_gate.write_text('continue')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and 'turn_completed' not in long_log.read_text():
            time.sleep(0.05)
        self.assertIn('turn_completed', long_log.read_text())
        self.assertEqual(dispatch.read(long_receipt)['dispatch_state'], 'created')
        self.assertEqual(count.read_text(), 'start\nstart\nstart\n')

        # A server crash is visible in the log and never authorizes a second creation.
        crash_packet = root / 'crash-packet.md'
        crash_packet.write_text('# Goal\nContinue after a failed monitor.\n')
        crash_prompt = root / 'crash-prompt.txt'
        crash_prompt.write_text('Read crash-packet.md and continue.')
        crash_receipt = root / 'crash.receipt.json'
        dispatch.prepare(crash_receipt, crash_packet, 'invocation-crash', 'source-test', root)
        crash_attempt = dispatch.claim(crash_receipt)['receipt']['attempt_id']
        crash_env = dict(env, HANDOFF_FAKE_CRASH_AFTER_START='1')
        crash_command = [sys.executable, str(SCRIPTS / 'appserver_dispatch.py'),
                         '--receipt', str(crash_receipt), '--attempt-id', crash_attempt,
                         '--packet', str(crash_packet), '--project-id', 'project-test',
                         '--cwd', str(root), '--title', 'Next', '--prompt-file', str(crash_prompt),
                         '--source-rollout', str(source), '--detach', '--startup-timeout', '10']
        crash = subprocess.run(crash_command, env=crash_env, capture_output=True, text=True, timeout=15)
        crash_event = json.loads(crash.stdout)
        crash_log = Path(crash_event['log'])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and '"event": "error"' not in crash_log.read_text():
            time.sleep(0.05)
        self.assertIn('"event": "error"', crash_log.read_text())
        self.assertEqual(dispatch.read(crash_receipt)['dispatch_state'], 'created')
        self.assertEqual(count.read_text(), 'start\nstart\nstart\nstart\n')
        duplicate_crash = subprocess.run(crash_command, env=crash_env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(duplicate_crash.returncode, 0)


if __name__ == '__main__':
    unittest.main()

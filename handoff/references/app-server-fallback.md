# App Server fallback and desktop ownership

Use this only for an explicit handoff when native `list_projects`/`create_thread` remain unavailable after checking the current tool catalog and any available tool search. A historical task's tool availability is not evidence about the current task. Native `project/local` creation avoids starting a separate writer process and is preferred.

The [official App Server protocol](https://learn.chatgpt.com/docs/app-server) documents `initialize` → `initialized`, `thread/start`, `turn/start`, and `turn/interrupt`. The fallback is a separate client: while it runs the first turn, the desktop may show **This is open in another app**. Starting a turn does not transfer its writer ownership to the desktop. Do not describe this as immediately interactive desktop continuation.

## Resolve and preserve the source

This fallback requires an effective `approval_policy = "on-request"`. It rejects `never`, retired policies and unsupported granular policies before starting an App Server or creating a successor. Do not silently convert the source policy; the user must select interactive permissions, then recover the same receipt. It does not replace or bypass a native approval rejection.

Use one read-only App Server connection (`codex app-server --stdio`) to initialize with `capabilities.experimentalApi: true`, read the exact source task using `thread/read`, and page `project/list` until the saved Local project is resolved. Match the actual source Project ID or a unique canonical root on this host, never just a label. Keep the same `projectId`; record the actual source cwd and the verified destination cwd separately. The destination defaults to the source for legacy receipts and uses `destination_workspace` when present; do not create a worktree or substitute projectless work. Close this routing connection after reading.

Record the exact source rollout `path` returned by `thread/read`. The dispatch helper's required `--source-rollout` argument verifies its `session_meta.id` against the receipt and its latest `turn_context.cwd` against the workspace. It preserves the observed model and `session_meta.model_provider`, reasoning effort, approval policy, approval reviewer, sandbox and explicit workspace roots. Missing provider or roots are unknown and rejected; an explicitly empty roots array remains empty and is verified in the effective response. These are per-thread settings, not edits to global configuration. Do not fabricate a source rollout or settings to obtain wider access. The helper rejects missing/unsupported contexts, named permission profiles and unsupported sandbox modes; use native dispatch or report the specific limitation. Respect any more restrictive current host or user constraints instead of copying older broader settings. For workspace-write, a destination above the source must already be covered by the observed source writable roots; changing cwd must not silently add writable scope. Unsupported cases require native dispatch or a precise limitation report, not broader permissions.

If the protocol rejects an expected field, inspect the installed schema with `codex app-server generate-json-schema --out <work-directory> --experimental` before adapting. Do not regenerate schemas or reread scripts on each successful handoff. Do not invoke unpublished desktop endpoints, database writes or UI automation to take writer ownership.

## Dispatch once

Prepare the packet, short receiver prompt, history and claimed receipt using [dispatch.md](dispatch.md), then run:

```text
python3 <skill-dir>/scripts/appserver_dispatch.py --detach \
  --receipt <receipt.json> --attempt-id <claimed-attempt> \
  --packet <packet.md> --project-id <verified-project-id> \
  --cwd <verified-local-directory> --title <receiver-title> \
  --prompt-file <receiver-prompt.txt> --source-rollout <verified-source-rollout.jsonl>
```

The helper verifies packet integrity, source settings and the fresh Project inventory, calls `thread/start` once, checks returned effective settings before sending work, then starts one turn. A settings mismatch is an error, never a reason to drop the checks or silently accept CLI defaults. An exclusive per-attempt worker claim prevents two foreground runners from using the same creation claim. Keep the receipt, log, runtime state and worker claim intact.

The launcher waits only for startup (30 seconds by default). `startup_pending` does not authorize a second launch; inspect the same attempt. A `created` receipt records the existing destination, even if its first turn later fails. It does not prove goal completion or desktop readiness. Source-task confirmation should take one bounded snapshot of the receipt/runtime state, then stop doing the transferred work.

## Run, release and report accurately

The worker writes a private `.runtime.json` beside the receipt, with the effective source context, task/turn IDs, state, errors and `writerReleased`. It retains the writer while healthy work runs; there is no arbitrary timer that kills a productive turn. After `turn/completed`, it verifies the saved project/directory and closes its own App Server. Only after that process exits does it write `writerReleased: true`. Another client may subsequently acquire the task, so this flag is evidence of this worker's release, not a guarantee of current desktop ownership.

A headless worker cannot present or answer interactive requests. On **any** server-initiated request (including command/file/permission approvals, user input, MCP elicitation and unknown future requests), it records `attention_required`, calls `turn/interrupt` for its own thread/turn with a total bounded wait, then closes its own server and releases the writer. A request explicitly identifying another thread/turn is recorded and releases this client without sending an interrupt or response to that other task. It never grants permission, supplies an invented answer, or changes sandbox settings to bypass the request. Interruption clears pending requests; the desktop may need to reissue the action after resumption. The existing task and history are retained, and the receipt remains `created`.

Report one of these observed states:

- **后台首轮已启动，桌面暂不可接管**: `running`, writer not released. Provide the existing task link and packet path.
- **需要人工处理，后台已释放**: `attention_required` with `writerReleased: true`. Explain the recorded request type and direct the user to the same task. Do not say the substantive work is finished.
- **首轮结束，后台已释放**: terminal state and `writerReleased: true`. Report the actual completed/failed/interrupted status; do not infer task completion from process exit alone.
- **启动待确认或失败**: explain the concrete receipt/runtime evidence, preserving the same attempt and any recorded task ID. Do not recreate on timeout.

Do not delete writer lock files or kill unrelated/previous clients. Updating the skill does not change already-running workers; recovery of an old blocked task is a separate operation. No automatic fallback to `codex exec`, TUI or `codex mcp-server`: these do not establish saved desktop Local Project membership.

RPC deadlines cover sending, buffered messages and notification traffic. A failed turn preserves its structured `turn.error` in the private runtime; creation identity remains unchanged. Client version is read from the installed VERSION file. Protocol fixtures were checked against codex-cli 0.158.0-alpha.2.1; supported fields still need verification after a CLI update.

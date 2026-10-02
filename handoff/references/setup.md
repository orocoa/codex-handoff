# Codex desktop scope and local setup

This skill is for Codex desktop with shared access to the source files. It prefers native task tools; when absent, the documented Codex App Server protocol can create a project-aware Local thread as described in [app-server-fallback.md](app-server-fallback.md). macOS is the tested platform. Python 3.9+ is required for bundled helpers; they use POSIX `fcntl` locking. Windows and remote/cross-device task transfer are not supported by this tested configuration. Do not emulate desktop tasks with a standalone CLI or `codex exec` process.

Install the complete `handoff/` directory in the user's configured Codex skills directory. Do not replace an existing directory without inspecting it. Start a fresh task or refresh skill discovery if necessary. In a supported saved Local project, select **Codex 任务交接** or send `$handoff` alone to prepare the handoff and start one new conversation there; no additional operation or confirmation is needed. If that destination cannot be verified or created, the skill reports the blocker instead of claiming success. `$handoff 帮我交接` remains equivalent. There are no separate record-only modes. Ordinary mentions and quoted examples do not activate this skill. This policy does not redefine unrelated native Codex task-management commands.

## Permissions and recovery

Full Access is not a skill requirement. Filesystem access and MCP approval are separate controls. Native handoff needs a writable packet/history/receipt directory inside the verified project, access to the native task tools, and permission to execute those tools. A saved `config.toml` does not establish the current turn's policy. Native preparation does not inspect either setting; consult effective permissions only to diagnose an actual returned failure. The Full Access preset uses `danger-full-access` plus `never`; it is not the Auto-review preset. A correctly saved `on-request` / `auto_review` configuration can therefore coexist with an active chat that still reports `never`. Changing the saved file again does not establish a change in that active chat.

| Effective mode | Handoff behavior |
| --- | --- |
| `workspace-write` + `on-request`, reviewer `user` | Save inside the writable project and use the normal native tool approval if required. Full Access is unnecessary. |
| `workspace-write` + `on-request`, reviewer `auto_review` | Same file boundary; eligible MCP requests can go through automatic review. Approval is not guaranteed. |
| `workspace-write` + `never` | Save and claim one native attempt; invoke the tool rather than preemptively stopping. The host executes allowed tools and rejects tools that require unavailable approval. |
| `read-only` | The complete workflow needs scoped permission for project writes plus native tool permission. Without those, packet preparation cannot complete. Do not silently write elsewhere or switch to Full Access. |
| Full Access | Removes the filesystem boundary; separate tool, managed-policy or access restrictions may still apply. Do not treat it as a universal success guarantee. |

For an interactive setup, a user can select **Ask for approval** or **Approve for me / Auto-review** in the app's permissions control. Enabling a mode in settings alone does not select it for an existing chat. An optional persistent user configuration is:

```toml
sandbox_mode = "workspace-write"
approval_policy = "on-request"
approvals_reviewer = "auto_review" # Use "user" for manual approval instead.
```

These are setup choices, not settings the skill changes as a side effect. Reload/select the effective permissions before recovery. Organization requirements may constrain the choices. Codex also documents per-tool MCP/plugin approval overrides; use only the host's verified tool identity and supported controls if the user explicitly requests such an override. Do not invent a server/plugin ID, approve all tools, or claim a local override defeats managed requirements.

Native handoff does not set an approval policy. The optional App Server adapter preserves the observed supported scalar policy (`on-request` or `never`) and verifies that the new task returns the same setting; it does not require enabling approvals or silently change permissions. Missing, retired or granular policy shapes that this adapter cannot preserve require the native path. See the [official App Server thread/start example](https://learn.chatgpt.com/docs/app-server), which uses `never`.

The native path has no skill-level approval preflight. Invoke `prepare_handoff.py --compact` with the verified project and summary; preparation takes no approval-policy or sandbox-mode input. A fresh receipt claim permits one native creation call in the same turn, followed by startup confirmation. The native host enforces its own actual permissions. Do not stop after saving or require a second handoff prompt. Already queued/created/dispatching/uncertain operations cannot be recreated. Recover an old unclaimed prepared receipt from its same frozen request; no new invocation is needed. Permission/access denials are handled only after the tool actually returns them; report the observed reason and do not bypass them. Older callers must remove the retired `--approval-policy` / `--sandbox-mode` flags (or corresponding Python keyword arguments); the frozen request JSON is unchanged.

Normal preparation writes only inside the project, not under the installed skill or global `~/.codex` state. If the source cwd is a nested directory and only that subtree is writable, choose its `work/handoffs` before freezing the request while keeping the verified saved-project root as `destination_workspace`. Do not move a frozen invocation to another directory to evade an access failure. Protected `.codex`, `.git` and `.agents` directories are unsuitable output locations.

When the native tool reports exactly **MCP tool call requires approval, but approval policy is never**, `native_result.py` records the proven pre-execution rejection as `failed` and explains the conflict. It preserves the packet and invocation and does not issue a retry claim. After a verified, user-authorized effective permission change, submit the original saved `.request.json` to `prepare_handoff.py`; only a new `may_create: true` allows one retry. For a denial, timeout, unknown error, malformed result or returned identity mixed with an error, the helper records `uncertain`; reconcile with native task evidence instead. Do not use the App Server fallback, CLI, a different tool or UI to bypass an approval/access denial. That fallback applies only when native capability is genuinely unavailable.

Official sources, checked 2026-10-02: [permission modes](https://learn.chatgpt.com/docs/permission-modes), [automatic review including MCP tools](https://learn.chatgpt.com/docs/sandboxing/auto-review), and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference). These establish supported approval mechanisms, not a guarantee that every host or organization permits native task creation. Local sandbox and script checks do not prove a live restricted-mode handoff; report those evidence levels separately.

## Optional compaction advisory

The core handoff needs no hook or background monitor. Without the optional configuration below, it does not proactively remind the user about compaction. To opt into a best-effort reminder, add an instruction to the user's chosen global/project AGENTS.md, using the real installed script path:

> At the first tool-using turn and after recovering from compaction, run `python3 <absolute-skill-dir>/scripts/context_check.py --claim-notice`. Use the actual current task ID; do not select by recency. If `remind` is true, briefly report the observed count and suggest selecting the handoff skill or sending `$handoff`, then continue the substantive work. A reminder never authorizes task creation. Unavailable data must not block work or produce an invented count.

Default threshold is two observed canonical compaction records, then every additional two. This counts local JSONL records, not context percentage or lost facts. The local transcript format may change. State defaults to `$CODEX_HOME/handoff-state` (or `~/.codex/handoff-state`), stores notice IDs/counts and private scan checkpoints (file identity, complete-line offset, prefix/compaction-key hashes; no message text), and can deduplicate a reminder before it is displayed; an interruption may therefore suppress that particular notice. There is no guaranteed background popup. With `--claim-notice` or explicit `--state-dir`, logs below 4 MiB use the direct scan without cache I/O; for larger logs repeat scans validate the entire previous prefix hash and JSON-decode only new complete lines. Replacement, truncation, changed prefixes or invalid cache cause a full scan. Busy/unwritable cache falls back to full scanning; unwritable notice state may repeat a reminder. Plain diagnostics without either option remain read-only.

## Data and removal

History contains full handoff packets, task IDs and file paths. New snapshots and dispatch receipts use private file permissions. Local Python helpers do not contact a network service; Codex's normal model processing is separate. Review project archives before committing them to a public repository. Removing the skill and the optional AGENTS.md instruction disables future use; retain handoff history and notice state unless the user explicitly asks to delete them.

## Fast native preparation

The default native path reads only SKILL.md. `prepare_handoff.py` accepts verified routing metadata plus a short summary on stdin, then saves the packet, receiver prompt and history before freezing the immutable request and claiming the receipt in one local call. It distinguishes source cwd from destination cwd and returns `create_args` for the native tool. The recommended `--compact` option omits duplicate legacy top-level creation fields from stdout; the default output and Python return keep those fields for existing callers. It never creates a task itself. Tests cover concurrent callers, retries after an uncertain outcome, conflicting input/history, same-workspace output and retaining long critical summaries without truncation. The claim and recovery protocol remain unchanged. Same-input retries keep the original prompt across upgrades after verifying the packet, including a pre-freeze history failure and avoid rewriting identical content, while still completing directory synchronization and rebuilding a missing generated index. End-to-end model latency is not measured by these local tests.

## Reproducible script checks

```text
python3 -m unittest discover -s <absolute-skill-dir>/tests -v
```

Tests locate scripts relative to their own files. Fixtures are preserved under the current directory's `work/` by default; set `HANDOFF_TEST_ROOT` to an explicit test-artifact directory if desired. Tests use synthetic data; one subprocess is deliberately killed to verify interrupted snapshot publication. No test creates a Codex task, modifies a real project or makes network calls.

App Server simulations also cover source model/permission preservation, rejection of mismatched effective settings, approval/input/elicitation/unknown requests, writer release, server/client request-ID collisions, and duplicate-runner prevention. They never grant permissions or create a real task. The fallback retains a writer while its first turn runs; see [app-server-fallback.md](app-server-fallback.md) for desktop availability and recovery limits.

Script tests cover local file/state behavior. Native discovery, live model routing and receiving-task behavior need separate app-level evidence. In particular, a fake adapter's dropped-response test does not emulate all Codex server failures.

Native-result regressions also cover ready/queued identities, the exact non-interactive approval conflict, ambiguous errors, retained error messages, conflicting identities and stale attempts. App Server simulations verify that `never` is retained in both creation and turn startup, without issuing an approval response. They do not execute a live MCP tool or approve anything.


## Local routing regression

Before every creation, read the fresh native Project inventory, including for non-Git directories. `resolve_target.py` plans only `project/local`; it does not register or dispatch a task. Tests cover Git and non-Git Local projects, nested paths, duplicate matches, same-name/other-host projects, title stability and rejection of a different source checkout. A real Git fixture verifies that nested repositories cannot be mistaken for the saved root. A linked checkout outside the saved Local root is rejected rather than reused through another working directory. Test fixtures remain in `work/`.

Local-only continuation is this skill's deliberate scope. There are no directory-mode flags; removed flags fail argument parsing. Tests validate the local plan, while live placement and immediate continuation still require the native task tools and the receiving task's verification.

When a historical directory disappears, first recover the current location from fresh project records and the observed workspace as described in destination.md. Validate both an updated same-ID path and the unresolved case where the provider still points only to the missing path; do not bypass checkout checks or register a substitute project during a test. A stale packet's previous blocker is not a current routing result.

Regression checks also cover source/destination cwd integration, archive correction before freezing, snapshot symlink boundaries, canonical receipt/worker aliases, absolute RPC deadlines under notifications, model provider identity, explicit empty roots, and compaction cache invalidation. Benchmarks measure local functions with synthetic data; do not claim a model or whole-handoff latency improvement from them.

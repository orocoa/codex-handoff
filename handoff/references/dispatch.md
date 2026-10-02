# Local receipt protocol for Codex desktop

Normal native preparation uses `prepare_handoff.py` to publish the packet/history and call prepare/claim in one local operation. Read this detailed protocol for manual fallback, queued/ambiguous creation or recovery; it is not a mandatory read on every handoff. The receipt and no-blind-retry invariants are unchanged. The optional `destination_workspace` records a saved-project root distinct from a nested source cwd; older receipts without it retain source-as-destination semantics. For manual prepare, use `--destination-workspace` when those directories differ. Receipt paths are canonicalized before locking; hard-linked receipt files are rejected instead of split by atomic replacement.

Use the actual installed skill path. Replace placeholders with observed values; these examples are not authorization to create tasks. First satisfy the explicit invocation gate in SKILL.md, write and verify the packet and history, resolve the actual Project and title using [destination.md](destination.md), record the exact intended native `target`/`title`, source/destination cwd and selection evidence in the immutable packet, then prepare a receipt next to the packet. Copy those values into the native call; the receipt does not itself route a task to a Project.

```text
python3 <skill-dir>/scripts/dispatch.py prepare --receipt <receipt.json> --packet <packet.md> --invocation-id <stable-current-request-id> --source-thread <actual-id> --source-workspace <absolute-path>
python3 <skill-dir>/scripts/dispatch.py claim --receipt <receipt.json>
```

Use a real request/turn ID when available; otherwise generate a unique invocation ID once and save it with this packet. Recover it from the receipt on retries. Do not use a fresh timestamp/receipt for each attempt. A different user invocation can create a different receipt.

`claim` atomically persists `dispatching` and an `attempt_id` under a file lock. If `may_create` is false, recover the stored operation; do not call create. If true, use the returned attempt ID and make at most one `create_thread` or App Server `thread/start` call. Receipt persistence must succeed before the creation call. Inspect the actual current tool/protocol schema and its authorization requirements.

Record an actual result:

```text
python3 <skill-dir>/scripts/dispatch.py finish --receipt <receipt.json> --attempt-id <returned-attempt> --outcome created --thread-id <returned-threadId> --host-id <returned-hostId>
```

Omit host-id if unavailable. For setup pending use `--outcome queued --client-id <returned-clientThreadId>`. The client ID is not a ready task ID. After matching that queued operation to a ready task, finish the same attempt with `created`; the client ID is retained. Never replace a recorded destination with another one.

For a timeout or interrupted/ambiguous response, use `--outcome uncertain --note <observed-failure>`, or leave the already durable `dispatching` state if interrupted. Neither state can be claimed again. Search native `list_threads`/`read_thread` results for the exact unique packet marker and source task; verify the actual initial prompt and environment when available. A single verified match can be recorded as created. Zero matches in a limited listing, elapsed time, or a title resemblance do not prove absence. Multiple matches or inability to verify leave the operation unresolved; report the specific issue and retain the packet. Do not automatically create a replacement.

Only a conclusive pre-creation rejection or other verified evidence that no task was created allows `--outcome not-created --note <specific-evidence>`. This moves to `failed`, from which a new claim yields a new attempt token. Old attempt results cannot alter a new attempt. The helper cannot verify whether a human-written note is true: evaluating the tool evidence remains the agent's responsibility. It does not grant additional authorization for a retry.

For the App Server stdio fallback only, `thread/start` can return a live ID before a turn has been persisted. If that process exits before `turn/start` and a fresh App Server connection confirms both `thread/resume` reports **no rollout** and a comprehensive `thread/list` has no matching ID, the prior `created` receipt may be finished with `--outcome not-persisted --note <these exact observations>`. This keeps the lost ID in `orphaned_destinations`; the next `claim` can then authorize one replacement attempt under the same invocation. Never use this exception for a timeout, an active process, a thread with any turn, or a merely missing item in a limited listing. Do not edit the receipt by hand.

Use `show --receipt <receipt.json>` to inspect state. Corrupt/older-schema receipts fail closed and stay intact; reconcile them from the packet and native tool evidence instead of overwriting. Do not use this helper to rewrite a historical receipt.

The guarantee is local and conditional: cooperating callers using the same receipt get one claim per unresolved attempt. There is no transaction spanning the file and Codex's external task creation. If creation succeeds but saving its result fails, the earlier dispatching state prevents blind retries. The receipt is not a substitute for task verification, and simulation tests do not prove the real app will never duplicate a task.

## Native result recording

The fast path can pass the actual `create_thread` MCP result as JSON stdin to `native_result.py --receipt ... --attempt-id ...`. The helper calls this receipt protocol, not an external creation API. It recognizes ready and queued identities and the exact known pre-execution `approval policy is never` rejection. An error with any returned identity, conflicting payloads or an unknown failure stays `uncertain`; it never guesses non-creation from a missing ID. A failure to record a result does not permit a new creation call.

For failed or uncertain results, the helper retains a bounded excerpt of the returned error in the attempt note and returns it as `observed_error` when available. This is observed evidence, not a diagnosis: redact sensitive details in the user-facing report, and state that the root cause is unknown when the tool does not explain it. A retained error message does not authorize another creation attempt.

The known policy conflict is `failed`, not an automatic-review denial. Recovery needs a verified permission change plus a new claim under the same saved request. An unresolved attempt or existing destination cannot be replaced just because settings changed. See [setup.md](setup.md#permissions-and-recovery) for supported restricted modes and their limitations.

## App Server runtime state

Creation identity and execution state are separate. A `created` receipt remains immutable evidence of the destination even when its first turn later fails or needs input. Read the same attempt's `.runtime.json` for `state`, `threadId`, `turnId`, `writerReleased`, and any `requestMethod`/error. A startup response is not evidence that the desktop can resume the task. The helper closes its own App Server after completion, failure, or an interactive request, and records `writerReleased: true` only after that process exits. This does not prove another client has not since acquired the task.

If `attention_required`, report the request type and the existing task link. Do not approve on behalf of the user, auto-resume the same blocked action, delete lock files, kill another client's process, or create a replacement. An `uncertain` receipt plus a runtime thread ID after a startup/settings failure must be reconciled against that same ID; no blind retry. Existing workers launched before a skill update retain their loaded code; updating the skill does not recover them.

## Legacy preparation stopped before claim

New preparation freezes `.request.json` only after packet/prompt/history publication succeeds. A known incompatible history directory can therefore be corrected under the same invocation/output before freezing; packet, summary and other identity fields remain fixed. A retry across a skill update reuses the saved receiver prompt instead of rendering new wording into the existing invocation.

For an older request already frozen by a pre-claim history failure, preserve every existing file. First establish from the observed failure and receipt state that no creation claim was issued; a merely missing file is not proof that a task was never created. If uncertain, use normal reconciliation above.

When that pre-claim failure is established, record the corrected archive path, original request path, actual source cwd and verified destination cwd in a new immutable correction note next to the packet. Publish the unchanged packet using `history.py` with the corrected archive and the original packet ID/title/source. If the legacy packet/prompt treats a nested source cwd as the receiving cwd, also save a new immutable recovery prompt beside it. Point that prompt to both the unchanged packet and the correction note; explicitly say that the old cwd is source-only and that receiver verification uses the note’s destination cwd. Preserve the original prompt and send the recovery prompt in this creation. Reuse a correct existing prompt only when it already agrees with the fresh destination. Retain any currently evidenced, explicit user model/thinking choice in the native creation arguments. Then use `dispatch.py prepare` and `claim` with the original receipt path, packet, invocation and source; pass a verified destination workspace if it differs. Only this new successful claim permits the one creation call. Continue through the same receipt, not through a rewritten request or a replacement invocation. The old request continues to document the rejected archive choice; the correction note documents the actual archive.

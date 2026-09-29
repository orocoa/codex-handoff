# Project continuity at a user-requested handoff

Combine a focused next-task packet with persistent, inspectable project history. Run this preparation as part of the direct handoff workflow when the user explicitly selects the skill or invokes `$handoff`. No separate operation text is needed. It is not an always-on memory collector.

## Recover and update

1. Look for existing project handoff or decision documents at known locations first: `AGENT_HANDOFF.md`, `HANDOFF.md`, `docs/handoffs/`, and the workspace's output/handoff directory. Reuse the applicable scheme; do not install a competing project framework or rewrite unrelated AGENTS.md rules.
2. Read the latest relevant state and follow selected decision/evidence references. Preserve why the approach was chosen, not just the latest task list. Do not rescan all old transcripts or all project files. A newer summary does not automatically cancel an older user decision.
3. Build the current packet with objective, completed/in-progress/blocked state, decisions and reasons, open questions, evidence, verification, workspace state and next actions. Record a changed decision only with the real user source or label it a proposal. Preserve rejected alternatives only when useful to the continuation goal.
4. Reconcile stale statements against actual files and this conversation. Keep old snapshots as history and put corrections in a new snapshot; do not rewrite old evidence to make it agree with the current answer. Unknown or inaccessible evidence stays unknown.

## Persistence without a memory service

If the project already has a maintained handoff index, add the new packet by that scheme and preserve its manual content. Honor an existing designated location. Without one, put preparation files under the verified project root’s `work/handoffs/`, and history under that output directory’s `history/`. An established `docs/handoffs/` or `outputs/handoffs/` archive remains valid; pass it explicitly as `history_dir` rather than starting a second archive. Keep this archive tied to the original project and pass its absolute path to later tasks so each new task does not create a disconnected archive.

After the packet is written, use the bundled helper with explicit arguments:

```text
python3 <skill-dir>/scripts/history.py --archive <project-history-directory> --packet <packet.md> --packet-id <unique-stable-id> --title <meaningful-title> --source-thread <actual-task-id>
```

The helper retains the original packet, saves an immutable historical snapshot, keeps a complete catalog, and limits the generated index to eight recent links. It never discards historical snapshots. Same-ID/same-content retries are idempotent; a changed packet needs a new ID. It refuses to overwrite a manual index. If that occurs before the request is frozen or claimed, keep the invocation/output identity and choose a distinct history subdirectory; do not delete the manual document. For an older frozen request, use the pre-claim recovery in dispatch.md. Never amend an already claimed request to bypass a conflict.

Snapshots are written privately to a temporary file, synced, then published without replacing an existing file. If catalog or generated index writing fails, retry the same command: a complete snapshot can be registered and the generated index rebuilt. A killed process may leave a hidden temporary file; keep it for diagnosis. If an older version left a partial final snapshot, preserve it and use a new packet ID with a correction note, or ask the user before moving/deleting the conflict. Do not silently overwrite it. The archive is local history, not a portable backup; packet references and catalog metadata can contain absolute paths.

This provides history navigation and index compaction, not a guarantee that every past conversation detail was captured. Substantive reasons and references must be present in the packet itself. Existing important decision documents remain the place to verify project rules.

## Before automatic dispatch

Verify the packet, required referenced paths, archive index and receipt. Then follow SKILL.md to create the successor directly in the same invocation. The user should not need to send another “now create it” message or copy a startup prompt. A standalone skill selection or `$handoff` already requests this creation. Do not offer separate saving, updating or checking modes; those are preparation steps before dispatch.

The receiver reads the packet and the relevant project-history references, checks current workspace state, and performs the authorized next step. The source reports its substantive outcome and the new task link. The receiver must not automatically repeat handoff.

The actual snapshot directory must remain inside the verified workspace (or the archive for standalone history calls). Existing links within that boundary may be used; links outside it are rejected without moving or removing them. Identical retries skip temporary writes/catalog replacement while retaining directory synchronization and missing-index repair.

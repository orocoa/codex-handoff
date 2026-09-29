# Compact continuation, not a second project report

The normal native path uses `prepare_handoff.py` from SKILL.md; this page is only for a difficult summarization/evidence decision or a manual fallback packet. Do not load it on every switch.

The summary is a minimum sufficient continuation, normally 300–800 Chinese characters or a similarly short passage in the user's language. This is a drafting target, not truncation: retain critical decisions, identity constraints, permissions, unresolved choices and material evidence even if it needs more space. Link existing source reports instead of recreating them. Preserve every original file.

Include:

- The actual goal and latest correction, without reviving abandoned directions.
- What the user decided versus what the assistant merely proposed; pending choices stay pending.
- What is complete, underway and still needed, distinguishing implemented from tested.
- Scope/approval/access constraints, shared modifications or active processes that affect the next step.
- Only the paths needed to continue, plus a concrete authorized next action and its existing completion standard.

`prepare_handoff.py` adds source identity, source/destination cwd, exact native target, continuation state and immutable history automatically. Do not repeat these fields throughout the summary or prompt. The caller is responsible for fresh Project verification; the local script does not query Codex or prove routing correctness.

Do not attach a full Git status listing, broad file inventory, new manifest, evidence audit or new acceptance report just to hand off. Record a small read-only check only when an identified material risk makes it necessary, or preserve an existing required check. The receiver checks relevant files before relying on or modifying them, not every project artifact before saying it has received the context. If a required file is missing or changed, report the actual mismatch and stop dependent work; do not treat the summary as proof of current file contents.

For a manual App Server packet, record the exact `projectId`, cwd and source rollout path, and follow app-server-fallback.md's settings and ownership checks. Do not use the native helper's `target` as App Server RPC parameters.

# Receiver contract

The helper generates a short prompt pointing to the packet. Keep it unchanged unless the task has a material additional constraint; do not paste the entire packet into it. The receiver should:

1. Read the packet and confirm actual cwd against its destination cwd; compare Project metadata if already exposed. On a concrete mismatch, stop dependent writes and report it. Do not make fresh project-list or self-read calls solely to repeat the sender's matching evidence.
2. Give a brief progress update that the context was received and name the concrete next action, then immediately continue existing authorized work in the same turn. This is a phase change, not a final answer requiring another user message.
3. Reuse existing evidence, read detailed files as needed, and respect checks before dependent operations. Do not read handoff implementation, scan full history, or generate an intake report as a routine step.

`continue_now` does not authorize extra research, specification documents, installation, modeling or other new deliverables beyond the existing task. If a lengthy deliverable was already authorized, it may continue; make clear that this is substantive work after receipt. `wait_for_user` requires a genuine missing input or explicit user instruction. `complete` confirms finished work without inventing a follow-up goal. None of these states authorizes recursive handoff.

# Design references checked 2026-09-12

This skill was authored for an explicit, same-Local-project Codex desktop workflow; it does not install or execute any third-party repository scripts.

- https://github.com/klittle32/handoff-skill — goal-focused transfer packet and evidence pointers; its documented receiver flow still requires starting a session and pasting a prompt. Adopt the focused packet idea; replace manual delivery with native Codex task creation. Do not adopt its temporary-file disposal behavior.
- https://github.com/codagent-ai/agent-skills/blob/main/skills/handoff/SKILL.md — concise objective, state, decisions, open questions and next actions. The example saves a summary only. Our version verifies the few relevant workspace facts and sends the packet to the receiver.
- https://github.com/WeirdSky924/agent-handoff-skill/blob/main/SKILL.md — durable repository handoff documents and evidence-based continuation. The expanded version adds project-history snapshots, a compact index, and review/correction instructions. Its cross-platform bootstrap and Claude hooks remain outside this Codex-specific request and are not installed.
- https://github.com/timyeou1234/context-handoff — also creates fresh Codex threads when supported and verifies workspace compatibility; its lifecycle hook detects compaction. Direct thread creation and verification are therefore not unique in isolation. This skill combines explicit one-call transfer, exact saved Local project routing, a no-hook core, durable project history and a creation receipt.
- https://learn.chatgpt.com/docs/build-skills — explicit invocation policy and skill discovery.
- https://learn.chatgpt.com/docs/hooks — Stop blocking creates a continuation prompt, and custom hooks require trust. This implementation avoids lifecycle hooks entirely.

Desktop dispatch behavior is defined by the live `create_thread`/`list_projects`/`wait_threads` schemas. Re-read those schemas at use time. A skill cannot by itself guarantee background scheduling or a hard context threshold. The global advisory instruction plus local script is best effort, runs only when Codex follows that instruction, and uses observed canonical `compacted` JSONL records rather than guesses about token pressure.

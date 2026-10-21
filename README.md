# Handoff — Codex conversation handoff

**One command. New thread. Keep going.**

[简体中文](README.zh-CN.md)

A **macOS Codex desktop** skill for Chinese- and English-speaking users who do not want to copy-paste context: hand work into a fresh chat inside the same saved **Local** project, with the necessary context already packed.

## Usage

In a saved local project, type `@handoff` (or the Chinese trigger `@任务交接`), select the **Codex task handoff** skill, and send. Or run:

```text
$handoff
```

The skill verifies the project, writes a handoff record, opens the continuation thread, and returns the new chat link plus the actual launch status. You do not need to say “continue.”

- Carries goals, latest decisions, done / todo, constraints, file paths, and evidence.
- Original files stay in place; necessary context goes into the new prompt; the receiver reads files as needed.
- Handoff runs only on explicit invocation — not on casual mentions, edits, or skill tests.

## Install

Requires **macOS Codex desktop**, **Python 3.9+**, a **saved local project**, plus write access and native project/chat tool permissions.

Ask Codex to install the full `handoff/` directory:

```text
$skill-installer Install handoff from https://github.com/orocoa/codex-handoff/tree/main/handoff .
If an install already exists, back it up and update that directory instead of creating a duplicate.
```

Current source is **alpha** (see repo `CHANGELOG.md` for the exact build). The link above installs `main`.

## Boundaries

Handoff also compresses information; summary quality depends on the source agent. You choose when to switch and what state to carry; a new thread does not guarantee zero drift. Stay in the original thread when you still need continuous fine detail.

Faster continuation is a design goal; wall-clock speed versus alternatives has not been measured. The skill does not add a separate approval layer or change permissions by itself. On create failure or unclear results it keeps records and explains the cause instead of blindly retrying.

## More

[Setup & recovery](handoff/references/setup.md) · [Changelog](CHANGELOG.md) · [Benchmarks](docs/benchmarks.md) · [Related work](docs/related-work.md) · [MIT License](LICENSE)

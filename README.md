# Handoff

**One command. Fresh chat. Keep going.**

[简体中文](README.zh-CN.md)

A task-continuation skill for **Codex desktop**. Send `$handoff` to create a fresh chat in the same saved **Local project**, carrying the state needed to continue. Once started, the successor resumes the next step you already authorized.

Built for long conversations and phase changes: reduce interference from old history and skip copying summaries, pasting prompts, and explaining the work again.

## Use

In a saved Local project, select the Handoff skill or send:

```text
$handoff
```

The skill verifies the project, saves the handoff record, creates a successor, and returns its link and observed startup state. No second “continue” message is needed.

- Carries the goal, latest decisions, completed and remaining work, essential constraints, file paths, and evidence.
- Keeps original files in place. Necessary context is inline in the new prompt; the receiver reads files as the work requires.
- Runs only on explicit invocation. Mentions, edits, and skill tests do not create a chat.

## Install

Requires **macOS Codex desktop, Python 3.9+, a saved Local project**, workspace write access, and access to native project/thread tools.

Ask Codex to install the complete `handoff/` directory:

```text
$skill-installer Install handoff from https://github.com/orocoa/codex-handoff/tree/main/handoff.
If already installed, back up and update the existing directory; avoid duplicate installations.
```

Current source: **alpha.18**, with 180 local regression tests passed. The release archive remains alpha.17. The link above installs source from `main`.

## Limits

Handoff also compresses information, and summary accuracy depends on the sending agent. You control when to switch and which necessary state to carry. A fresh chat does not guarantee freedom from drift; staying in the same chat can suit work that still depends on continuous detail.

Fast continuation is the design goal; whole-handoff latency and comparative speed have not been measured. The skill adds no approval gate and does not change permissions. Failed or uncertain creation retains the record and reports the observed reason, avoiding blind duplicate creation.

## More

[Setup and recovery](handoff/references/setup.md) · [Changelog](CHANGELOG.md) · [Measurements](docs/benchmarks.md) · [Related projects](docs/related-work.md) · [MIT](LICENSE)

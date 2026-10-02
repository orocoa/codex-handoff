# Handoff

**Fresh chat. Same project. Keep going.**

[简体中文](README.zh-CN.md) · [What's new](CHANGELOG.md) · [Related work](docs/related-work.md) · [Measured performance](docs/benchmarks.md)

## 众神指导 · Guided by the gods

### GPT-6 Astra Ultra × Multiple Astra Agents

> **“You can doubt my coding skills. Just don't underestimate Astra's.”**
> — orocoa, creator of Handoff

I shaped the requirements and spent **a month using and debugging Handoff intensively**. **GPT-6 Astra, with the Ultra reasoning setting in Codex, and multiple Astra agents** worked together on the final alpha.17 implementation: code review, fixes, performance optimization, regression checks, and independent cross-review. That is why I call this project **“众神指导” — “Guided by the gods.”**

## Why another handoff skill?

I built this for a very simple reason: **I wanted to be lazy about switching chats.** I didn't want to copy a summary, paste a prompt into a new chat, or work through a bunch of options. With the skill installed in a supported Local project, I wanted the routine to be simple: **type `$handoff`, then keep going.**

Yes, this overlaps with other handoff projects. I made a separate one because I wanted this exact small workflow for myself: **one command, no copy-paste, as little fuss as possible.** That's the whole motivation. See [related projects](docs/related-work.md).

## What is Handoff?

An explicit handoff skill for the **Codex desktop app**. When a long conversation still has unfinished work, send `$handoff`: save the essential context, create a fresh chat in the same verified saved Local project, and have it continue the work you already authorized.

Your files stay in place. There is no handoff prompt to copy and no second “continue” message to send. The core workflow needs no hook or always-on service.

**Current release:** `0.1.0-alpha.17` · **133 local regression tests passed** · **macOS tested** · **MIT**

```text
$handoff
   → verify the saved Local project
   → save a short packet, history, and creation receipt
   → create one successor chat
   → acknowledge the context and continue the authorized next step
```

## Who it is for

People who work through long debugging, development, research, or writing tasks in a Codex Local project and want to change conversations without rebuilding the working setup or explaining every decision again.

Use it when you want an explicit handoff with records you can inspect. If you only need a portable summary to paste into another agent, a simpler Markdown handoff may fit better; see [related projects](docs/related-work.md).

## Install

Requirements:

- Codex desktop with a **saved Local project** containing your working files. Git and non-Git projects are supported.
- Python **3.9+**. The helpers use the standard library and POSIX file locks; macOS is the tested platform.
- Native project and chat tools for the preferred path. The Codex CLI is needed only for the optional App Server fallback. Git is used for checkout verification and test fixtures.

Ask Codex to install the complete `handoff/` directory from this repository:

```text
$skill-installer Install the handoff skill from
https://github.com/orocoa/codex-handoff/tree/main/handoff
Inspect any existing handoff installation before updating it, and preserve a backup.
```

For a fresh manual installation, clone this repository, then run the following **from its root**. This links the complete skill into the current documented user skill location and stops if `handoff` already exists:

```bash
git clone https://github.com/orocoa/codex-handoff.git
cd codex-handoff
```

```bash
python3 - <<'PY'
from pathlib import Path

source = (Path.cwd() / "handoff").resolve()
assert (source / "SKILL.md").is_file(), "Run this from the repository root"
target = Path.home() / ".agents" / "skills" / "handoff"
if target.exists() or target.is_symlink():
    raise SystemExit("Existing handoff found; inspect and back it up before updating")
target.parent.mkdir(parents=True, exist_ok=True)
target.symlink_to(source, target_is_directory=True)
print(target)
PY
```

Keep the cloned directory in place while using that link. For an existing installation under `~/.codex/skills` or a custom location, update that installation after inspection rather than adding a second skill with the same name. If the skill does not appear, refresh discovery or restart Codex. [Official skill discovery guidance](https://learn.chatgpt.com/docs/build-skills).

## Permissions: Full Access is optional

Handoff can use **Ask for approval** or **Approve for me / Auto-review** with a writable Local workspace. Full Access is not required. Filesystem access and approval for the native task tools are separate controls.

- `workspace-write` + `on-request`: save in the project and use the host's normal manual or automatic review when a tool requires approval.
- `workspace-write` + `never`: local preparation can work, but a tool requiring approval is rejected. `never` does not mean “approve everything.”
- `read-only`: the full workflow needs scoped permission to write the packet/history/receipt and to invoke the task tools.

The skill does not change permission settings or use another interface to bypass a rejection. Its native-result helper records a known pre-execution approval conflict without losing the packet or enabling an immediate retry. After an effective permission change, recovery reuses the saved request and receipt; ambiguous results cannot be recreated.

See the [mode matrix, configuration and recovery instructions](handoff/references/setup.md#permissions-and-recovery). Local checks cover workspace-only preparation and read-only rejection; these are not live restricted-mode MCP handoff tests. Host policies and automatic review can still block creation.

The native workflow has no skill-level approval preflight: save, claim once, call the native tool, and confirm startup. Preparation no longer takes `--approval-policy` or `--sandbox-mode`; remove those flags (or Python keyword arguments) from older callers. The host still enforces actual tool permissions. Failures report the stopped stage, returned reason, creation certainty and recovery step; a timeout is not proof of non-creation. Old unclaimed receipts reuse their frozen request. The current source passes 149 local tests; the alpha.17 release archive predates these updates.

The optional App Server adapter also preserves the observed supported policy (`on-request` or `never`) instead of requiring a permission switch. It still verifies the model, provider and access boundaries. Failed or uncertain native results retain the actual returned error in the receipt.

Skill maintenance, diagnosis, tests and repository synchronization do not initiate a handoff, including when the skill is attached to that request. An unregistered projectless directory needs a verified saved Local project; retain the original request while the user registers their chosen directory.

## Use it

1. Open a saved **Local** project in Codex desktop and work normally.
2. When the conversation has grown long, select **Codex 任务交接** in the skill picker, or send:

   ```text
   $handoff
   ```

3. Handoff verifies the project, saves the packet and history, then creates the successor. The source chat reports the new link and the observed startup state.
4. Follow the link. The receiver checks its working directory, acknowledges the context, and continues the next authorized step. A queued chat is reported as queued, not as already running.

The current picker label and fixed generated prompt text are Chinese. The usage documentation is available in both languages.

### Example: finish debugging without starting over

Before handing off, make the remaining work and constraints clear in the current chat:

```text
We traced the bug to cache invalidation. Keep the current uncommitted changes.
Next, fix the two remaining failing tests and report the results.
```

Then send `$handoff`. The packet carries the recorded diagnosis, relevant files, decisions, checks, and next step. The receiving chat continues from that state and checks the files it will use.

The same flow works for a research or writing folder saved as a Local project: drafts and references stay where they are, and the next chat continues the agreed section or review. If the task genuinely needs your input, the successor preserves that waiting state instead of inventing a decision.

### If creation times out

Ask to reconcile the existing attempt:

```text
Check the saved receipt and existing successor from the last handoff.
Confirm whether it was created and recover that same attempt.
```

Do not repeatedly issue fresh `$handoff` requests to resolve an uncertain creation. The [recovery protocol](handoff/references/dispatch.md) uses the original invocation and tool evidence. Local receipts coordinate cooperative callers; they are not an end-to-end exactly-once guarantee.

## What makes this workflow distinctive

| Design choice | What it does for you |
|---|---|
| Explicit invocation | You decide when to switch. Ordinary mentions, quoted examples, editing, and tests do not initiate a handoff. |
| Verified saved Local project | The successor uses the same project and checkout. A source subdirectory is distinguished from the receiving project root. |
| A short packet plus durable history | Keep the goal, decisions, boundaries, evidence paths, and next step close at hand; retain earlier handoff snapshots. |
| A creation receipt | Record the attempt and actual queued, created, or uncertain outcome; inspect an ambiguous result before recreating anything. |
| A lightweight receiving flow | Acknowledge context, inspect relevant current files, and continue authorized work without repeating a full project audit. |

The distinction is this **combination of workflow choices**, not a claim to have invented summaries, new-chat creation, or workspace checks. Five related projects are compared with pinned source links in [Related work](docs/related-work.md).

## What is saved

By default, new handoff artifacts live in the verified project root's `work/handoffs/`; an existing designated handoff location takes precedence.

```text
work/handoffs/
├── handoff-<id>.md                  # Essential context and next action
├── handoff-<id>.receiver-prompt.txt # Prompt pointing to the packet
├── handoff-<id>.request.json        # Frozen preparation inputs
├── handoff-<id>.receipt.json        # Creation attempt and destination state
└── history/
    ├── INDEX.md                    # Eight most recent handoffs
    ├── catalog.json                # All registered entries
    └── snapshots/                  # Immutable handoff packets
```

Lock files and optional fallback runtime files are omitted from this overview. Earlier snapshots remain available beyond the eight-entry index. This is a history of authored handoff packets, not a complete transcript export or portable file backup. Archives can contain task IDs, absolute paths, and sensitive project summaries; inspect them before publishing a project.

## A month of real use, then “众神指导”

> I used Handoff intensively in my own Codex work for a month, debugging it as I went. That experience shaped its priorities: a direct invocation, preserved files, and records to inspect when the outcome is uncertain.
>
> I call the final alpha.17 development and review **“众神指导” — “Guided by the gods.”** I used **GPT-6 Astra with the Ultra (`ultra`) setting in Codex**, together with multiple Astra agents, to work through fixes, edge cases, regression checks, and the final skill. I supplied the use cases, feedback, and design decisions.
>
> — orocoa, maintainer

The month of use is the maintainer's personal experience. The Astra credit describes this release's development and review; it is not an OpenAI endorsement or a newly trained foundation model. Astra is not a runtime requirement: native creation forwards a model or reasoning override only when the user explicitly chose one; otherwise it uses the host tool's default.

## What's new in alpha.17

Correct source/receiver directories, checked archive boundaries, recoverable history failures, canonical receipt identities, real RPC deadlines, and provider verification in fallback. Repeated preparation avoids redundant writes; large transcript checks avoid repeated JSON decoding after validating their cached prefix.

See the bilingual [changelog](CHANGELOG.md) and [measurement notes](docs/benchmarks.md). Some local paths became substantially faster; first preparation and small transcript scans did not. No whole-handoff latency or token-cost reduction is claimed.

## Validation and limits

The release passed **133 tests** using synthetic projects and simulated App Server processes. They cover local file/state behavior, concurrent claims, interrupted publication, recovery, routing, settings checks, and cache invalidation. They do not prove live model behavior or every desktop version.

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s handoff/tests -v
```

Git must be available for test fixtures. Test artifacts are retained under `work/` by default. Tests do not create real Codex chats or make network calls.

- **Scope:** macOS Codex desktop, saved Local projects, shared local files. Windows and remote/cross-device transfer are unsupported by this tested configuration; Linux has not been validated.
- **Summary quality matters:** this is a compact continuation record, not lossless memory. The receiver must check relevant files before relying on them.
- **Fallback is constrained:** when native tools are missing, the [App Server adapter](handoff/references/app-server-fallback.md) verifies supported source model/provider/permission settings. Its first turn holds writer ownership; interactive requests interrupt and release its own client instead of granting approval.
- **Local does not mean offline inference:** the Python helpers do not call network services. Codex's model processing follows its normal operation.
- **Optional reminders:** an opt-in instruction can report observed local compaction records. It is not a background watcher or context-percentage meter and never authorizes a handoff. See [setup](handoff/references/setup.md).

## Feedback and license

If a handoff surprises you, open an issue with the version, platform, expected behavior, and a minimal redacted reproduction. Share only the relevant receipt state; avoid uploading private packets or complete conversations.

[MIT License](LICENSE). Related projects are credited in [Related work](docs/related-work.md).

# Same Local project and task naming

This skill creates a fresh conversation in the same saved Local project directory. There are no directory-mode choices or code-transfer workflows.

## Resolve before dispatch

1. Read the actual current task ID, host and cwd, then fetch the saved Project inventory for every creation, including non-Git directories: native `list_projects` when callable, otherwise documented App Server `project/list` per [app-server-fallback.md](app-server-fallback.md).
2. Match the verified source Project ID in that fresh inventory, or use canonical path matching on the same host: exact path first, otherwise the unique deepest containing project root. Same-name projects and similar path prefixes are not interchangeable. A failed listing is not an empty verified inventory.
3. Verify that the source is inside that same Local project. A missing historical directory triggers location recovery below, not an immediate blocker. For Git, compare `git rev-parse --show-toplevel` with the current saved project root as well; an unrelated nested repository is not the same checkout. Project association alone is insufficient.
4. For native creation set `target: {type: project, projectId: <verified ID>, environment: {type: local}}`. For App Server creation pass the verified `projectId` and canonical on-device `cwd` to `thread/start`; verify both in its response or `thread/read`. Do not add branch, starting-state, worktree or projectless options. Do not create a fork.
5. After attempting location recovery, if the Project is still missing, ambiguous or does not contain the current implementation, save useful records and report the specific Local prerequisite or mismatch. Do not silently switch to older project files, invent an ID or create an alternate directory. This is an actual scope problem, not a reason to routinely ask the user to choose between modes.

## Recover an updated directory

An earlier packet, source environment or failed handoff may remember a directory that no longer exists. Treat that as stale location evidence, not proof that the project is unavailable.

1. Use a fresh Project inventory for this invocation. Inspect only plausible current locations already evidenced by this task's actual cwd, a verified canonical workspace, an explicit user path or the provider's current project records. Do not search the whole disk for a matching folder name.
2. If the same verified Project ID now has a new path, verify that it exists and contains the task's current implementation. Resolve symlinks and, for Git, compare the actual checkout root. Use the updated path for preparation, explicit shell working directories and receiver verification; do not require the vanished old path to reappear.
3. If the inventory still has the vanished path, refresh it once. A unique current saved-project root that matches the observed actual workspace is also usable through canonical matching. If a stale source ID is no longer the association, record why canonical matching identifies the current saved project instead of passing that stale ID to the resolver. A same-name folder, a matching remote URL, or a similar path alone is insufficient; another worktree is not a relocation.
4. Record the old path, newly verified path, real current Project ID and matching evidence in the packet. This resolves the location without copying files, creating a symlink, changing global configuration or requesting another approval for an already verified update.
5. If the actual workspace is found but no current saved project points to it, native creation still has no valid target. Preserve the summary and report that precise registration mismatch. Do not forge the inventory or choose a projectless/worktree destination. If two plausible locations remain, report the ambiguity rather than guessing.

Run `resolve_target.py` with the recovered, observed workspace and the fresh inventory, not the absent historical cwd. Its existing canonical-path and checkout checks validate the new destination. The planner is read-only and cannot repair provider metadata itself.

`scripts/resolve_target.py` is a read-only planner for the fresh decoded `list_projects` JSON. It always resolves to `project/local`, or returns unresolved. It does not create tasks, register projects, copy files or change Git state. Pass `--verified-source-project-id` only with actual source-task evidence. `source_workspace` is the actual source cwd; `expected_cwd` is the matched saved project root. Pass both to preparation as `workspace` and `destination_workspace`. Do not replace one with the other, even for a legitimate nested source directory. The planner checks actual directory existence and probes Git only for the selected candidate/source, after complete inventory matching. A nested repository is rejected even when its saved container is marked non-Git.

```text
python3 <skill-dir>/scripts/resolve_target.py --projects-json <fresh-projects.json> --workspace <actual-directory> --host-id local --topic '最终模型核对' --stamp 20260913-1300
```

Record the exact target/title and matching evidence in the immutable packet. The preparation output `create_args` carries these values and any explicitly user-selected model/thinking overrides into `create_thread`; otherwise omit model overrides. Unresolved plans must not dispatch.

## Continue existing files

Keep the current code, uncommitted/untracked files, assets and environment in place. Record relevant file state, shared changes and active processes; do not package and restore the project simply to change conversations. The source stops executing the transferred objective after dispatch. The receiver verifies the current files and continues immediately within existing authorization, preserving other tasks' changes. Do not stop or take over other tasks or processes automatically.

Task archiving is separate from moving/deleting folders. Preserve source files and handoff history; do not automatically archive the source task, commit, merge, synchronize or migrate project files.

## Title

Use `项目名 · 目标简称 · 接续 YYYYMMDD-HHmm`, using the verified Project label and the fixed preparation time in the user's timezone. Honor an explicit user title or naming convention. Preserve the title on retries; do not derive a handoff counter from unrelated project history.

## Verify the receiving task

Persist returned IDs using the existing receipt protocol, then take a bounded status snapshot. Verify available Project/cwd metadata; expected cwd is the matched saved project directory. The receiver confirms its actual cwd against the packet’s destination cwd (not a nested source cwd) and compares Project metadata if already available; do not query its own task or the Project list merely to repeat the sender's matching. Check relevant current file state and any explicitly required check before dependent use/writes, and report concrete mismatches. No general intake audit or manifest is required. On a match, execute the next authorized action toward the recorded completion criteria without asking whether to continue.

If metadata is not exposed, state what is verified and leave actual cwd verification to the receiver; do not claim inspection. If placement is wrong, report the difference and stop dependent writes. Do not duplicate the task, redirect work to a second directory, or treat title/sidebar changes as cwd repair. Keep independent useful work moving within actual access constraints.

Editing or testing this skill does not authorize creation of a real receiving task.

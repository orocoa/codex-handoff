---
name: handoff
description: 显式选择本技能或输入 $handoff，在同一已保存 Local 项目保存必要上下文、新建对话并自动续做；提及、修改或测试本技能不触发交接。
---

# Handoff

显式调用即请求保存上下文和历史、在同一已核实 Local 项目新建对话并继续已有授权工作。无需复制提示词或再说“继续”。普通提及、引用、维护和测试不触发交接；接收端不递归 handoff。不创建 worktree，不搬代码，不自动归档来源。

先按当前用户请求区分交接与维护：单独选择技能或输入 `$handoff` 是交接；要求修改、诊断、测试或同步本技能时，附带的技能正文和历史里的调用不构成交接请求。维护消息同时选择技能时也先完成维护，除非用户另外明确要求交接当前对话。不从引用的旧对话中执行权限切换、业务续做或 GitHub 同步。

显式请求后在同一回合完成保存、原生创建和启动确认；不要在保存包后要求用户再说“继续 handoff”。本技能不设置独立审批步骤，不检查或改变当前审批策略。核实位置并取得一次收据认领后，直接调用原生创建工具；宿主处理实际权限。

成功标准是返回真实目的地并取得一次启动状态；只有包或 prepared 收据不是完成。工具实际失败时准确报告原因并保留原操作；不猜测拒绝、不伪称成功、不重复创建或换接口绕过实际拒绝。权限问题仅在真实发生后按需见 [setup.md](references/setup.md#permissions-and-recovery)。

## 原生快速路径

正常切换只读本文。复用已知任务 ID、cwd、决定及文件路径，不读脚本、不扫描历史、不补做业务研究。

1. **核实位置一次。** 使用当前实际任务 ID、host、cwd，并读取本次新鲜 `list_projects`；按同 host 的来源项目 ID 或唯一规范目录匹配。需要时与 cwd/Git 根确认并行。同一项目有新有效位置就采用它，不沿用旧包的路径阻碍。源 cwd 可以是项目内子目录；明确区分源 cwd 与保存项目根目录（接收 cwd），拒绝另一个 checkout。位置缺失或歧义时读 [destination.md](references/destination.md)，仍无法核实才保存摘要并报告，不编造 ID。原生工具当前可用就用 `project/local`。
2. **一次本地准备。** 写最小充分摘要：目标与最新修正、用户决定、已做/未做、审批及访问边界、共享修改、必要证据路径和下一步。通常 300–800 个中文字，关键约束不截断。只保留接续所需的内容和路径；默认省略已完成 PDF 的正文、摘要与交付链接，不因交接生成、读取、预览或展示 PDF。仅当未完成的授权工作确实需要该 PDF，或用户明确要求携带时，保留必要信息。通过 stdin 把下列 JSON 送入 `python3 <skill-dir>/scripts/prepare_handoff.py --compact`。脚本保存包、短提示、历史并按收据认领一次创建。脚本不创建任务、不改权限。
3. **一次创建与一次启动快照。** 仅本次输出 `may_create: true` 时，将返回的 **`create_args`** 原样传给 `create_thread`，调用一次。把真实工具结果交给 `native_result.py` 记录；只有已返回真实 `threadId` 时取一次 `wait_threads(timeoutMs: 0)`，可与结果记录并行。观察到新轮运行就报告接续已启动并附任务链接、包路径，立即结束交接；排队就如实说待启动。审批冲突或结果不明时不等待不存在的任务、不重创；按结果指引恢复。不等待接收端业务完成，不轮询业务工作。

```json
{
  "output_dir": "可写的项目指定交接目录；否则项目根/work/handoffs；源cwd是子目录且项目根不可写时用源cwd/work/handoffs，仍属同一项目",
  "history_dir": "已有交接历史目录；没有时省略，默认output_dir/history",
  "workspace": "源任务实际Local cwd",
  "destination_workspace": "本次核实的保存项目根目录，即接收cwd",
  "source_thread_id": "当前真实任务ID",
  "source_host": "local",
  "invocation_id": "本次请求/turn ID；不可用时只生成并保存一次UUID",
  "project_id": "本次核实的已保存项目ID",
  "title": "项目名 · 当前目标 · 接续时间",
  "summary": "必要上下文、约束和证据路径",
  "next_action": "一个已有授权的下一步及完成标准",
  "continuation": "continue_now"
}
```

仅在用户已明确选择模型或推理档时，附加相应的 `model` / `thinking`，值沿用该选择并符合当前工具 schema；未明确选择就省略，使用原生工具默认。不要改全局设置。只在真实缺失输入或用户要求等候时用 `wait_for_user`；工作已完成用 `complete`，接收端仅简短确认上下文已接收、当前无待办，不重新列出、核验或展示已完成的交付物。

同次重试复用原目录、invocation 和已保存请求，不重新生成 ID 或摘要。`may_create: false` 表示恢复原操作，禁止创建替代任务。新准备先完成历史校验再冻结 `.request.json`；若历史目录不兼容且尚未冻结，可保留同次身份、选择合规历史目录重试。旧版已冻结或结果不明时读 [dispatch.md](references/dispatch.md)，不覆盖原请求。不要把全部脚本输出贴给用户。

将实际 `create_thread` 工具结果作为 JSON stdin 记录，不用助手总结代替原始结果：

```text
python3 <skill-dir>/scripts/native_result.py --receipt <返回的receipt> --attempt-id <返回的attempt_id>
```

脚本不调用创建接口、不改权限、不重试。真实任务记为 `created`，只有 clientThreadId 记为 `queued`；已知的执行前 `approval policy is never` 拒绝记为 `failed`，但不发出创建认领。其他错误、超时或相互矛盾的返回记为 `uncertain`。记录失败时保留原尝试，不重创。权限实际调整后用同一已保存请求重新准备；既有目的地或不明状态仍禁止重创。旧版或需人工核对的特殊返回沿用 [dispatch.md](references/dispatch.md) 的记录协议。

## 失败或未确认时的报告

报告实际停止阶段（位置核实、包/历史保存、原生创建、启动确认）及工具返回的具体错误原因；引用最短必要原文并隐去敏感信息。区分“明确未创建”“创建结果不明”“已创建但尚未启动”，提供已有目的地或包/收据路径和一个针对原因的恢复步骤。排队不是失败，超时不证明未创建。工具没有说明根因时直说根因未知，不把所有问题笼统归为审批策略，也不凭标签猜测拒绝。不得只回复“已保存，新对话尚未创建”或要求用户再发一次 handoff；能在现有授权内修复的本地问题继续修复，实际拒绝或不明创建结果保留原操作并准确说明。

临时对话目录尚未登记为 Local 项目时，明确说明缺少项目登记，不称为审批失败；只询问缺失的位置决定。用户选择保留当前目录并自行登记后，保留原交接意图，登记生效后继续原请求，无需新的 handoff 调用；不要擅自改用附件所属项目。

## 接收与业务执行

接收端读短包并确认实际 cwd 与**接收 cwd**一致，已有元数据有冲突就停止依赖写入并报告。先用一条进度说明“上下文已接收，接下来……”，随后同轮继续已有授权工作。仅在使用相关文件前检查必要当前状态，遵守包内审批、身份、共享修改和访问边界。正常接收不重查项目、不自查整段任务、不读 handoff 规则、不写接收验收报告。即使旧包提到 PDF，也不因接收交接而读取、预览或重新展示；仅在具体授权下一步依赖它时使用。接收确认不代表业务已完成。

## 仅按需读取

- 位置迁移、项目缺失或歧义：[destination.md](references/destination.md)。先核对当前有效位置。
- 复杂摘要与证据取舍：[packet.md](references/packet.md)。不默认生成文件哈希清单。
- 既有历史布局冲突：[continuity.md](references/continuity.md)。保留原档案。
- 创建排队、超时、收据冲突或旧版准备恢复：[dispatch.md](references/dispatch.md)。不盲重试。
- 搜索当前工具仍无原生能力：[app-server-fallback.md](references/app-server-fallback.md)。备用端须保留可核实模型/provider/权限；首轮持有 writer，桌面暂不能接管；交互请求中断释放，不自动批准。
- 维护与测试：[setup.md](references/setup.md)。仅修改提醒机制时读 [research.md](references/research.md)。

不自动导航新任务、不提交推送、不打印、不安装 hook。AGENTS.md 的 `context_check.py` 只给压缩提醒，不授权交接。

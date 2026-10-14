# App Server 备用路径与桌面端写入所有权

仅在用户明确要求交接，且检查当前工具目录及可用工具搜索后，原生 `list_projects`/`create_thread` 仍不可用时使用此路径。历史任务的工具可用性不能证明当前任务的工具可用性。优先使用原生 `project/local` 创建，以免启动独立的写入进程。

[官方 App Server 协议](https://learn.chatgpt.com/docs/app-server)说明了 `initialize` → `initialized`、`thread/start`、`turn/start` 和 `turn/interrupt`。备用路径使用独立客户端：它运行首轮时，桌面端可能显示 **This is open in another app**。启动一轮不会把写入所有权转交给桌面端。不要将其描述为可以立即在桌面端交互续做。

## 确认并保留来源

此备用路径保留实际观察到的标量 `approval_policy`，支持 `on-request` 和 `never`；无需切换为交互式权限。API 格式校验会拒绝缺失、已停用或不支持的细粒度策略，而不会修改它们。适配器无法保留的策略格式应使用原生派发。此路径不能替代或绕过原生审批拒绝。[官方 App Server thread/start 示例](https://learn.chatgpt.com/docs/app-server)明确使用 `never`；[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)说明了受支持的标量值。核查日期：2026-10-02。

使用一个只读 App Server 连接（`codex app-server --stdio`），以 `capabilities.experimentalApi: true` 初始化，通过 `thread/read` 读取确切的来源任务，并分页读取 `project/list`，直到确认已保存的 Local 项目。匹配实际来源 Project ID，或此主机上唯一的规范根目录，不能只按名称匹配。保持同一个 `projectId`；分别记录实际来源 cwd 和已核实的目的地 cwd。旧收据默认以来源目录为目的地；存在 `destination_workspace` 时使用该字段。不要创建 worktree 或改用无项目任务。读取完成后关闭这个路由连接。

记录 `thread/read` 返回的确切来源 rollout `path`。派发助手通过必需参数 `--source-rollout`，核对其 `session_meta.id` 与收据、最新 `turn_context.cwd` 与工作区是否一致。它保留实际观察到的模型、`session_meta.model_provider`、推理强度、审批策略、审批审核者、沙箱及显式工作区根目录。缺失的提供方或根目录属于未知信息，应拒绝；显式空根目录数组保持为空，并在实际生效的响应中核验。这些是每个任务的设置，不是对全局配置的修改。不要伪造来源 rollout 或设置以取得更广的访问权限。助手会拒绝缺失或不支持的上下文、命名权限配置及不支持的沙箱模式；应使用原生派发或报告具体限制。遵守当前主机或用户更严格的约束，不要照搬较旧、较宽的设置。在 workspace-write 下，位于来源目录上层的目的地必须已被观察到的来源可写根目录覆盖；改变 cwd 不得悄悄扩大可写范围。不支持的情况需要原生派发或准确的限制说明，不能扩大权限。

若协议拒绝预期字段，在调整前使用 `codex app-server generate-json-schema --out <work-directory> --experimental` 检查已安装的 schema。不要在每次成功交接时重新生成 schema 或重读脚本。不要通过未公开的桌面端接口、数据库写入或 UI 自动化取得写入所有权。

## 仅派发一次

按照 [dispatch.md](dispatch.md) 准备交接包、简短接收提示、历史及已认领收据，然后运行：

```text
python3 <skill-dir>/scripts/appserver_dispatch.py --detach \
  --receipt <receipt.json> --attempt-id <claimed-attempt> \
  --packet <packet.md> --project-id <verified-project-id> \
  --cwd <verified-local-directory> --title <receiver-title> \
  --prompt-file <receiver-prompt.txt> --source-rollout <verified-source-rollout.jsonl>
```

助手核验交接包及所有自动生成的接收提示绑定、来源设置和新鲜 Project 列表，调用一次 `thread/start`，在发送工作前检查返回的实际生效设置，然后启动一轮。设置不一致属于错误，不能因此省略检查或悄悄接受 CLI 默认值。每次尝试的独占工作进程认领可阻止两个前台运行者使用同一创建认领。保留完整的收据、日志、运行状态和工作进程认领文件。

若能够证明本地校验、工作进程启动、运行状态初始化、初始化 RPC 或项目核验失败发生在任何 `thread/start` 尝试之前，助手会记录确切阶段，并标记为 not-created；修复本地原因后，在同一调用下再次认领。一旦开始发送 `thread/start`，后续失败仍属结果不明，不得盲目重试。返回的候选身份是核对证据，不是已核实的目的地。运行状态记录或清理失败不会替换原始错误；助手也不会声称已释放从未取得的写入所有权。这种分类不授权绕过实际主机拒绝。

启动器只等待启动（默认 30 秒）。`startup_pending` 不授权再次启动；应检查同一次尝试。`created` 收据记录已有目的地，即使其首轮随后失败也仍然有效。它不证明目标已完成或桌面端已可接管。来源任务确认时应只取一次有界的收据/运行状态快照，随后停止执行已转交的工作。

## 运行、释放并准确报告

工作进程在收据旁写入私有 `.runtime.json`，包含实际生效的来源上下文、任务/轮次 ID、状态、错误和 `writerReleased`。工作正常进行时，它持有写入所有权；不会用任意定时器终止正在有效工作的轮次。在 `turn/completed` 后，它核验已保存的项目/目录，并关闭自己的 App Server。只有该进程退出后，才写入 `writerReleased: true`。其他客户端随后可能取得任务，因此该标志证明的是此工作进程已释放所有权，不保证当前桌面端拥有写入权。

无界面工作进程无法展示或回答交互请求。遇到**任何**服务端发起的请求（包括命令/文件/权限审批、用户输入、MCP elicitation 和未来未知请求）时，它会记录 `attention_required`，为自己的任务/轮次调用 `turn/interrupt`，采用有总时限的等待，然后关闭自己的服务端并释放写入所有权。若请求明确指向另一个任务/轮次，助手会记录请求并释放此客户端，不向另一任务发送中断或响应。它绝不授予权限、编造答案或更改沙箱设置以绕过请求。中断会清除待处理请求；恢复后桌面端可能需要重新发起该操作。已有任务和历史保持不变，收据仍为 `created`。

报告以下实际观察到的状态之一：

- **后台首轮已启动，桌面暂不可接管**：`running`，写入所有权尚未释放。提供已有任务链接和交接包路径。
- **需要人工处理，后台已释放**：`attention_required` 且 `writerReleased: true`。说明记录的请求类型，引导用户到同一任务。不要声称实质工作已经完成。
- **首轮结束，后台已释放**：终止状态且 `writerReleased: true`。报告实际 completed/failed/interrupted 状态；不要仅凭进程退出推断任务已完成。
- **启动待确认或失败**：说明具体的收据/运行状态证据，保留同一次尝试及所有已记录的任务 ID。不要因超时而重新创建。

不要删除写入锁文件，也不要终止无关或先前客户端的进程。更新技能不会改变已运行的工作进程；恢复旧的受阻任务属于另一项操作。不得自动改用 `codex exec`、TUI 或 `codex mcp-server`：这些方式无法确立已保存的桌面端 Local Project 归属。

RPC 时限覆盖发送、缓冲消息和通知流量。失败轮次的结构化 `turn.error` 保留在私有运行状态中；创建身份保持不变。客户端版本从已安装的 VERSION 文件读取。协议测试夹具已对照 codex-cli 0.158.0-alpha.2.1 核查；CLI 更新后仍需核验受支持字段。

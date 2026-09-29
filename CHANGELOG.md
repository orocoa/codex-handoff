# Changelog · 更新记录

## 0.1.0-alpha.17 — 2026-09-29

This release improves local project routing, retry recovery, and the cost of repeated preparation. The installed release passed **133 tests**, including storage, concurrency, routing, protocol simulations, and cache invalidation. Live model startup and complete desktop handoffs were not benchmarked in this release audit.

本版完善 Local 项目定位、失败恢复和重复准备性能。安装后的版本通过 **133 项测试**，覆盖存储、并发、位置匹配、协议模拟和缓存失效。本轮发布审计未测量真实模型启动或完整桌面交接的耗时。

### Fixed · 修复

- Validate resolved archive, snapshot directory, and snapshot destination against the verified workspace. Preserve and reject an existing out-of-bounds link. / 校验归档和快照的实际写入边界，拒绝越界并保留原链接。
- Distinguish source cwd from the saved Local project's receiving cwd, including nested-directory handoffs. / 区分来源 cwd 与接收项目根目录，支持从项目子目录正确接续。
- Freeze a new request after history publication succeeds, so an incompatible archive does not prematurely lock the invocation. Document recovery for legacy frozen failures. / 历史发布成功后再冻结请求，补充旧版已冻结失败的恢复流程。
- Enforce one absolute RPC deadline across writes, reads, and buffered notifications. / RPC 的写入、读取和积压通知共用绝对截止时间。
- Preserve and verify the source model provider in App Server fallback, including explicit empty workspace roots. Unknown settings remain unsupported rather than silently defaulted. / 备用路径传递并核验模型 provider 及显式空 roots；未知配置不静默套用默认值。
- Canonicalize receipt and worker identities; reject hard-linked receipts to avoid splitting a claim. / 统一收据与 worker 的规范路径，拒绝会分裂认领的硬链接收据。
- Preserve the saved receiver prompt on compatible retries across renderer upgrades, including a history failure before request freeze. / 兼容重试保留已保存的接收提示，包括冻结请求前的历史失败。
- Keep structured turn errors for diagnosis and take client version from `VERSION`. / 保留结构化回合错误，客户端版本统一读取 `VERSION`。

### Faster repeated work · 重复操作减负

- Filter the project inventory before probing Git; the 100-root synthetic case uses one Git probe instead of 100. / 先筛选项目再查 Git；100 个目录的合成场景从 100 次调用降为 1 次。
- Skip rewriting identical content and already registered catalog entries, while preserving required directory synchronization and missing-index recovery. / 相同内容和已登记记录跳过重复写入，同时保留必要同步与索引恢复。
- Use checked scan checkpoints for transcripts of at least 4 MiB when advisory state is enabled. Revalidate the full old prefix before decoding new complete lines. / 启用提醒状态时，4 MiB 及以上日志使用扫描检查点；先核验旧前缀，再解析追加完整行。
- Add opt-in `prepare_handoff.py --compact` and shorten the normal skill entrypoint. / 新增推荐的 `--compact` 输出，精简正常路径的技能入口。

See [measured results and limitations](docs/benchmarks.md). First preparation and small transcript scans did **not** improve in these measurements. / 参见[测量结果与边界](docs/benchmarks.md)；首次准备与小日志扫描在本次样本中**没有提速**。

### Compatibility · 兼容

Existing Python call signatures and default CLI creation fields remain available. `destination_workspace`, `model`, and `thinking` are optional preparation fields; explicit model choices are passed to the native creation tool. `--compact` only removes duplicated legacy top-level creation fields from stdout. Existing packet/history files are retained.

原 Python 调用方式与默认 CLI 创建字段继续保留。`destination_workspace`、`model` 和 `thinking` 为可选准备字段；明确选择的模型参数会传给原生创建工具。`--compact` 仅省去 stdout 中重复的旧顶层创建字段。原交接包和历史文件保持保留。

### Development · 开发记录

The maintainer reports one month of intensive personal use and debugging. This release was developed and reviewed using **GPT-6 Astra with the Ultra (`ultra`) setting in Codex and multiple Astra agents**, including independent checks of failure recovery and upgrade compatibility. The maintainer calls this process **“众神指导” — “Guided by the gods.”** This describes the development process for the skill, not a newly trained foundation model or an OpenAI certification.

作者已在自己的工作流中高强度使用并 debug 一个月。本版通过 **GPT-6 Astra（Codex 中的 Ultra／`ultra` 设置）与多个 Astra agent** 协作完善，包含独立的失败恢复与升级兼容复核。作者将这一过程称为 **“众神指导”**。这里指技能的开发与评审方式，不是训练了新的基础模型，也不代表 OpenAI 官方认证。

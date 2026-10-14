# 设计参考，核查日期 2026-09-12

本技能面向用户明确调用、在同一 Local 项目中交接的 Codex 桌面端流程编写；不会安装或执行任何第三方仓库脚本。

- https://github.com/klittle32/handoff-skill — 围绕目标的交接包和证据位置；其文档中的接收流程仍需启动会话并粘贴提示。采用聚焦目标的交接包思路，以原生 Codex 任务创建替代手动交付。不采用其临时文件丢弃行为。
- https://github.com/codagent-ai/agent-skills/blob/main/skills/handoff/SKILL.md — 简洁记录目标、状态、决定、未决问题和下一步。示例仅保存摘要。本版本核验少量相关工作区事实，并将交接包发送给接收端。
- https://github.com/WeirdSky924/agent-handoff-skill/blob/main/SKILL.md — 持久保存的仓库交接文档和基于证据的续做。扩展版本增加了项目历史快照、精简索引及评审/修正说明。其跨平台初始化和 Claude hooks 不在本次 Codex 专属需求范围内，也未安装。
- https://github.com/timyeou1234/context-handoff — 在受支持时也会创建新的 Codex 任务，并核验工作区兼容性；其生命周期 hook 检测压缩。因此，单独的直接创建任务和核验并非本技能独有。本技能结合了显式单次调用交接、精确的已保存 Local 项目路由、无需 hook 的核心流程、持久项目历史和创建收据。
- https://learn.chatgpt.com/docs/build-skills — 显式调用策略与技能发现。
- https://learn.chatgpt.com/docs/hooks — Stop 阻塞会创建续做提示，自定义 hooks 需要信任。本实现完全不使用生命周期 hooks。

桌面端派发行为由当前 `create_thread`/`list_projects`/`wait_threads` schema 定义。使用时重新读取这些 schema。技能本身不能保证后台调度或严格的上下文阈值。全局提醒指令与本地脚本属于尽力而为的机制，只在 Codex 遵循该指令时运行，使用实际观察到的规范 `compacted` JSONL 记录，不猜测 token 压力。

# 同类项目与定位

于 **2026-09-29** 核对公开 README、技能、项目清单与提交记录。这是源码与文档对照，不是实际运行后的可靠性或性能排名。以下提交日期不一定是发布日期；引用固定到审阅版本，后续项目可能变化。

## 五种值得参考的做法

| 项目 | 核验版本 | 重点 |
|---|---|---|
| [klittle32/handoff-skill](https://github.com/klittle32/handoff-skill) | [57089b6](https://github.com/klittle32/handoff-skill/blob/57089b6e1ce61498ec70852e46d41b2f8f12fa00/SKILL.md)，2026-06-13 | 围绕下一目标提取便携交接文档，提供可粘贴到新会话的启动消息。 |
| [Codagent-AI handoff](https://github.com/Codagent-AI/agent-skills/tree/main/skills/handoff) | [244b104](https://github.com/Codagent-AI/agent-skills/blob/244b10402c4ebaaace6c4e71a4b892187eb7a458/skills/handoff/SKILL.md)，2026-09-29 仓库 HEAD | 按用户指定方面精简保存目标、状态、决定、开放问题、下一步和文件。 |
| [WeirdSky924/agent-handoff-skill](https://github.com/WeirdSky924/agent-handoff-skill) | [ef01fa9](https://github.com/WeirdSky924/agent-handoff-skill/blob/ef01fa9db0ea0aab19141954644a1049da4da795/SKILL.md)，2026-08-27 | 通过快照、决定、验证、风险和待办等文档持续维护仓库记忆及归档。 |
| [timyeou1234/context-handoff](https://github.com/timyeou1234/context-handoff) | [0cf554b](https://github.com/timyeou1234/context-handoff/blob/0cf554bd8c26abb00eaf656d373453959387d29f/skills/context-handoff/SKILL.md)，项目清单版本 0.3.4，2026-09-11 | 上下文压力钩子、经核验的新线程交接、接收检查、可见性读回及授权归档；也提供仅使用技能的用法。 |
| [djhyes/context-handoff](https://github.com/djhyes/context-handoff) | [a350295](https://github.com/djhyes/context-handoff/blob/a35029596e3f56698d9d74a0d38ae4d091792069/skills/context-handoff/SKILL.md)，项目清单版本 0.2.2，2026-06-21 | Codex 项目感知的新线程创建、保留显式模型选择及压缩提醒钩子。 |

Codagent 的该技能最后修改于 [7c00678](https://github.com/Codagent-AI/agent-skills/commit/7c006787b96b917bb870a871018bee3ac69e614c)，2026-05-12。列出仓库 HEAD 日期是为便于复核，不是给活跃度打分。

## 本项目的选择

Handoff alpha.17 将**显式调用、已核实且已保存的 Local 项目、基于文件的短交接包、不可变本地历史与收据恢复**组合起来，要求接收端确认上下文后在同一轮继续授权工作。正常路径不安装钩子、不创建 Git 工作树，也不自动导航、置顶或归档对话。

这些选择适合希望自行决定何时交接、并能回查结果的人。跨代理粘贴可能更适合便携 Markdown；持续记忆方案覆盖更广的项目文档；带钩子的方案提供更多生命周期自动化。

自动新建、项目核验、保留模型选择、摘要与持久历史都有先例。本项目不声称这些单点独有，也不声称该组合在全世界唯一。此处没有跨项目速度、可靠性或词元成本基准。

## 参考与致谢

感谢这些项目对目标导向提取、精简状态摘要、证据引用和持久文档的探索。原有设计参考保留在技能的[调研记录](../handoff/references/research.md)。这些项目独立维护，列入参考不代表其作者为本项目背书。

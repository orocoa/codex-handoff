# Handoff

**换个对话，接着把事做完。**

[English](README.md) · [更新记录](CHANGELOG.md) · [同类项目对照](docs/related-work.md) · [性能测量](docs/benchmarks.md)

## 众神指导

### GPT-6 Astra Ultra × 多个 Astra Agent

> **“你可以不相信我的 coding 能力，但不能否定 Astra 的实力。”**
> —— orocoa，Handoff 项目作者

我负责提出需求，并且已经**高强度使用、持续 debug 一个月**。最终 alpha.17 项目实现由 **GPT-6 Astra（Codex 中的 Ultra 推理设置）与多个 Astra agent** 协同完善，覆盖代码审查、问题修复、性能优化、回归验证与独立交叉评审。这就是我把这个项目称为**“众神指导”**的原因。

## Handoff 是什么？

面向 **Codex 桌面端**的显式任务交接 skill。对话已经很长，但手上的事情还没做完？发送 `$handoff`，保存必要上下文，在同一个已核实的保存 Local 项目中新建对话，让它继续已有授权的工作。

文件留在原处。无需复制交接提示词，也无需再说一次“继续”。核心流程不需要 hook 或常驻服务。

**当前版本：** `0.1.0-alpha.17` · **133 项本地回归测试通过** · **macOS 已测试** · **MIT**

```text
$handoff
   → 核实已保存的 Local 项目
   → 保存短交接包、历史和创建收据
   → 创建一个接续对话
   → 接收上下文，继续已授权的下一步
```

## 适合谁

适合在 Codex 的 Local 项目里持续调试、开发、研究或写作的用户：想换个新对话，但不想重建工作目录、重新解释每个决定，也希望出问题时有记录可查。

如果你只需要一段可粘贴给其他 agent 的摘要，更简单的 Markdown 交接方案可能更合适，参见[同类项目对照](docs/related-work.md)。

## 安装

需要：

- Codex 桌面端，以及包含当前文件的**已保存 Local 项目**；支持 Git 和非 Git 项目。
- **Python 3.9+**。辅助脚本使用标准库和 POSIX 文件锁；已测试平台为 macOS。
- 首选路径需要原生项目与对话工具。Codex CLI 仅用于可选 App Server 备用路径；Git 用于 checkout 核验和测试夹具。

让 Codex 从本仓库安装完整的 `handoff/` 目录：

```text
$skill-installer 从下面的仓库目录安装 handoff 技能：
https://github.com/orocoa/codex-handoff/tree/main/handoff
如果已经安装 handoff，请先检查现有目录并保留备份，再进行更新。
```

全新手动安装时，先克隆本仓库，然后**在仓库根目录**运行以下命令。它会把完整技能链接到当前官方文档的用户级技能目录；目标已存在就停止：

```bash
git clone https://github.com/orocoa/codex-handoff.git
cd codex-handoff
```

```bash
python3 - <<'PY'
from pathlib import Path

source = (Path.cwd() / "handoff").resolve()
assert (source / "SKILL.md").is_file(), "请从仓库根目录运行"
target = Path.home() / ".agents" / "skills" / "handoff"
if target.exists() or target.is_symlink():
    raise SystemExit("已有 handoff，请先检查并备份，再更新")
target.parent.mkdir(parents=True, exist_ok=True)
target.symlink_to(source, target_is_directory=True)
print(target)
PY
```

使用链接期间请保留克隆目录。若已经安装在 `~/.codex/skills` 或自定义位置，应检查后更新原安装，避免出现两个同名技能。若尚未显示，可刷新技能发现或重启 Codex。[官方技能发现说明](https://learn.chatgpt.com/docs/build-skills)。

## 具体怎么用

1. 在 Codex 桌面端打开一个已保存的 **Local 项目**，正常开展工作。
2. 需要换新对话继续时，选择技能 **Codex 任务交接**，或者直接发送：

   ```text
   $handoff
   ```

3. Handoff 核实项目，保存交接包和历史，再创建接续对话。原对话会返回新对话链接及实际观察到的启动状态。
4. 打开链接。接收端检查工作目录，先说明已收到上下文和接下来做什么，再继续已有授权的下一步。仍在排队时，会如实报告排队状态。

当前技能选择器名称和固定生成提示为中文；使用文档提供完整中英两版。

### 例子：调试做了一半，换新对话接着修

先在当前对话说明剩余工作和约束：

```text
已经确定问题在缓存失效逻辑。保留当前未提交的修改。
下一步修复仍失败的两个测试，完成后报告测试结果。
```

然后发送 `$handoff`。已记录的问题判断、相关文件、决定、检查结果和下一步会进入交接包；接收对话据此续做，并检查即将使用的文件。

研究与写作同样适用：把资料目录保存为 Local 项目，草稿和引用留在原处，新对话继续已约定的章节或校对步骤。若任务确实在等待你的资料或选择，交接会保留等待状态，不把未定选项当成决定。

### 如果创建超时

要求核对原来的尝试：

```text
检查上次交接保存的收据和现有接续对话。
确认是否已经创建，并沿用同一次交接记录恢复。
```

不要靠反复发送新的 `$handoff` 解决结果不明的问题。[恢复协议](handoff/references/dispatch.md)要求复用原调用身份并核对工具证据。本地收据协调的是遵守协议的调用方，不承诺跨外部系统的 exactly-once。

## 这套流程的辨识度

| 设计选择 | 实际带来的价值 |
|---|---|
| 显式触发 | 由你决定何时换对话；普通提及、引用、编辑和测试不会启动交接。 |
| 核实同一保存 Local 项目 | 沿用同一个项目与 checkout，清楚区分来源子目录和接收项目根目录。 |
| 短包与可查历史 | 保存目标、决定、边界、证据路径和下一步，同时保留更早的交接快照。 |
| 创建收据 | 记录尝试及真实的排队、已创建或不确定状态；结果不明时先查记录。 |
| 精简接收流程 | 接收后检查相关文件并继续授权工作，不重复进行完整项目审计。 |

差异在于这套**工作流选择的组合**。摘要、新建会话、工作区核验都已有同类实现；本项目不把这些单点包装成首创。已对照 5 个相关项目，固定版本的来源见[同类项目对照](docs/related-work.md)。

## 会保存什么

默认写入已核实项目根目录的 `work/handoffs/`；已有指定交接目录时优先沿用。

```text
work/handoffs/
├── handoff-<id>.md                  # 必要上下文与下一步
├── handoff-<id>.receiver-prompt.txt # 指向交接包的短提示
├── handoff-<id>.request.json        # 冻结的准备输入
├── handoff-<id>.receipt.json        # 创建尝试与创建结果
└── history/
    ├── INDEX.md                    # 最近八次交接
    ├── catalog.json                # 全部已登记记录
    └── snapshots/                  # 不可变交接快照
```

上图省略锁文件及可选备用路径的运行文件。索引只显示最近八次，更早快照仍保留。这是交接包历史，不是完整聊天导出，也不是可搬走原文件的备份。档案可能包含任务 ID、绝对路径和项目摘要，公开项目之前应检查其中内容。

## 一个月高强度使用，以及“众神指导”

> 我已经连续一个月把 Handoff 放进自己的 Codex 工作里，高强度使用，也在实际使用中不断 debug。这段经历决定了它今天的取舍：调用要直接，旧文件要保留，结果不明时要有记录可查。
>
> 我把 alpha.17 这一轮的最终完善与评审叫作**“众神指导”**：使用 **GPT-6 Astra（Codex 中的 Ultra／`ultra` 设置）**，同时让多个 Astra agent 分工协作，完成修复、边界审查、回归验证和技能整理。我负责使用场景、反馈与设计取舍。
>
> —— orocoa，项目作者

一个月使用是作者的个人实践；Astra 署名说明本版的开发和评审过程，不代表 OpenAI 官方背书，也不是训练了一个新的基础模型。使用 Handoff 本身不要求 Astra：原生创建仅在用户已明确选择时传入模型或推理覆盖值，否则使用宿主工具默认值。

## alpha.17 更新了什么

修正来源与接收目录、归档边界、历史失败恢复、收据身份、RPC 截止时间和备用 provider 核验。重复准备减少冗余写入；大日志在校验缓存前缀后减少重复 JSON 解码。

详见双语[更新记录](CHANGELOG.md)及[性能测量](docs/benchmarks.md)。部分本地操作明显提速；首次准备和小日志扫描没有变快，本项目不据此宣传整次交接耗时或 token 成本降低。

## 验证与边界

本版通过 **133 项测试**，使用合成项目和模拟 App Server，覆盖文件与状态、并发认领、中断发布、恢复、目录匹配、配置核验和缓存失效。测试不等于真实模型行为或全部桌面版本的保证。

在仓库根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s handoff/tests -v
```

测试夹具需要 Git，产物默认保留在 `work/`；测试不创建真实 Codex 对话，也不调用网络。

- **支持范围：** macOS Codex 桌面端、已保存 Local 项目、共享本地文件。此已测试配置不支持 Windows 和远程／跨设备迁移；Linux 尚未验证。
- **摘要质量仍然重要：** 这是精简续接记录，不是无损记忆；接收端必须检查将要依赖的文件。
- **备用路径有限制：** 原生工具缺失时，[App Server 适配器](handoff/references/app-server-fallback.md)核实其支持的源模型、provider 和权限配置。首轮会占用写入权；交互请求会中断并释放自身客户端，不代替用户批准。
- **本地不等于模型离线：** Python helper 不调用网络服务；Codex 的模型处理仍按正常机制进行。
- **提醒是可选项：** 可配置指令提示本地日志中已观察到的压缩次数；它不是后台 watcher 或上下文百分比仪表盘，也不授权交接。配置见[使用环境与提醒](handoff/references/setup.md)。

## 反馈与许可

遇到异常时，欢迎提交 issue，说明版本、平台、预期行为和经过脱敏的最小复现。只提供有关的收据状态，避免上传私人交接包或完整对话。

采用 [MIT License](LICENSE)。相关方案见[同类项目与致谢](docs/related-work.md)。

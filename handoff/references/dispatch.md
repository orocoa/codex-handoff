# Codex 桌面端本地收据协议

正常原生准备通过 `prepare_handoff.py`，在一次本地操作中发布交接包/历史并调用 prepare/claim。手动备用派发、排队或结果不明的创建，以及恢复时，再读取本详细协议；并非每次交接都必须读取。收据和不得盲目重试的约束保持不变。可选 `destination_workspace` 记录已保存项目根目录，与嵌套的来源 cwd 区分；没有该字段的旧收据仍以来源目录为目的地。手动准备时，若两者不同，使用 `--destination-workspace`。收据路径在加锁前规范化；硬链接收据会被拒绝，以免原子替换使其分裂。

使用实际安装的技能路径。用观察到的值替换占位符；这些示例不授权创建任务。先满足 SKILL.md 中的显式调用条件，写入并核验交接包和历史，按照 [destination.md](destination.md) 确认实际 Project 和标题，在不可变交接包中记录确切的原生 `target`/`title`、来源/目的地 cwd 和选择证据，再在包旁准备收据。将这些值原样带入原生调用；收据本身不会把任务路由到 Project。

```text
python3 <skill-dir>/scripts/dispatch.py prepare --receipt <receipt.json> --packet <packet.md> --invocation-id <stable-current-request-id> --source-thread <actual-id> --source-workspace <absolute-path>
python3 <skill-dir>/scripts/dispatch.py claim --receipt <receipt.json>
```

有真实请求/轮次 ID 时使用它；否则只生成一次唯一调用 ID，并随交接包保存。重试时从收据恢复该 ID。不要为每次尝试使用新的时间戳或收据。另一次用户调用可以创建另一份收据。

`claim` 在文件锁下原子持久化 `dispatching` 和 `attempt_id`。若 `may_create` 为 false，恢复已保存操作，不调用创建。若为 true，使用返回的尝试 ID，最多调用一次 `create_thread` 或 App Server `thread/start`。收据持久化必须在创建调用前成功。检查当前实际工具/协议 schema 及其授权要求。

记录实际结果：

```text
python3 <skill-dir>/scripts/dispatch.py finish --receipt <receipt.json> --attempt-id <returned-attempt> --outcome created --thread-id <returned-threadId> --host-id <returned-hostId>
```

host-id 不可用时省略。设置仍在准备时使用 `--outcome queued --client-id <returned-clientThreadId>`。客户端 ID 不是就绪任务 ID。将该排队操作匹配到就绪任务后，以 `created` 完成同一次尝试；客户端 ID 会保留。绝不能用另一个目的地替换已记录的目的地。

对于超时、中断或结果不明的响应，使用 `--outcome uncertain --note <observed-failure>`；若被中断，也可以保留已持久化的 `dispatching` 状态。这两种状态都不能再次认领。按照确切唯一的交接包标记和来源任务，在原生 `list_threads`/`read_thread` 结果中查找；可用时核验实际初始提示和环境。仅一个已核实匹配可以登记为 created。有限列表中没有匹配、经过了一段时间或标题相似，都不能证明任务不存在。多个匹配或无法核验时，操作保持未解决；报告具体问题并保留交接包。不要自动创建替代任务。

只有明确的创建前拒绝，或其他已核实、能证明未创建任务的证据，才允许 `--outcome not-created --note <specific-evidence>`。这会转为 `failed`，此后新的认领产生新的尝试令牌。旧尝试结果不能更改新尝试。助手无法验证人工填写的说明是否属实：判断工具证据仍是代理的责任。它不为重试授予额外授权。

仅限 App Server stdio 备用路径：`thread/start` 可能在轮次持久化前返回有效 ID。若该进程在 `turn/start` 前退出，且新的 App Server 连接同时确认 `thread/resume` 返回 **no rollout**，完整的 `thread/list` 中也没有匹配 ID，先前的 `created` 收据才可通过 `--outcome not-persisted --note <these exact observations>` 完成。丢失的 ID 会保留在 `orphaned_destinations`；下一次 `claim` 才可在同一调用下授权一次替代尝试。不能将此例外用于超时、仍在运行的进程、已有任何轮次的任务，或仅在有限列表中缺少条目的情况。不要手动编辑收据。

使用 `show --receipt <receipt.json>` 检查状态。损坏或较旧 schema 的收据会被安全拒绝，并保持原样；根据交接包和原生工具证据核对，不要覆盖。不要用此助手重写历史收据。

此保证仅限本地且有条件：使用同一收据的协作调用者，每个尚未解决的尝试只能获得一次认领。文件与 Codex 外部任务创建之间不存在跨系统事务。若创建成功但结果保存失败，先前的 dispatching 状态会阻止盲目重试。收据不能替代任务核验；模拟测试也不证明真实应用绝不会重复创建任务。

<a id="frozen-request-and-prompt-integrity"></a>

## 冻结请求与提示完整性

新准备会写入 `handoff-request-v2` 封装，包含未改变的用户计划和确切的 `receiver_prompt_sha256`。交接包/历史发布成功后，相邻 `.prompt-integrity.json` 会在提示/请求发布或认领前，绑定提示绝对路径、哈希值和规范化的 `history_dir`。这样可避免归档失败留下指向未发布归档的新提示。后续在冻结前中断时，仍可核验已保存提示。可将保存的 v2 封装或旧版扁平 `.request.json` 直接作为 stdin 传给 `prepare_handoff.py --compact`；无需手动修改请求。

新认领前，准备过程会检查这些绑定；若已保存绑定包含 `history_dir`，也会检查归档冲突。提示被修改或截断时会失败，原请求/收据保留；不能读取改后文字并重新计算哈希来接受它。不要通过删除或重写绑定来修复。缺少归档字段的现有附属文件保持字节不变，而冻结请求已绑定完整计划。对于没有绑定的旧版扁平冻结请求，助手会重建本版本包含的已知旧版仅引用交接包的提示生成逻辑，只接受完全相同的字节。未知旧版提示措辞，或缺失的未绑定旧版提示，需要基于证据核对；保留全部原件。可识别的旧请求和提示保持字节不变，只新增附属文件。一旦绑定，未变更的提示可跨提示生成逻辑升级保留；旧提示可能没有新的内联来源/归档元数据，不得自动重写。

冻结新请求或认领前，交接包/提示/历史必须发布完成。若冻结前发现历史目录不兼容，在同一调用下选择合规目录，保留交接包/摘要身份。冻结请求不得仅为适应新历史目录而更改；使用下述旧版恢复协议。

## 一次启动观察

只有无错误、无冲突且已确认的 `threadId`，才允许一次 `wait_threads(timeoutMs: 0)` 快照，包括以 JSON 形式返回在 `content.text` 中的身份。并行记录原始创建结果和获取快照；不明或冲突的 ID 不能作为快照目标。若调用者无法可靠分类原始身份，先记录结果，再仅使用 `created` 结果的权威 `destination.threadId`，在同一次编排调用中获取快照。运行中是已启动的证据；排队中表示等待启动。就绪 ID 的快照数据为空闲、缺失或失败时，含义是**已创建、启动未确认**，不能认定未创建。保留目的地并说明实际快照错误。仅有客户端 ID 时，不能作为 `wait_threads` 目标。观察一次后停止；不要轮询业务工作，也不要为得到更强的启动确认而重新创建目的地。

## 原生结果记录

快速路径可将实际 `create_thread` MCP 结果作为 JSON stdin，传给 `native_result.py --receipt ... --attempt-id ...`。助手调用的是此收据协议，不是外部创建 API。它识别就绪和排队身份，以及已知且完全匹配的执行前 `approval policy is never` 拒绝。带有任何返回身份的错误、相互冲突的负载或未知失败，都保持 `uncertain`；绝不因缺少 ID 而猜测未创建。结果记录失败不允许再次调用创建。

对于失败或不明结果，助手在尝试说明中保留有长度上限的返回错误摘录，并在可用时以 `observed_error` 返回。这是观察证据，不是诊断：对用户报告时应隐去敏感细节；若工具未解释根因，应说明根因未知。保留的错误消息不授权另一次创建尝试。

对于不明结果，它还会在说明和 `observed_destinations` 中保留有长度上限的返回 ID。这些是用于核对同一次尝试的未核实候选，不会写入权威目的地，也不会允许再次认领，即使某个候选看起来合理。

已知策略冲突标记为 `failed`，不属于自动审核拒绝。恢复需要已核实的权限变更，以及对同一保存请求的新认领。不能仅因设置改变就替换尚未解决的尝试或已有目的地。受支持的受限模式及其局限见 [setup.md](setup.md#permissions-and-recovery)。

## App Server 运行状态

创建身份与执行状态分别记录。即使首轮随后失败或需要输入，`created` 收据仍是目的地的不可变证据。读取同一次尝试的 `.runtime.json`，查看 `state`、`threadId`、`turnId`、`writerReleased` 及任何 `requestMethod`/错误。启动响应不能证明桌面端可以接管任务。助手在完成、失败或收到交互请求后，关闭自己的 App Server；只有该进程退出后才记录 `writerReleased: true`。这不能证明其他客户端此后尚未取得该任务。

若为 `attention_required`，报告请求类型和已有任务链接。不要代用户批准、自动恢复同一受阻操作、删除锁文件、终止另一客户端的进程或创建替代任务。启动/设置失败后，若收据为 `uncertain` 且运行状态中有任务 ID，必须核对同一个 ID，不得盲目重试。技能更新前已启动的工作进程保留其已加载代码；更新技能不会恢复这些进程。

## 旧版准备在认领前停止

新准备先发布历史，再创建新提示/绑定；只有交接包/历史/提示发布成功后，才冻结 `.request.json`。因此，在提示尚未绑定时，已知不兼容的历史目录可在同一调用/输出目录下修正；交接包、摘要和其他身份字段保持不变。已经绑定的归档冲突需要保留原件并核对，即使请求尚未冻结也一样。跨技能升级进行兼容重试时，应复用已保存的接收提示，而不是为已有调用生成新措辞。

对于已因认领前历史失败而冻结的旧请求，保留每个现有文件。先根据观察到的失败和收据状态，确立未发出创建认领；仅仅缺少文件不能证明未创建任务。若结果不明，使用上面的正常核对流程。

确立认领前失败后，在交接包旁新增不可变修正说明，记录修正后的归档路径、原请求路径、实际来源 cwd 和已核实的目的地 cwd。使用 `history.py`，按修正后的归档及原交接包 ID/标题/来源发布未变更的包。若旧版包/提示把嵌套来源 cwd 当作接收 cwd，还需在旁边保存新的不可变恢复提示。该提示应同时指向未变更的包和修正说明；明确说明旧 cwd 仅是来源，接收端核验使用说明中的目的地 cwd。保留原提示，并在此次创建时发送恢复提示。只有现有正确提示已与新鲜核实的目的地一致时，才可复用它。在原生创建参数中保留当前证据支持的、用户明确选择的 model/thinking。随后使用原收据路径、交接包、调用和来源执行 `dispatch.py prepare` 和 `claim`；目的地工作区不同时，传入已核实的目的地工作区。只有此次新的成功认领才允许一次创建调用。继续使用同一收据，不重写请求，也不替换调用。旧请求继续记录被拒绝的归档选择；修正说明记录实际归档。

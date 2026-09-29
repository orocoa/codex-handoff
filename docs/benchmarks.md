# Measured performance · 性能测量

Measured on 2026-09-29, macOS 27 / arm64, Python 3.9.6. Compare alpha.16 with alpha.17 on the same machine. The operating-system filesystem cache was warm or uncontrolled. These are synthetic local checks, **not whole-handoff or model-latency benchmarks**. CPU utilization, peak memory, and energy were not measured.

测量日期 2026-09-29，macOS 27 / arm64，Python 3.9.6；同机对比 alpha.16 与 alpha.17。系统文件缓存已热或未受控。这些是合成本地测试，**不是整次 handoff 或模型延迟基准**；没有测量 CPU 占用、峰值内存和能耗。

## Local functions · 本地函数

Five samples per version and case; values are medians. / 每版本每场景 5 次，取中位数。

| Scenario / 场景 | alpha.16 | alpha.17 | Interpretation / 含义 |
|---|---:|---:|---|
| Resolve among 100 saved roots / 100 个保存目录中定位 | 811.47 ms | 13.19 ms | Git calls 100 → 1 / Git 调用次数减少 |
| Retry an already-created request / 已创建请求的相同输入重试 | 2.80 ms | 1.49 ms | fsync calls 10 → 5 / 同步调用减少 |
| Retry a registered entry in a 10,000-entry catalog / 万条目录的已登记记录重试 | 65.29 ms | 25.70 ms | Less JSON serialization and writing / 减少序列化与写入 |
| First preparation / 首次准备 | 4.60 ms | 5.00 ms | No improvement / 没有加速 |

The 10,000-entry catalog fixture contains metadata for old snapshots, not 10,000 complete packet files. This measures the catalog path, not whole-archive integrity. Repeated values depend on machine load, storage, path layout, and data shape.

万条 catalog 夹具预置的是旧快照元数据，并未生成万份完整交接包。它衡量目录处理成本，不证明整个档案的一致性。结果会随机器负载、存储、路径布局和数据结构变化。

## Transcript checks · 日志检查

Actual installed alpha.17 code. Three fresh Python processes per version and size, alternated; medians below. The first alpha.17 run is one additional sample. A fresh process is **not** a cold-disk test.

使用实际已安装的 alpha.17。每版每尺寸交替运行 3 个新 Python 进程，以下为中位数；新版首次运行另测 1 次。新进程**不等于**冷磁盘测试。

| Synthetic transcript / 合成日志 | alpha.16 | alpha.17 repeated / 后续运行 | alpha.17 first run / 首次运行 |
|---|---:|---:|---:|
| 1 MiB | 34.49 ms | 40.10 ms | 39.15 ms; no scan cache / 无扫描缓存 |
| 128 MiB | 443.13 ms | 96.77 ms | 521.99 ms; builds cache / 建立缓存 |

All runs agreed on compaction count, malformed lines, and partial tails. The large-log cached case improved; the small-log case and first large cache build did not. Logs below 4 MiB bypass scan caching. Larger logs with advisory state re-read and hash the complete old prefix, avoiding repeated JSON decoding. This still has O(total bytes) read cost, not O(appended bytes) I/O.

各次运行的压缩次数、坏行数和未完成尾行判断一致。大日志缓存命中有收益；小日志与首次建立大日志缓存没有收益。4 MiB 以下跳过扫描缓存；大日志启用状态时仍会读取并哈希旧前缀，只减少重复 JSON 解码。因此读取成本仍是 O(总字节数)，不是 O(追加字节数)。

## Text size and validation · 文本体积与验证

- `SKILL.md`: 6,741 → 5,595 bytes, about 17% less. / 入口文件字节数约减少 17%。
- Receiver prompt in the synthetic case: 1,160 → 1,036 bytes. / 合成案例的接收提示字节数减少。
- Recommended CLI output in that case: 2,096 → 1,992 bytes. / 该案例推荐命令的输出字节数减少。
- Installed release: **133 tests passed**, zero failures/errors/skips. / 安装后的版本 **133 项测试通过**，失败、错误与跳过均为零。

Text bytes are not measured model tokens or billed cost. No end-to-end latency reduction is claimed. The repository's tests exercise functional regressions and fake protocol servers; they are not a reproduction of these timing measurements.

文本字节数不是模型 token 数或计费成本，本项目不据此声称端到端延迟下降。仓库测试覆盖功能回归与模拟协议服务，不等同于复现此处性能测量。

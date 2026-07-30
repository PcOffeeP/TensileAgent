# `data/08_runtime` 目录说明

该目录保存 Agent 在本机运行时生成的临时媒体、诊断记录、传输追踪和评测结果。
除本说明文件外，目录内容均由 `.gitignore` 排除，不应提交到 Git。

运行产物可能包含原始视频副本、裁剪视频、模型输出和本机路径。复制、归档或对外分享前，
应先检查其中是否包含不适合公开的数据。不要把这里的文件当作训练数据或权威标注；
权威标签仍以 `data/02_annotations/` 中的 CSV 为准。

## 子目录

### `agent_clips/`

Agent 按采样区间从原视频生成的临时 MP4 clip。文件名通常包含视频 ID 和原视频时间范围，
部分由 Web 任务生成的文件还带有任务 UUID。它们用于发送给视觉推理服务，并可辅助回放
某一轮实际查看的视频片段。

这些文件可以由相同原视频和采样参数重新生成，但删除前应确认没有正在运行的任务引用它们。

### `diagnostics/`

Agent 的逐轮诊断 JSON 和任务汇总 JSON。常见文件包括：

- `<video_id>_round_XXXX_diagnostics.json`：单轮采样区间、模型结果、校验状态和边界更新；
- `<video_id>_diagnostics_summary.json`：一条视频完整运行的历史、终止状态和最终结果；
- `task_<id>_diagnostics_summary.json`：以任务 ID 命名的运行汇总。

该目录适合排查搜索策略、非法输出、冲突处理和终止原因。重复运行时，同名诊断文件可能被
后续任务更新；需要冻结证据时，应复制到独立的实验结果目录并记录 SHA256。

### `events/`

按运行时间分目录保存的 JSONL 事件流。每行是一条结构化事件，可用于还原任务开始、逐轮调用、
状态变化、最终结果或失败过程。时间目录用于区分不同批次，视频文件名或任务 ID 用于区分任务。

事件流主要面向运行过程审计；它与 `diagnostics/` 的区别是前者按时间记录事件，后者按轮次和
任务整理诊断快照。

### `llm_traces/`

决策模型的逐轮传输追踪，通常按任务 ID 或视频 ID 分目录，文件名为 `round-XXXX.json`。
内容包括经过脱敏的 messages、tools、tool calls、模型响应、token usage、耗时和错误信息。

追踪不应包含 API Key、Base64 视频载荷或临时媒体内容，但对外分享前仍需检查用户输入和本机
路径等上下文。

### `local_model_ab/`

本地决策模型 A/B 对照实验产物。每个时间戳目录通常包含：

- `report.json`：本次模型对照的汇总结果和运行身份；
- `traces/`：不同本地模型的逐轮传输记录。

该目录用于比较决策模型行为，不代表视觉模型训练或正式质量门结果。

### `results/`

开发诊断和一次性实验的汇总目录。当前主要包含：

- `cli_v4_1_accuracy30_*`：30 条 CLI 诊断集的逐视频结果、日志、CSV 和指标；
- `cli_v4_1_all110_*`：110 条视频批量运行结果；
- `isolation_oracle_clip_*`：使用真值附近 clip 测量视觉模型能力上限的实验；
- `isolation_policy_replay_*`：不重新推理、只回放历史轮次的 Agent 门槛归因；
- `isolation_joint_attribution_*`：模型能力与 Agent 策略的联合归因结果。

这里的结果属于开发或封闭语料评测。除非对应 manifest 和项目文档明确声明，否则不能表述为
独立测试、外部泛化或生产验收结果。

### `strategy_ab/`

Agent A/B/C 同预算策略评测的协议与产物：

- `protocol-development.json`：固定集合、输入文件、视频、配置和协议源码的 SHA256；
- `results/diagnostic30/`：每条视频的 A/B/C 原始结果、身份快照和临时 clip；
- `diagnostic30-report.json`：Presence、时间、类型、位置、调用次数和配对统计；
- `diagnostic30-blocked-audit.json`：被完整性检查阻止的历史运行审计。

目录名带 `max512m` 表示仅提高了客户端请求体上限，以允许长视频 Base64 请求通过；
它不表示模型、Prompt、schema、切片策略或推理服务发生变化。

`locked80` 是受保护的一次性评测集合。开发诊断不得创建
`LOCKED80_STARTED.json`，也不得启动或消费 `locked80`。

### `web_workbench/`

Web 工作台的私有运行状态：

- `uploads/`：用户上传或任务复制的视频；
- `events/`：Web 任务事件流；
- `history/`：可恢复的任务历史；
- `sessions/`：会话状态；
- `private_runtime_index.json`：本机运行索引。

这些文件属于本机工作台状态，可能包含用户输入和上传媒体，不应提交或直接对外发布。

## 使用与清理建议

- 查看正式实验结果时，优先从对应实验目录的 manifest、身份文件和报告开始。
- 复现某条结论时，同时保留原视频 SHA256、clip manifest、逐轮结果和部署身份。
- 不要在任务运行期间清理 `agent_clips/`、`web_workbench/` 或当前实验目录。
- 清理旧产物前，先确认它们没有作为项目说明书、评测报告或问题复现的证据。
- `data/08_runtime/` 的存在不是程序启动前提；缺少的子目录会在需要时重新创建。

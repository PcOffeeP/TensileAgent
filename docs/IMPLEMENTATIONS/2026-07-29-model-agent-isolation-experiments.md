# 模型能力与 Agent 策略隔离实验

> 日期：2026-07-29
> 状态：待执行
> 目的：判断当前低召回和字段缺失主要来自视觉模型、Agent 采样策略，还是 Agent 终止与字段聚合门槛。
> 边界：仅做开发诊断，不修改生产默认策略，不构成 V4.1 质量门重算或生产批准。

## 非目标

- 不重新训练、微调或替换视觉模型；
- 不重新运行完整 110 条；
- 不测试 Web 工作台 ping、并发或会话状态；
- 不修改现有 30 条基线结果；
- Oracle 主实验不评价未夹紧和视频异常，特殊场景只在历史回放中保留现状归因；
- 不把 P1/P2 直接切换为默认或生产策略。

## 一、已知基线

当前 30 条分层 CLI 诊断集保存在：

```text
data/08_runtime/results/cli_v4_1_accuracy30_20260729/
```

权威标签：

```text
/Users/pcoffeep/AgentPlayground/active-projects/
mVllm_2-data-backups/pre-semantic-portal-20260723/
data/02_annotations/all_videos_tag.csv
```

原始视频：

```text
/Users/pcoffeep/AgentPlayground/active-projects/
mVllm_2-data-backups/pre-semantic-portal-20260723/
data/01_videos/
```

基线样本组成：

- 17 条断裂；
- 8 条普通未断裂；
- 5 条特殊场景：1 条未夹紧、4 条视频异常。

冻结 V4.1 口径下的关键结果：

| 指标 | 基线 |
|---|---:|
| 断裂 Precision | 87.50% |
| 断裂 Recall | 41.18% |
| 普通未断裂 Recall | 87.50% |
| 时间容差命中率 | 23.53% |
| 断裂模式准确率 | 6.67% |
| 断裂位置准确率 | 35.29% |
| 特殊场景准确率 | 0% |
| 断裂样本全字段成功率 | 0% |

固定的 30 条视频 ID：

```text
video_0001 video_0002 video_0003 video_0004 video_0005
video_0006 video_0007 video_0008 video_0009 video_0010
video_0014 video_0017 video_0025 video_0026 video_0027
video_0033 video_0034 video_0040 video_0042 video_0049
video_0052 video_0054 video_0058 video_0066 video_0069
video_0076 video_0083 video_0096 video_0102 video_0106
```

其中 17 条断裂视频：

```text
video_0001 video_0003 video_0004 video_0006 video_0007
video_0008 video_0009 video_0010 video_0014 video_0017
video_0025 video_0026 video_0027 video_0033 video_0040
video_0076 video_0102
```

## 二、必须冻结的共同条件

两个实验必须记录并校验以下身份，任一项发生漂移时停止实验：

- contract version：`tensile-vlm/v4.1`；
- contract hash：`3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`；
- deployment manifest 全字段；
- 模型、adapter、processor、transformers 和运行设备身份；
- V4.1 固定分析 Prompt 和确定性 generation 参数；
- 源视频 SHA256；
- 测试清单 SHA256；
- 标签 CSV SHA256。

临时脚本放在 `/tmp`，不要写入项目。结果统一写入
`data/08_runtime/results/`，不要覆盖现有 30 条基线。

正式执行前：

```bash
uv run python -m agent.doctor \
  --config /tmp/tensile-isolation/v4_1_isolation.yaml
```

当前默认 32 MiB 请求上限无法覆盖长视频。实验临时配置可以使用 1 GiB 上限，但必须在报告中记录；
该调整只解除传输限制，不得改变模型、Prompt 或 Agent 语义策略。

## 三、实验一：Oracle Clip 模型能力上限

### 3.1 目标

绕过 Agent 的搜索、确认、终止和字段聚合逻辑，直接回答：

> 当视觉模型已经拿到包含真实断裂时刻的局部 clip 时，它能否识别断裂、模式和位置？

本实验不评价 Agent 时间定位能力，因为 V4.1 模型本身不输出最终时间。

### 3.2 输入构造

仅对 17 条真实断裂视频执行主实验。对每条视频从 CSV 读取真值断裂时刻 `t` 和视频时长 `D`，
生成一个固定 6 秒 oracle clip：

```text
start = max(0, t - 3)
end   = min(D, t + 3)
```

若靠近视频边界导致区间不足 6 秒，应在不越界的前提下向另一侧补足。clip 构造必须复用
`FfmpegVideoClipBuilder.build_with_manifest()`，保留原视频帧与时间映射。

真值时间只允许用于选取 clip，不得进入模型 Prompt、JSON 或对话上下文。每条视频只进行一次
V4.1 主分析调用，不请求 evidence 文本，不经过 `IterativeAgent`。

### 3.3 调用链

临时程序应执行：

1. 读取标签与固定的 17 条 ID；
2. 生成 oracle clip 和 manifest；
3. 创建与当前 CLI 相同配置的 `LlamaFactoryInferenceClient`；
4. 执行一次 `preflight()` 并锁定 deployment manifest；
5. 对每个 oracle clip 调用一次 `infer()`；
6. 保存原始模型输出、解析错误、server preprocessing、request ID、帧时间和 clip hash；
7. 不根据标签修正、重试或重写模型输出。

输出目录建议：

```text
data/08_runtime/results/isolation_oracle_clip_v4_1_20260729/
```

至少生成：

```text
manifest.json
raw_predictions.jsonl
per_video.csv
metrics.json
```

### 3.4 指标

断裂存在性判定：

- `clip_state in {"发生断裂", "已断裂"}` 视为识别到断裂；
- `未断裂`、`临界未断裂`、`无法判断`均不算断裂命中；
- 非法 JSON 或调用失败计为错误，不从分母删除。

报告：

- oracle fracture recall：分母固定为 17；
- `clip_state` 混淆分布；
- mechanism exact accuracy：按 V4.1 canonical 口径，分母固定为有机制真值的 15 条；
- site exact accuracy：分母固定为 17；
- mechanism/site 字段可用率；
- 按断裂类型分组的 recall；
- schema 合法率和推理成功率。

建议追加一个 clip 宽度敏感性测试，但不能替代 6 秒主结果：

```text
2 秒：[t-1, t+1]
12 秒：[t-6, t+6]
```

只有同一模型、同一部署、同一 17 条样本才允许比较。

### 3.5 解释

| Oracle 结果 | 含义 |
|---|---|
| Oracle recall 仍接近当前 41% | 模型检测能力是主要瓶颈 |
| Oracle recall 明显高，但 mechanism/site 仍差 | 模型能检测事件，但分类能力不足 |
| Oracle 检测和字段均明显高于 Agent | Agent 搜索、确认或聚合损失显著 |
| 2 秒好、12 秒差 | 模型对长上下文和稀疏采帧敏感 |
| 三种宽度均差 | 不是搜索区间宽度可以解决的问题，应回到训练数据或模型 |

## 四、实验二：现有历史的 Agent 门槛反事实回放

### 4.1 目标

不重新调用模型，直接使用同一批 30 条运行时的逐轮模型输出，回答：

> 模型是否曾经在某一轮给出正确证据，但被 Agent 的双重确认、时间交集或字段投票规则丢弃？

这个实验首先只做离线回放，不修改 `IterativeAgent`。

### 4.2 输入快照

逐轮历史目前位于：

```text
data/08_runtime/diagnostics/<video_id>_diagnostics_summary.json
```

这些文件可能被后续运行覆盖。执行实验前必须：

1. 校验 30 条 summary 均存在；
2. 校验 `video_id`；
3. 校验 history 非空；
4. 将它们复制到本次结果目录的 `history_snapshots/`；
5. 记录每个文件 SHA256；
6. 后续只读取快照，不读取可能变化的 diagnostics 原路径。

输出目录建议：

```text
data/08_runtime/results/isolation_policy_replay_v4_1_20260729/
```

### 4.3 每条视频需要提取的事实

对每轮 history 提取：

- `sample_range`；
- `clip_state`；
- `fracture_mechanism`；
- `fracture_site`；
- `special_case`；
- `inferred_time_range`；
- 是否为局部 clip；
- parser/validation/infra error；
- request ID、clip hash 和实际帧时间。

把正证据定义为：

```text
clip_state in {"发生断裂", "已断裂"}
```

每条视频计算：

- `positive_round_count`；
- `local_positive_round_count`；
- 是否出现过正确 mechanism；
- 是否出现过正确 site；
- 是否存在包含真值时间的正证据区间；
- 当前最终状态和字段。

### 4.4 错误归因分桶

对 17 条真实断裂固定分桶：

| 分桶 | 条件 | 解释 |
|---|---|---|
| M0 | 逐轮历史中没有任何正证据 | 模型或采样未发现事件 |
| G1 | 只有一次正证据，或没有局部正证据 | 双重确认门槛造成潜在损失 |
| G2 | 已有至少两次正证据和局部正证据，但最终不是 fracture | 终止、预算、状态机或聚合问题 |
| F1 | 历史出现过正确字段，但最终字段为 null/错误 | 字段投票门槛造成损失 |
| T1 | 历史存在包含真值的事件区间，但最终时间为空/错误 | 时间交集或终止逻辑造成损失 |

对 8 条普通未断裂视频同时统计：

- 是否出现过一次伪正证据；
- 是否出现过两次伪正证据；
- 如果采用单正证据策略，预计会增加多少假阳性。

这一步可以在不改代码、不重新推理的情况下计算当前门槛带来的 Recall/Precision 交换。

### 4.5 三种离线策略

对完全相同的历史输出回放以下策略：

#### P0：当前严格策略

- 至少两次正证据；
- 至少一次局部正证据；
- mechanism/site 至少两次非空且一致；
- 时间要求至少两个正区间交集有效且不超过容差。

P0 的回放结果必须与现有公开结果一致，否则先修复回放器。

#### P1：单正证据筛查策略

- 任一合法局部正证据即标记为 `suspected_fracture`；
- 不直接声称高置信 fracture；
- 不允许输出 `no_fracture`；
- mechanism/site 取最佳正轮次的单次非空值，但标记为低证据；
- 时间取最窄合法正证据区间，但标记为未确认。

P1 用于计算“如果不把一次正证据丢掉，筛查 Recall 能提高多少”，不建议直接替换公共契约。

#### P2：单正证据触发强制复查

离线回放只能统计 P2 的触发数量，不能伪造第二次模型结果：

- 首次合法正证据出现后，禁止继续普通五区间阴性覆盖；
- 对同一区间或其子区间安排一次强制复查；
- 第二次正证据确认 fracture；
- 第二次为负或无法判断时输出 suspected/unrecognized，不得直接降级为 no_fracture。

如果 P1 表明 Recall 有明显收益且普通负类伪正证据可控，再由主对话在隔离分支实现 P2，
并使用同一 30 条测试集进行真实 A/B。

### 4.6 指标

输出：

- M0/G1/G2/F1/T1 样本数量和 video ID；
- P0、P1 的 presence confusion matrix；
- Precision、Recall、F1、Specificity；
- mechanism/site 的“历史曾正确”与“最终正确”差值；
- time 的“历史曾命中”与“最终命中”差值；
- P2 预计触发复查的正负样本数量；
- 每种策略的弃答率；
- 逐视频反事实表。

至少生成：

```text
manifest.json
history_hashes.json
per_round.csv
per_video_counterfactual.csv
metrics.json
```

## 五、联合判定矩阵

完成两个实验后按下表归因：

| Oracle 模型 | 历史回放 | 主要结论 |
|---|---|---|
| 低 | P1 相比 P0 提升很小 | 模型能力是主要瓶颈 |
| 高 | M0 很多 | Agent 粗采样没有把正确局部片段交给模型 |
| 高 | G1/G2 很多 | Agent 确认、终止或预算策略是主要瓶颈 |
| 字段高 | F1/T1 很多 | Agent 字段投票和时间交集规则过严 |
| 字段低 | F1/T1 很少 | 模型分类和定位字段能力不足 |
| 两边都差 | 多类错误并存 | 模型与 Agent 不匹配，需要同时调整 |

不要仅凭总体 Accuracy 下结论。报告必须明确区分：

1. 模型在 oracle clip 上的能力上限；
2. Agent 是否采样到过正证据；
3. Agent 是否丢弃了已经出现的正确证据；
4. 放宽门槛可能增加的假阳性。

## 六、执行顺序

1. 冻结 30 条 history summary 和全部身份 hash；
2. 先执行实验二的离线回放；
3. 再执行实验一的 17 条 oracle clip；
4. 生成联合归因报告；
5. 只有证据表明 G1/G2/F1/T1 占比较高时，才实现临时 P2 策略；
6. P2 只能通过临时配置或隔离分支启用，当前严格策略继续作为默认；
7. 使用相同 30 条进行 A/B，不立即扩展到 110 条。

这样排序的原因是：离线回放不产生新的模型调用，能够先判断现有证据是否已经足够解释问题。

## 七、影响范围

第一阶段只允许新增：

- `/tmp/tensile-isolation/` 下的临时 oracle、回放和评分程序；
- `data/08_runtime/results/isolation_*` 下的忽略产物。

离线回放和 oracle 实验不应修改 `agent/`。只有在 P1 证明确有收益后，后续 P2 才可能影响：

- `agent/iterative_agent.py`：首次局部正证据后的强制复查状态；
- `agent/schema.py`：仅当决定公开新增 suspected 状态时才评估，当前实验不改；
- `tests/test_iterative_agent.py`：正证据复查、冲突、预算和负类伪正覆盖；
- 临时实验配置：必须默认关闭 P2。

## 八、完成标准

实验只有在以下条件全部满足时才算完成：

- 所有分母固定且报告中可见；
- 调用失败和非法输出不从分母删除；
- Oracle 与 Agent 使用相同模型和 contract 身份；
- P0 回放能够复现当前公开结果；
- 没有使用真值选择模型输出或反事实策略结果；
- 所有原始输出、history hash 和逐样本归因可追踪；
- 明确给出“模型主因 / 采样主因 / 聚合主因 / 混合原因”的证据结论；
- 不修改或覆盖现有 30 条基线结果。

验证命令：

```bash
python3 -m pytest tests/test_iterative_agent.py \
  tests/test_sampling.py \
  tests/test_parser.py \
  tests/test_inference.py -q
git diff --check
```

如果仅执行临时 oracle 和离线回放脚本，没有修改 Agent 源码，则只需要校验结果完整性和
`git diff --check`；P2 若进入代码实现，必须补充针对单正证据、复查冲突、负类伪正和预算耗尽的单元测试。

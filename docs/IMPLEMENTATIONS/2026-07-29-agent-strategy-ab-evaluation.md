# Agent 动态策略同预算 A/B 评测

> 日期：2026-07-29
>
> 状态：已批准，实施中
>
> 目的：在没有新增视频的约束下，证明固定 V4.1 视觉模型条件下，动态 Agent
> 是否优于固定覆盖扫描；结果不解释为视觉模型的外部泛化性能。

## 目标与范围

本实验冻结 `v4.1-agent-pipeline-fold0-r1`、V4.1 Prompt/schema/generation、
服务 deployment manifest 和源视频，比较三种策略：

- A：完整视频单次 VLM，作为低调用成本锚点；
- B：固定覆盖扫描；
- C：当前动态 Agent。

主比较是 B 与 C 的逐视频同调用预算配对差值。A 不套用两轮 Agent 终止门槛，
直接按单 clip 原始模型输出评分，并将时间字段记为不可用。

本轮同时修正 V4.1 时间收敛：搜索采样范围可以为探索而扩展，但可信事件边界只能由
合法方向证据单调收缩。存在性和时间可用性分项验收；断裂存在性成立但时间未收敛时，
返回 `fracture + time unavailable`。

## 非目标

- 不训练、替换或修改视觉模型；
- 不改变视觉 Prompt、schema、generation 或服务预处理；
- 不做更细 clip、帧密度或宽度敏感性实验；
- 不优化延迟、并发、编码或缓存；
- 不把现有 110 条重新包装为外部独立测试；
- 不放宽“两轮正证据且至少一轮为局部证据”的 fracture presence 门槛；
- 不启用单正证据 P2 策略。

## 数据边界

当前 Fold0 源视频级划分为 train59、validation30、test21。现有诊断30与它们分别重叠
train18、validation8、test4。由于 Stage G 已消费 test21，且其中4条进入逐样本诊断，
本实验使用以下固定角色：

| 集合 | 数量 | 角色 |
|---|---:|---|
| `diagnostic_30` | 30 | 策略开发、失败分析、单元测试设计 |
| `locked_80` | 80 | 策略冻结后一次性主要配对评测 |
| `confirmatory_test_17` | 17 | `locked_80` 内部确认子集 |
| `legacy_test_21` | 21 | 历史 held-out 连续性 |
| `all_110` | 110 | 包含性敏感性分析 |

`locked_80` 包含 Fold0 train41、validation22、test17。因此其 B−C 差值只能描述
“固定模型和封闭语料条件下的 Agent 策略增益”，不能描述视觉模型泛化。
`confirmatory_test_17` 未进入逐样本诊断，但 test21 聚合指标此前已暴露，不能称为
untouched、independent 或 new held-out。

## 方案比较

### 方案一：仅比较相同最大预算

B 固定运行10次，C 最多运行10次。实现简单，但 C 可能提前终止，实际调用量不同，
无法把差值完全归因于动态策略。

### 方案二：逐视频调用数匹配

先运行 C 并记录每条视频实际发出的全部 VLM 请求数 `N_i`，包括失败、非法输出和特殊复查。
B 使用预先冻结的固定窗口序列，仅执行前 `N_i` 次。该方案保证逐视频调用数相同，
不要求改变 C 的自然终止行为。

### 方案三：强制 C 恰好运行10次

能获得完全固定预算，但终止后的强制复查会改变当前 Agent，测量对象不再是现有策略。

采用方案二。若以后另做 B@10，只能作为固定预算敏感性结果，不能把它与自然终止 C
直接表述为严格同预算比较；本次实现不额外发出 B@10 请求。

## 固定窗口

B 的冻结顺序为：

1. 完整视频 `[0,D]`；
2. 当前五个阴性覆盖窗口，起点依次为
   `0,6D/32,12D/32,18D/32,24D/32`；
3. 四个补充覆盖窗口，起点依次为
   `3D/32,9D/32,15D/32,21D/32`。

按时间排序后，九个窗口完整覆盖 `[0,D]`，相邻窗口重叠 `5D/32`。前五个局部调用
与当前阴性覆盖窗一致，因此 B 在第6次调用后具备与 C 相同的 no-fracture 覆盖机会。
窗口只由视频时长决定，不读取标签或真值断裂时间。

## 单调事件边界

V4.1 为每个任务维护独立的可信边界 `event_bounds=[L,U]`，初始为 `[0,D]`。
只有合法、身份校验通过的语义结果可以更新：

```text
未断裂 / 临界未断裂：L' = max(L, sample_end)
已断裂：             U' = min(U, sample_start)
发生断裂：           [L',U'] = [L,U] ∩ sample_range
无法判断：           不更新
```

更新必须满足：

- 新边界只能是旧边界的子区间；
- 没有收缩时记录 no-op；
- 空区间记录 conflict，保留旧可信边界；
- 探索回退只能改变下一轮 `candidate/sample_range`，不能扩大 `event_bounds`；
- 只有对产生冲突的同一 `sample_range` 进行合法“发生断裂”复查，才可解决先前边界冲突；
- 最终时间只读取 `event_bounds`，不再对全部历史正区间二次求交。

公开时间需要同时满足：

- fracture presence 已由至少两轮正证据确认；
- 至少一轮正证据来自严格局部 clip；
- `event_bounds` 非空且没有未解决冲突；
- `U-L <= tolerance_seconds`，当前为1秒。

不满足时仍可返回 fracture，但 `time_range=null`。评分中的 ±1 秒是命中容差，
不会用于扩大公开区间。

## B 与 C 的公共 reducer

B 与 C 必须共享以下确定性语义：

- 正证据：`clip_state in {"发生断裂", "已断裂"}`；
- fracture：至少两轮正证据，且至少一轮为局部 clip；
- no-fracture：五个冻结阴性覆盖窗均为合法普通 `未断裂`；
- 其余情况：`unrecognized`；
- mechanism/site：至少两个合法正轮次给出相同非空值，平票或不足时不可用；
- 时间：只按上节的单调 `event_bounds` 规则公开。

特殊样本的 C 路径要求同一区间重复确认，而冻结 B 窗口不含重复区间，因此特殊样本只做
各方法描述性结果，不进入 B−C presence 主配对指标。

A 作为单次原始模型基线，不使用该多轮 reducer：

- `发生断裂/已断裂` 映射为 fracture；
- `未断裂/临界未断裂` 映射为 no-fracture；
- `无法判断` 映射为 unrecognized；
- mechanism/site 仅作为单轮字段评分；
- time 固定不可用。

## 运行与停止调参

运行 `locked_80` 前必须冻结并记录：

- Agent commit、评测代码 commit 与策略版本；
- 五个集合的 ID 清单和 SHA256；
- 标签 CSV、源视频和 split 文件 SHA256；
- 模型、adapter、processor、framework、device 和 deployment manifest；
- Prompt/schema/generation；
- A/B/C 调用预算、固定窗口和失败计数规则；
- reducer、时间边界、弃答、冲突和评分规则；
- 主要指标、切片和配对统计方法。

执行纪律：

1. 先在 `diagnostic_30` 完成代码与评测器验证；
2. 冻结后一次性完成 `locked_80` 三种方法的全部预测；
3. 运行期间标签不可见，不根据单视频输出修改、重试或重写策略；
4. 全部完成后一次性评分并同时生成80、17、21、110切片；
5. 80或17结果一旦查看即视为已消费，后续修改只能作为新的开发结果。

## 指标

主指标：

- Presence Precision、Recall、F1、Specificity；
- unrecognized/abstention rate；
- B−C 逐视频胜、负、平；
- B−C paired bootstrap 95% confidence interval。

次指标：

- time availability、严格区间命中率、±1秒命中率；
- mechanism/site exact accuracy 与 availability；
- 特殊场景单独结果；
- 每视频发出请求数、有效响应数、非法输出和基础设施失败数。

所有指标显示固定分母。总体 Accuracy 不是主要结论。

## 失败处理

- 请求已发出即计入预算，传输失败、非法输出和特殊复查不从预算删除；
- deployment、contract、Prompt 或输入 hash 漂移立即停止整批运行；
- 成功结果不可覆盖，失败重试必须显式授权并保留先前记录；
- 非法 JSON、调用失败和弃答保留在分母中；
- A/B/C 任一方法缺少某视频结果时，不生成配对主结论。

## 验证

本机：

```bash
uv run python -m pytest tests -q
git diff --check
```

训练机先用全部110个源视频生成开发 manifest 并运行诊断30：

```bash
uv run python scripts/prepare_strategy_ab.py \
  --splits-dir /path/to/mVllm_2/data/05_splits \
  --annotations /path/to/mVllm_2/data/02_annotations/all_videos_tag.csv \
  --videos-root /path/to/mVllm_2/data/01_videos \
  --config agent/config.yaml \
  --output data/08_runtime/strategy_ab/protocol-development.json

uv run python scripts/run_strategy_ab.py \
  --manifest data/08_runtime/strategy_ab/protocol-development.json \
  --set diagnostic30 \
  --videos-root /path/to/mVllm_2/data/01_videos \
  --results-root data/08_runtime/strategy_ab/results-development

uv run python scripts/score_strategy_ab.py \
  --manifest data/08_runtime/strategy_ab/protocol-development.json \
  --set diagnostic30 \
  --results-root data/08_runtime/strategy_ab/results-development \
  --output data/08_runtime/strategy_ab/diagnostic30-report.json
```

诊断完成并提交全部代码与配置后，从 clean worktree 重新加 `--freeze` 生成正式 manifest。
正式 manifest 下先重跑 diagnostic30，再使用下面的显式确认串启动一次 locked80；marker
允许同一结果目录断点续跑，但拒绝换目录开启第二次主评测：

```bash
uv run python scripts/run_strategy_ab.py \
  --manifest data/08_runtime/strategy_ab/protocol-frozen.json \
  --set locked80 \
  --videos-root /path/to/mVllm_2/data/01_videos \
  --results-root data/08_runtime/strategy_ab/results-frozen \
  --consume-locked80 I_UNDERSTAND_LOCKED80_IS_ONE_TIME
```

完成后分别用 `--set locked80`、`confirmatory_test17`、`legacy_test21` 和 `all110`
生成报告；后两者会从同一个正式结果根目录内的 diagnostic30 与 locked80 两个互斥目录
汇总，不会重新调用模型。

## 对外口径

允许：

> 在现有封闭110视频语料、固定Fold0 VLM、固定Prompt和逐视频相同视觉调用预算下，
> 动态Agent相对固定覆盖扫描取得了配对策略增益。

禁止：

- independent test、new held-out、external validation；
- 模型泛化能力提升；
- 对其他材料、设备或采集分布的普遍性能；
- production-ready 或最终质量门通过。

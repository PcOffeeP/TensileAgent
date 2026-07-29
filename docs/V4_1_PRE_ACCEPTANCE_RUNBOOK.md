# TensileAgent V4.1 中间模型集成运行手册

## 当前授权边界

当前 V4.1 服务消费 Stage B 冻结的
`v4.1-agent-pipeline-fold0-r1` 中间开发模型，来源身份为
`stage-b-intermediate-8e1fdb09f8e6`。原 Stage B 质量门和 LOSO
门仍为失败；本路线只授权 Stage E pre-acceptance、Stage F Agent 集成和 Stage G
一次性联合验收准备，不代表模型质量门通过，不授权重训、正式别名、生产切换或读取
sealed labels。

运行时视觉契约为 `tensile-vlm/v4.1`，hash 为
`3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`。
其 analysis prompt 已采用本轮补全合法枚举和时间状态判定顺序后的版本。

预验收配置使用 `v4.1-interval-policy-v1` 确定性 Planner。它只提出下一次工具调用；
首轮全视频、覆盖/复查区间、候选更新、证据门和最终终止仍全部由
`IterativeAgent`/Verifier 强制执行。这样不引入新权重或外部凭据，也避免决策模型与
VLM 争用同一张 GPU。默认 V2/Qwen 配置保持不变。

## 单视频预验收

训练机使用显式配置，禁止任务内自动回退到 V2：

```bash
python3 -m agent.doctor --config agent/config.v4_1.pre_acceptance.yaml
python3 -m agent.run \
  --video /absolute/path/video_0001.mp4 \
  --config agent/config.v4_1.pre_acceptance.yaml \
  --contract-version tensile-vlm/v4.1
```

公共结果 schema 为 `tensile-agent/result/v4.1`。三级断裂位置为
`inside_gauge`、`outside_gauge_non_root`、`grip_root`；确认的 `未夹紧` 或
`视频异常` 必须投影为 `status=unrecognized` 和同名 `special_case`，不能写成普通
`no_fracture`。

## 可恢复批处理

批处理只能使用冻结的 `agent-acceptance-manifest`：

```bash
python3 scripts/run_v4_1_acceptance_batch.py \
  --manifest /absolute/path/agent_acceptance_manifest.json \
  --stage-g-authorization /absolute/path/stage_g_authorization.json \
  --input-list all_110 \
  --output-dir data/08_runtime/v4_1_acceptance
```

每个视频独立保存事件、工作目录和身份绑定结果。成功结果不可覆盖；默认保留失败，
只有纯基础设施恢复时才使用 `--retry-failed`。任一 input-list hash、配置 hash、
manifest hash 或 deployment identity 漂移均 fail closed。
`all_110` 和 `heldout_21` 还必须提供与 acceptance manifest 精确绑定的一次性
Stage G authorization；缺少 Stage D 前置或授权文件时 runner 在首次 VLM 调用前拒绝。

## 评分

评分规范位于 `agent/scoring/v4_1_agent_acceptance_v1.json`。Stage F 只允许合成金样例
测试，不读取 held-out 语义标签。Stage G 唯一一次开封后才可运行：

```bash
python3 scripts/score_v4_1_acceptance.py \
  --annotations /absolute/path/all_videos_tag.csv \
  --results-root data/08_runtime/v4_1_acceptance \
  --spec agent/scoring/v4_1_agent_acceptance_v1.json \
  --output data/08_runtime/v4_1_acceptance/accuracy_report.json
```

评分器固定区分全量 110 条描述性指标和 21 条 source-held-out 主指标；不得混算或在
查看 held-out 预测后修改映射、阈值、模型、Agent、问题或配置。

## 显式 V2 回滚

V2 仍使用 `agent/config.yaml` 或显式
`--contract-version tensile-vlm/v2`。回滚必须在新任务中完成，不允许同一任务中
从 V4.1 自动降级到 V2。

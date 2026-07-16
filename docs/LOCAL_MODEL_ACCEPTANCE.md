# 本地决策模型验收记录

> 日期：2026-07-16
> 正式 A/B 运行目录：`data/08_runtime/local_model_ab/20260716-185242/`（Git 忽略）

## Agent-only A/B

两个模型使用同一组 20 个场景，其中 5 个关键场景各运行 3 次，每个模型共 30 次调用。场景包含继续采样、合法终止、MiniCPM 非法输出、基础设施失败、无关文本和 Prompt 注入。

| 模型 | digest | 结构合法率 | 参数 schema 合法率 | 预期工具率 | 未定义工具 | 平均耗时 |
|---|---|---:|---:|---:|---:|---:|
| `tensile-qwen35:9b` | `079e71a587e3...54bbca2` | 100% | 100% | 100% | 0 | 12.76 s |
| `tensile-qwen3:8b` | `7ef4ca800d20...57eaa5` | 100% | 100% | 100% | 0 | 6.31 s |

两者都达到功能验收门槛。按已批准方案保留 `tensile-qwen35:9b` 为默认；`tensile-qwen3:8b` 作为延迟更低的手动对照。逐轮请求、工具 schema、工具调用、usage 和脱敏响应均保存在该运行目录的 `traces/` 中。

## 真实跨仓 smoke

使用真实视频 `video_0015.mp4`，本地 `tensile-qwen35:9b` 通过 SSH 隧道调用训练机 MiniCPM 服务。

- 决策请求的 backend/model/digest 均为本地 Ollama，三轮均产生 `sample_and_infer` 合法工具调用。
- 首轮 MiniCPM 在两次校正后返回完整四字段，证明本地 Agent → 视频裁剪 → 训练机 MiniCPM 链路实际可达。
- 第二轮 MiniCPM 在两次校正后仍返回非法 `fracture_between/type/location`，Agent 未补造字段，而是保留 invalid-output 证据并继续采样。
- 第三轮训练机代理在三次传输尝试后仍返回 HTTP 502，当前任务按 fail-closed 失败，没有回退至 `qwen3.7-max`，也没有产生伪造结论。

对应证据位于 `data/08_runtime/llm_traces/video_0015/` 和 `data/08_runtime/diagnostics/video_0015_*`（均为 Git 忽略运行产物）。这一 smoke 验收了本地决策链路、真实 MiniCPM 传输和拒绝造数机制，但不代表 MiniCPM 任务效果已达标。HTTP 502 和非法视觉输出仍是后续需要处理的训练机侧问题。

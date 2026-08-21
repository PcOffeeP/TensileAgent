# TensileAgent 项目工作准则

## 项目边界

- 本仓库只维护 Agent 决策系统、Web 交互、运行时契约和交付验证；模型训练、权重、训练数据流程与视觉推理服务发布由相邻的 `mVllm_2` 仓库负责。
- 不要把训练流水线、LLaMA-Factory 源码、模型权重或训练侧依赖重新引入本仓库。两侧通过 HTTP API、版本化契约和轻量交付清单协作。
- 涉及两个仓库的变更必须保持职责分离；本仓库不得依赖训练机上的源码、私有数据或本地绝对路径才能运行。

## 设计与文档

- 只有复杂、跨模块、需要交接或用户明确要求的任务才在 `docs/plans/` 中创建设计或实施文档；普通修改不要求额外文档门禁。
- 当目标、范围、公共契约、核心流程或验收标准发生变化时，同步更新对应的当前文档。用户已经授权实施后，无需仅因文档更新再次等待批准。
- `docs/results/`、`delivery/history/` 和回滚记录是历史证据，不是当前实现依据。不得从历史材料恢复已废弃的契约或运行路径。

## Agent Runtime 不变量

- 决策模型只负责提出工具调用或终止建议；候选区间更新、覆盖检查、冲突处理、非法输出处理和最终状态必须由代码确定，不能完全信任模型参数。
- 当前运行时使用 Native Function Calling，不为 Agent 决策循环引入 MCP。
- V4.1 视觉输出只提供方向语义，事件边界由代码单调维护；不得让模型直接决定最终时间边界，也不得在同一任务中自动降级到旧契约。
- `fracture`、`no_fracture` 和 `unrecognized` 必须满足各自的代码级证据与终止条件；基础设施错误、契约漂移或预处理元数据缺失不得伪装成有效视觉结论。
- 每轮推理后，下一轮上下文必须包含更新后的候选区间和必要历史，保证迭代决策基于最新状态。

## 验证与产物

- Agent Runtime 修改应优先运行对应测试；涉及状态机、采样、解析或推理链路时，重点覆盖 `tests/test_iterative_agent.py`、`tests/test_sampling*.py`、`tests/test_parser.py` 和 `tests/test_inference.py`。
- 项目级验证命令为 `python3 -m pytest tests -q`；前端修改运行 `cd web && npm run build`；交付 bundle 修改运行 `python3 scripts/validate_delivery_bundle.py --mvllm-root ../mVllm_2`。
- 动态帧、临时 clip、LLM trace 和其他运行时产物写入 `data/08_runtime/`，不得提交。不要提交视频、模型权重、checkpoint、密钥、token 或大型生成结果。

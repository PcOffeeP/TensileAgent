# TensileAgent 项目工作准则

## 项目边界

- 本仓库只维护 Agent 决策系统、Web 交互、运行时契约和交付验证；当前 `tensile-vlm/v4.1`（及回滚 `v2`）的冻结视觉推理服务与交付上游由相邻的 `mVllm_2` 仓库负责。
- 新一代五类标注、数据流程、模型微调与离线评测在相邻工作区 `TensileAgent-Finetune`（`mVllm_2` 仓库的 `feat/tensileagent-finetune` worktree）演进，待下一代运行时契约冻结后再接入本仓库。
- 不要把训练流水线、LLaMA-Factory 源码、模型权重或训练侧依赖重新引入本仓库。两侧通过 HTTP API、版本化契约和轻量交付清单协作。
- 涉及上下游仓库的变更必须保持职责分离；本仓库不得依赖训练机上的源码、私有数据或本地绝对路径才能运行。

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
- 凡读取或导出结构化 CSV（标注表、评分输入、实验账本等），必须实现 **Schema 校验**（表头非空且无重复、行宽一致、必需列与合法取值检查）与 **计数/集合不变量校验**（非空行数、主键唯一、与预期 ID 集合对齐），遇到缺列、错位或未识别取值必须 fail-closed 报错，严禁静默兜底为有效正例或默认值。

## 验证与产物

- Agent Runtime 修改应优先运行对应测试；涉及状态机、采样、解析或推理链路时，重点覆盖 `tests/test_iterative_agent.py`、`tests/test_sampling*.py`、`tests/test_parser.py` 和 `tests/test_inference.py`。
- 项目级验证命令为 `python3 -m pytest tests -q`；前端修改运行 `cd web && npm run build`；交付 bundle 修改运行 `python3 scripts/validate_delivery_bundle.py --mvllm-root ../mVllm_2`。
- 动态帧、临时 clip、LLM trace 和其他运行时产物写入 `data/08_runtime/`，不得提交。不要提交视频、模型权重、checkpoint、密钥、token 或大型生成结果。

<!-- git-pr-workflow:start -->
## Git 协作与 PR 审查流

- **主线与远程**：本仓库长期主线分支为 `main`，PR 审查远程为 `github`（PR 流程基线 tag：`pr-workflow-baseline-20261120`）。
- **开工前置动作**：每个独立任务开始前先运行 `bash scripts/sync_and_clean.sh`（自动拉取最新 `github/main`、同步主工作区并安全清理已合并的干净 `work/*` 残留），再显式从最新远端主线创建独立 worktree 与任务分支：
  ```bash
  git worktree add --no-track ../TensileAgent-<线名> -b work/<线名> github/main
  ```
  不要在主工作区切换分支，同一 worktree 内不得并行两个写入者。
- **交付与 PR**：在任务分支完成开发并跑通本项目准入检查（`python3 -m pytest tests -q`；涉及前端运行 `cd web && npm run build`）后，推送 `work/<线名>` 到 `github` 并创建指向 `main` 的 PR（`gh pr create --base main`，严格按 `.github/PULL_REQUEST_TEMPLATE.md` 填写）。
- **权限红线**：允许 Agent 推送自己的 `work/*` 任务分支并创建/更新 PR；**严禁** push `main`，**严禁**自行合并 PR，也不要本地直接合并回主线。
- **合并与自动清理**：PR 统一由用户在远端审查并通过所有 Required Status Checks 后以 **Create a merge commit** 合并（保留“任务信封”合并节点）；远程 `work/*` 分支在 PR 合并后自动删除。对已通过 Merge Commit 合入 `github/main` 且工作树完全干净的本地 `work/*` 分支及对应 worktree，已永久预授权 Agent 通过 `bash scripts/sync_and_clean.sh` 自动清理，无需逐次请示；未合并、含未提交改动或用途不明的分支严禁删除。
<!-- git-pr-workflow:end -->

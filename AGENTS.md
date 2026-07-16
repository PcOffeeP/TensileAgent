# 仓库规范

## 项目结构与模块组织

- `agent/`：Agent/模型接口契约实现、schema、prompt、采样、推理客户端和 `IterativeAgent` 状态机。
- `data/01_videos/`：原始视频，本地数据，命名为 `video_XXXX.mp4`，不要提交。
- `data/02_annotations/`：CSV 标注文件、`video_mapping.csv` 和 `all_videos_tag.csv`。
- `data/05_splits/`：新 interval 方案生成的 `fold_*_{train,val}.json`、`test.json` 和划分决策记录。
- `data/03_subvideos/`、`data/04_frames/`、`data/06_merged/`、`data/07_metadata/`：新 interval pipeline 的本地生成产物，不提交。
- `pipeline/scripts/`：数据集准备、子视频生成、训练样本构建脚本；从仓库根目录运行。 （仅训练机）
- `pipeline/config/`、`pipeline/templates/`：旧问题池和 JSON 模板。 （仅训练机）
- `finetune/`：项目专属 LLaMA-Factory 配置、数据集注册表和验证脚本。 （仅训练机）
- `LlamaFactory/`：LLaMA-Factory git submodule，不在 `finetune/` 中维护框架源码副本。 （仅训练机）
- `docs/PROJECT_PLAN.md`、`docs/IMPLEMENTATIONS/`：项目级计划与分步骤实施方案。
- `docs/archive/`：已过期的原设计资料和带日期的历史设计记录，不作为当前实现依据。
- `assets/`：领域参考文档和项目原始说明材料；运行时配置仍保存在对应代码或配置目录。
- `tests/`：项目级 pytest 测试。

> **注意**：本仓库仅包含 Agent 决策系统。
> `pipeline/`、`finetune/`、`LlamaFactory/`、`models/`、`scripts/` 等目录属于训练流水线，
> 位于独立的 [mVllm_2](../mVllm_2) 仓库中。本仓库通过 HTTP API 调用训练侧部署的推理服务。

## 设计驱动工作流

本项目通过维护项目设计和必要的分步骤实施方案指导 Agent 工作，但不设置强制二次审批门：

1. `docs/PROJECT_PLAN.md` 是项目级设计依据。目标、范围、公共契约、核心流程或验收标准变化时，应同步修订项目计划；当用户已经明确授权实施时，Agent 可以在同一任务中更新文档并继续施工，无需等待额外的“批准”回复。
2. `docs/IMPLEMENTATIONS/*.md` 仅在任务复杂、需要跨 Agent 交接或用户明确要求时创建，不再作为每个核心步骤的强制前置条件。
3. 开始修改代码或数据流程前，Agent 必须读取 `AGENTS.md` 和当前项目计划，并把变更限制在用户授权与项目边界内。
4. 实施中发现设计不可行、与仓库事实冲突或需要扩大用户授权范围时，应停止施工并说明问题；低影响的实现细节调整可以同步记录后继续，不要求单独走审批流程。
5. `docs/archive/` 只提供历史背景。其内容与当前项目计划或当前实现冲突时，以后两者为准，不能从归档文档恢复旧契约。

## 构建、测试与开发命令

初始化依赖：

```bash
git submodule update --init --recursive
cd LlamaFactory/  # （仅训练机）
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

新 interval 数据流程：

```bash
python3 pipeline/scripts/dataset_manager.py  # （仅训练机）
python3 pipeline/scripts/subvideo_builder.py  # （仅训练机）
python3 pipeline/scripts/training_sample_builder.py  # （仅训练机）
python3 scripts/validate_no_oob.py  # （仅训练机）
```

训练一个新 interval fold：

```bash
cd finetune/  # （仅训练机）
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml  # （仅训练机）
```

项目级验证：

```bash
python3 -m pytest tests -q
python3 scripts/validate_no_oob.py  # （仅训练机）
git diff --check
```

## 代码风格与命名约定

使用 Python 3.11。遵循 `LlamaFactory/pyproject.toml` 的基本风格：4 空格缩进、双引号、每行 119 字符，并在需要时使用 Google 风格 docstring。确保 `pipeline/scripts/`、`scripts/` 和 `finetune/validation/` 下脚本可从仓库根目录通过 `python3` 运行。 （仅训练机）保留 `video_XXXX.mp4`、`fold_N_train`、`fold_N_val` 的命名方式。

## 标签治理与数据口径

CSV 标注是权威来源。发生冲突时，不覆盖 CSV 原字段；通过 `has_fracture_canonical`、`location_canonical`、`is_label_conflict`、`label_governance_reason` 等派生字段表达训练口径，并在下游样本构造中使用 canonical 字段。

旧直接预测方案由另一个项目维护。本项目不恢复或维护其训练数据、配置和运行流程，只导入它根据约定测试清单生成的版本化预测产物。跨项目比较必须校验测试清单哈希、预测完整性、方法版本和配置，不能让旧方案代码重新进入当前项目的训练或运行依赖。

## 测试规范

项目级测试从仓库根目录运行 `python3 -m pytest tests -q`。真实生成产物不存在时，部分 `data/07_metadata/` 或 `data/06_merged/` 相关测试应 `skip`，不能依赖本机 ignored 产物才能通过。修改 pipeline 后，优先运行相关单测、一个小样本脚本链路和 `scripts/validate_no_oob.py`。 （仅训练机） 修改 Agent runtime 后，重点覆盖 `tests/test_iterative_agent.py`、`tests/test_sampling*.py`、`tests/test_parser.py`、`tests/test_inference.py`。

## Agent Runtime 规范

Agent 使用 Native Function Calling，不引入 MCP。微调模型的 `fracture_between` 只允许严格相邻的 `[i,i+1]`，不接受边界哨兵。`IterativeAgent` 的候选区间更新、五个重叠区间完整覆盖、至少两次局部断裂确认、冲突与非法输出处理，以及 `fracture` / `no_fracture` / `unrecognized` 最终状态必须由代码层兜底，不能完全信任 LLM 参数。每轮 `sample_and_infer` 后必须把更新后的候选区间和历史追加到下一轮 user context。Agent 推理阶段动态生成的帧和临时 clip 写入 `data/08_runtime/`，不要提交。

## 提交与拉取请求规范

近期提交摘要使用英文或中文：`docs: ...`、`feat: ...`、`refactor(...): ...`、`Update ...` 或 `第二批提交：...`。保持提交聚焦任务。PR 应说明目的、变更路径、已运行的命令和硬件假设。验证可视化结果请附上截图或图表。

## Git 工作流与并行实现

以 `main` 作为稳定集成分支。如需并行工作，优先使用 `git worktree`，而非在一个目录中切换分支。长期分支通过 `git fetch` 加 `git rebase main` 同步，或在需要保守协作时使用 `git merge main`。

历史上的并行分支职责如下，后续拆分任务时仍按这个边界组织：

- contract 分支：schema、adapter、prompt/message 格式、评估 fixture 和配置。
- finetuning pipeline 分支：训练数据、pipeline 脚本、LLaMA-Factory 配置、验证和 checkpoint。
- agent runtime 分支：工具调用、执行循环、状态、记忆/上下文、调度和接口。

## 安全与配置提示

不要提交 checkpoint、模型权重、密钥、token、大型输出文件或本地视频数据。`.gitignore` 已覆盖 `data/01_videos/`、`data/03_subvideos/`、`data/04_frames/`、`data/06_merged/`、`data/07_metadata/`、`data/08_runtime/` 和验证结果目录。PR 中记录本地模型路径、GPU 相关 YAML 设置和 `DOWNSAMPLE_MODE`。标注时间保持为 `XXX.XXs` 格式，不要嵌入空格。

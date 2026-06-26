# 开发工作流与运行环境

## 硬件与开发环境

| 角色 | 机器 | 规格 | Shell | Python 管理 |
|------|------|------|-------|-------------|
| 开发机 | MacBook Air M4 | 24GB 内存 | fish | uv |
| 训练机 | 远程服务器 | — | — | pip（LLaMA-Factory 依赖） |

- Python 版本：3.11（仓库根目录 `.python-version`）。
- 开发机使用 **uv** 管理项目虚拟环境与依赖，参见 `pyproject.toml`。
- 训练机不需要 uv，直接在 `LlamaFactory/` 子模块下用 pip 安装框架训练依赖即可。

## 双机协同工作流

```text
┌──────────────────┐     git push      ┌──────────────────┐
│   开发机 (Mac)    │ ──────────────>  │   训练机 (远程)   │
│                   │                  │                   │
│  · 代码开发        │                  │  · 训练           │
│  · 数据 pipeline   │                  │  · 推理验证       │
│  · Agent 调试      │                  │  · 结果导出       │
│  · 单元测试        │                  │                   │
│                   │ <──────────────  │                   │
│                   │   git pull       │                   │
└──────────────────┘                  └──────────────────┘
```

### 原则

1. **所有代码变更在开发机（Mac）上完成**，包括数据 pipeline 脚本、Agent runtime、配置、测试等。
2. 开发机上完成的变更通过 `git push` 推送到远程仓库。
3. 训练机通过 `git pull` 拉取最新代码后，**仅用于训练与推理验证**，不直接在训练机上修改代码。
4. 训练机上的训练产物（checkpoint、验证结果）如有需要，通过 Git 忽略规则排除（已在 `.gitignore` 中配置 `LlamaFactory/saves/` 和 `finetune/validation/results/`），不走 Git 同步；如需归档，由训练机单独导出。

### 典型迭代循环

```bash
# 开发机 (Mac)
# 1. 修改代码
# 2. 本地运行测试
python3 -m pytest tests/ -q

# 3. 提交并推送
git add -A
git commit -m "feat: ..."
git push

# 训练机
# 4. 拉取最新代码
git pull
git submodule update --init --recursive

# 5. 执行训练
cd finetune/
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml

# 6. 推理验证
python3 finetune/validation/run_inference.py \
  --task joint \
  --fold 0 \
  --model-dir ../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged \
  --output finetune/validation/results/joint_fold0.jsonl
```

## LLaMA-Factory Submodule 管理

LLaMA-Factory 以 Git submodule 方式引入，位于 `LlamaFactory/` 目录。

### 配置

- 远程仓库使用用户的 **Gitee fork**。
- `.gitmodules` 配置：
  ```
  [submodule "LlamaFactory"]
      path = LlamaFactory
      url = git@gitee.com:l-i-u-yang/LlamaFactory.git
  ```

### 初始化

```bash
# 首次克隆后初始化 submodule
git submodule update --init --recursive
```

### 日常同步

- LLaMA-Factory 框架本身的更新由用户在 Gitee fork 中管理。
- 项目本身**不修改 LLaMA-Factory 框架源码**；所有训练配置、数据集注册和验证脚本都在项目目录 `finetune/` 下，与 `LlamaFactory/` 保持分离。
- 如果需要在训练机更新 LLaMA-Factory 版本，在训练机上执行：
  ```bash
  cd LlamaFactory
  git fetch origin
  git checkout <目标版本或分支>
  cd ..
  git add LlamaFactory
  git commit -m "chore: update LLaMA-Factory submodule"
  git push
  ```

> 注意：submodule 指针变更需要在所有机器（开发机 + 训练机）上执行 `git submodule update --init --recursive` 才能同步。

## 本地数据与产物管理

**开发机（Mac）本地生成的数据产物**（子视频、帧图缓存、训练 JSON、元数据等）不提交到 Git：

| 目录 | 内容 | .gitignore |
|------|------|------------|
| `data/01_videos/` | 原始视频 | 否（仅忽略 `.mp4` 等扩展名） |
| `data/03_subvideos/` | 子视频 | 是 |
| `data/04_frames/` | 帧图缓存 | 是 |
| `data/06_merged/` | 训练 JSON | 是 |
| `data/07_metadata/` | 元数据 JSON | 是 |
| `data/08_runtime/` | Agent 运行时帧/clip | 是 |
| `LlamaFactory/saves/` | 训练 checkpoint | 是 |
| `finetune/validation/results/` | 验证结果 | 是 |

**训练机**上的训练产物同理，由 `.gitignore` 排除，不走 Git 同步。

## 环境配置注意事项

- 开发机使用 **uv**：`pip install -e .` 和 `pip install -e ".[dev]"` 通过 uv 执行。
- 训练机使用原生 pip：在 `LlamaFactory/` 下安装框架依赖（`pip install -e ".[metrics]"` 和 `pip install -r requirements/minicpm-v.txt`）。
- 模型权重统一放在 `models/` 目录下（由 `models/README.md` 说明），不提交。
- Agent 远程后端配置（`LLM_API_KEY`）在训练机上按需设置，不在代码仓库中保留密钥。

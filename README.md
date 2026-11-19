# TensileAgent

## 当前版本边界

TensileAgent 已完成 `tensile-vlm/v4.1` 中间模型的 Agent 集成和一次冻结的 110 视频运行。
当前中间交付以整体链路为硬门，已经通过；模型质量仍单独记录和优化，不能用链路通过
替代效果验收。当前唯一允许的处置级别为 `intermediate_development_model`：训练机发布
了一个 V4.1 推理模型，服务只监听 loopback，本机通过 SSH tunnel 联调。具体权重、
fold、seed 和发布目录由 mVllm_2 的机器清单管理，不作为 Agent 使用说明。

| 层 | 当前状态 |
| --- | --- |
| Agent Runner、状态机、HTTP 客户端 | V4.1 中间集成已完成 |
| 当前视觉服务 | V4.1 中间推理服务，只监听 loopback，通过 SSH tunnel 联调，非生产 |
| V4.1 consumer artifact | 已冻结：`agent/contracts/tensile_vlm_v4_1.json` |
| 中间交付链路门 | 通过 |
| 性能策略 | 不阻断当前中间交付；新模型在 mVllm_2 中独立实验和晋级 |
| 全量 110 条性能 | 断裂准确率/联合成功率 40.91%，断裂召回 31.11%，未断裂召回 85.00% |
| Held-out 21 条性能 | 断裂准确率/联合成功率 42.86%，断裂召回 35.29%，未断裂召回 75.00% |
| Stage B | 历史质量门失败 |
| Stage C | 延期，未执行 full-data 训练 |
| Stage D | 历史质量门失败 |
| Stage G | 110/110 运行完成、链路完整；历史质量门失败 |
| V2 | 保留为回滚对象，不代表已完成同源最终比较 |

不得将当前状态宣称为 final、full-data、independent-test-passed 或生产通过。
机器可验的当前交付入口见 [delivery](delivery/README.md)，人工状态入口见跨仓 handoff。
Stage G 聚合结果和 scorer 覆盖限制见
[中间汇总](docs/results/v4_1_stage_g_intermediate/README.md)。

## 项目简介

TensileAgent 是材料拉伸断裂视频 Agent 分析系统。本仓库只维护 Agent 端：接收用户的
自然语言问题，通过 HTTP 调用外部 MiniCPM-V 4.5 视觉推理服务，迭代定位断裂区间，并
投影为用户需要的回答。当前运行时使用 `tensile-vlm/v4.1` 视觉契约，`tensile-vlm/v2`
仅作为显式回滚协议保留，同一任务中不会自动降级。

## 仓库结构

```
TensileAgent/
├── agent/                          ← 核心 Agent 系统
│   ├── iterative_agent.py          ← 迭代状态机（INITIAL/COVERAGE/LOCALIZING/NARROWING/VERIFYING/NO_FRACTURE/TERMINATED）
│   ├── llm.py                      ← 决策模型双后端（远程 DashScope / 本地 Ollama）
│   ├── inference.py                 ← 视觉推理 HTTP 客户端与契约校验
│   ├── runner.py                    ← 共享执行内核（CLI + Web API 共用）
│   ├── schema.py                    ← Pydantic 契约与公共结果模型
│   ├── prompts.py                   ← 系统提示词模板
│   ├── sampling.py                  ← 视频裁剪与帧→时间戳映射
│   ├── parser.py                    ← 通用模型输出解析器
│   ├── v4_1_parser.py              ← V4.1 四字段解析器
│   ├── v4_1_evidence.py            ← V4.1 事件边界单调收缩
│   ├── contract.py                  ← 版本化视觉契约加载与 hash 校验
│   ├── contracts/                   ← 冻结契约 artifact（v2 / v4.1）
│   ├── scoring/                     ← 评分规范（v4.1 验收、v2 对比）
│   ├── web_api.py                  ← FastAPI Web 后端（SSE 事件流）
│   ├── run.py                       ← CLI 入口
│   ├── setup.py                     ← 交互式配置向导
│   ├── config_util.py              ← 配置/模型列表/持久化工具
│   ├── config.yaml                 ← 默认运行时配置（V4.1）
│   ├── config.v4_1.pre_acceptance.yaml ← V4.1 预验收配置
│   ├── config.v2.comparison.yaml   ← V2 对比配置
│   ├── http_vlm_stub.py            ← 本地协议 Stub
│   ├── doctor.py                    ← 预检/健康检查
│   ├── acceptance_*.py             ← V4.1 验收批处理与校验
│   ├── v2_comparison_*.py            ← V2 回滚对比流水线
│   ├── strategy_ab*.py             ← 本地模型策略 A/B
│   └── llm_trace.py                ← 脱敏传输记录工具
├── web/                             ← React 19 + TypeScript 前端
│   ├── src/
│   │   ├── App.tsx                 ← 根组件
│   │   ├── api.ts                  ← API 通信层
│   │   └── components/             ← 上传、配置、任务详情、历史、诊断、模型传输回放等
│   ├── package.json
│   └── vite.config.ts
├── scripts/                         ← 批量运行、评分、交付 bundle 脚本
│   ├── run_v4_1_acceptance_batch.py
│   ├── score_v4_1_acceptance.py
│   ├── generate_delivery_bundle.py
│   ├── validate_delivery_bundle.py
│   ├── run_local_model_ab.py
│   └── ...
├── delivery/                        ← 单一交付中心（bundle、历史、回滚）
├── deployment/ollama/              ← Ollama Modelfile
├── tests/                           ← pytest 测试
├── docs/                            ← 设计文档与运行手册
│   ├── PROJECT_PLAN.md
│   ├── VISUAL_INFERENCE_SERVICE.md
│   ├── V4_1_PRE_ACCEPTANCE_RUNBOOK.md
│   └── LOCAL_MODEL_ACCEPTANCE.md
├── data/01_videos/                 ← 原始视频（本地数据，不提交）
├── data/08_runtime/                ← 运行时产物（gitignored）
├── pyproject.toml
├── uv.lock
├── AGENTS.md                       ← 仓库规范与 Agent 工作约定
└── README.md
```

## 当前 V4.1 架构概览

### 核心思路

V4.1 仍保持“迭代收敛”核心：LLM 只选择下一个 `sample_and_infer` 区间，真正的边界
更新、冲突处理、终止判断由 `IterativeAgent` 强制执行。视觉模型单轮返回固定四字段
`{clip_state, fracture_mechanism, fracture_site, special_case}`，其中只有 `clip_state`
提供搜索方向，其余字段只在最终投影时汇总。

```
用户输入视频
      │
      ▼
┌──────────────────────────────────────────────────────────────────┐
│                    TensileAgent 决策层                           │
│         (Qwen3.5-9B 本地 / Qwen3-8B 对照 / qwen3.7-max 远程)     │
│                                                                  │
│  第 1 轮 ──── sample_and_infer([0, duration], task_mode="analyze")  │
│  第 2 轮 ──── 根据 clip_state 收缩/转移候选区间                    │
│  第 3 轮 ──── 继续缩小直到事件边界 ≤ 容差                          │
│  ...        （最多 10 轮，逐步收敛）                              │
│                                                                  │
│  每轮 Agent 决定：                                                │
│  ① 裁剪哪段视频                                                  │
│  ② 是否继续缩小、扩展或覆盖检查                                  │
│  ③ 是否已有足够证据可以下结论                                  │
└──────────────────────┬───────────────────────────────────────────┘
                       │ 每轮：裁剪 → 编码 → HTTP 调用
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    MiniCPM-V 4.5 视觉层                          │
│                    (HTTP API 调用远程推理服务)                   │
│                                                                  │
│  输入：视频片段（最多 8 帧）+ 固定 Prompt                         │
│  输出：{clip_state, fracture_mechanism, fracture_site, special_case}│
│                                                                  │
│  clip_state 语义：                                               │
│  • 未断裂 / 临界未断裂  →  向后搜索（later）                      │
│  • 已断裂            →  向前搜索（earlier）                       │
│  • 发生断裂          →  当前区间为权威交集（within）              │
│  • 无法判断          →  不提供方向，触发复查/异常处理             │
└──────────────────────────────────────────────────────────────────┘
```

### 状态机流程

```
                    ┌──────────┐
                    │  INITIAL  │  首次全量扫描，获取视频元数据
                    └────┬─────┘
                         │
                    ┌────▼─────┐
              ┌─────│ COVERAGE  │─────┐  5 个固定区间覆盖全视频
              │     └────┬─────┘     │  （阴性时才能进入）
              │          │          │
              │     ┌────▼─────┐     │
              │     │ LOCALIZING│     │  阳性后寻找可用范围
              │     └────┬─────┘     │
              │          │          │
              │     ┌────▼─────┐     │
              │     │ NARROWING │     │  多轮迭代收缩事件边界
              │     └────┬─────┘     │
              │          │          │
              │     ┌────▼─────┐     │
              │     │ VERIFYING │     │  边界 ≤ tolerance，准备终止
              │     └────┬─────┘     │
              │          │          │
              │     ┌────▼─────┐     │
              └────►│ TERMINATED│◄────┘  冲突、异常或基础设施失败也强制终止
                    └────┬─────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
       fracture     no_fracture    unrecognized
```

### 一轮迭代的完整链路

```
TensileAgent 只决定 sample_range；视觉 Prompt 由程序固定
      │
      ▼
  ① 视频裁剪 ──  ffmpeg 裁剪出 [start, end] 片段，建立帧映射表
      │             {临时帧 → 原始帧 → 时间戳}
      ▼
  ② 编码传输 ──  片段编码为 data:video/mp4;base64，POST 到推理服务
      │             （OpenAI-compatible 接口，含 deployment manifest 预检）
      ▼
  ③ 模型推理 ──  MiniCPM-V 返回四字段 JSON
      │             {clip_state, fracture_mechanism, fracture_site, special_case}
      ▼
  ④ 事件边界更新 ──  依据 clip_state 单调收缩可信事件区间
      │             （V41EventBounds 负责冲突检测与拒绝）
      ▼
  ⑤ 状态更新 ──  更新候选区间、覆盖计数、冲突计数，进入下一轮
```

### 关键设计要点

| 方面 | 说明 |
|------|------|
| **分层解耦** | Agent 和视觉模型通过 HTTP API + 版本化四字段 JSON 契约交互；用户原话和 Planner Prompt 不进入视觉调用 |
| **方向语义** | V4.1 用 `clip_state` 给出搜索方向，事件边界由程序单调收缩，模型不再直接输出时间索引 |
| **收敛保证** | `发生断裂` 或 `已断裂`/`未断裂` 的合法方向证据持续缩小事件边界；冲突或漏检会扩展采样范围 |
| **终止条件** | 事件边界 ≤ tolerance（fracture）、5 个覆盖区间全通过（no_fracture）、超 10 轮 / 冲突 / 非法输出 / 基础设施失败（unrecognized） |
| **错误隔离** | 基础设施故障连续 2 次或 deployment drift → 强制终止，不伪装为 unrecognized |
| **证据可追溯** | 每轮绑定 clip hash、request_id、帧表、时间戳；按需视觉依据只引用这些 trace |

### 系统组件

| 组件 | 技术 | 说明 |
|------|------|------|
| **决策模型** | Qwen3.5-9B（本地默认）/ Qwen3-8B（本地对照）/ qwen3.7-max（远程可选） | TensileAgent 运行时的推理后端 |
| **视觉模型** | MiniCPM-V 4.5（HTTP API 调用） | 分析视频片段，输出 V4.1 四字段 |
| **状态机** | `IterativeAgent` | 管理候选区间、事件边界、覆盖、终止条件 |
| **V4.1 边界/解析** | `v4_1_evidence.py` / `v4_1_parser.py` | 方向语义处理、四字段严格校验 |
| **契约** | `contract.py` + 冻结 JSON | V2/V4.1 版本化契约加载与 hash 校验 |
| **视频采样** | ffmpeg 裁剪 + PTS 帧映射 | 将帧索引映射为真实时间戳 |
| **LLM 双后端** | `RemoteAPIClient` / `LocalClient` | 远程 DashScope 或本地 Ollama，统一接口 |
| **Web API** | FastAPI + SSE | 任务队列、实时事件流、历史持久化 |
| **前端** | React 19 + Vite 8 + Tailwind CSS 4 | 深色控制台，支持模型传输回放 |
| **验收/评分** | `acceptance_*.py` / `scripts/score_v4_1_acceptance.py` | 冻结批量验收与 Stage G 评分 |

### 当前三种最终状态

| 状态 | 条件 |
|------|------|
| `fracture` | ≥2 轮可用断裂证据，事件边界收敛到 ≤ tolerance，无未解决冲突 |
| `no_fracture` | 全部 5 个覆盖区间完成，无阳性证据 |
| `unrecognized` | 7 种原因（max_rounds、conflicting_results、invalid_model_output、insufficient_confidence、incomplete_coverage、video_anomaly/not_clamped、budget_exhausted） |

## 历史可替换视觉后端 MVP（V2）

V2 视觉服务必须提供 `GET /v1/tensile/contract`，并在每轮响应中返回与任务预检完全一致的
deployment manifest；旧 v1 服务会被拒绝。V2 单轮输出为
`{has_fracture, fracture_between, type, location}`，Agent 形成 `tensile-agent/result/v2`。

V2 仍可通过显式 `--contract-version tensile-vlm/v2` 或 `agent/config.v2.comparison.yaml`
回滚，但**不允许同一任务中从 V4.1 自动降级到 V2**。当前全量模型服务地址、独立 API Key
配置、预检和 Key 轮换流程见 [视觉推理服务接入说明](docs/VISUAL_INFERENCE_SERVICE.md)。

本地联调可以启动协议 Stub（默认 V2，可显式指定 V4.1）：

```bash
# V2 Stub
python3 -m agent.http_vlm_stub --scenario fracture --port 8000

# V4.1 Stub（与默认 config.yaml 联调）
python3 -m agent.http_vlm_stub --scenario fracture --port 18002 --contract-version tensile-vlm/v4.1

python3 -m agent.doctor
```

Stub 的 `--scenario` 支持 `fracture`、`partial`、`no-fracture`、`not-clamped`、
`unknown`、`invalid`、`drift`、`transport-failure` 等。公共结果统一为
`tensile-agent/result/v2` 或 `tensile-agent/result/v4.1`；Evidence 始终标记为
`experimental`，confidence 数值在校准前保持 `null`。

## 快速开始

### 安装

```bash
# 创建虚拟环境并安装依赖
uv venv --python 3.11
source .venv/bin/activate  # fish: source .venv/bin/activate.fish  |  Windows: .venv\Scripts\activate
uv sync

# 含开发依赖
uv sync --dev

# 视频处理工具（跑真实分析必需；仅链路验证 / Mock 模式可跳过）
brew install ffmpeg
```

### 准备本地决策模型（默认）

模型由 Ollama 管理，不要把权重下载到仓库。首次使用执行：

```bash
brew install ollama

# 终端 1：手动启动，不注册登录常驻服务
OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve

# 终端 2：拉取并创建固定 16K 上下文别名
ollama pull qwen3.5:9b
ollama pull qwen3:8b
ollama create tensile-qwen35:9b -f deployment/ollama/Modelfile.qwen35
ollama create tensile-qwen3:8b -f deployment/ollama/Modelfile.qwen3
```

Web 默认使用 `tensile-qwen35:9b`。配置页可以手动切换到 `tensile-qwen3:8b` 或远程
`qwen3.7-max`；本地失败时不会自动调用远程服务。

运行固定 Agent-only A/B（每个模型 20 个场景，5 个关键场景各 3 次）：

```bash
uv run python scripts/run_local_model_ab.py
```

报告和逐轮脱敏 trace 保存到 `data/08_runtime/local_model_ab/`。若要删除本地权重，先停止任务，再执行：

```bash
ollama rm tensile-qwen35:9b tensile-qwen3:8b qwen3.5:9b qwen3:8b
```

### 配置远程模型（可选）

只有手动选择远程后端时才需要百炼 API Key。CLI 配置方式：

```bash
# 交互式配置向导
python3 -m agent.setup

# 或静默配置
python3 -m agent.setup --api-key sk-xxx --model qwen3.7-max
```

API Key 存储在 `agent/.env` 中（已 gitignored），不会提交到仓库；模型选择保存在同样已忽略的 `agent/config.local.yaml`。

### 准备视觉推理服务（可选；跑真实分析必需）

真实分析需要 V4.1 MiniCPM-V 推理服务。该服务不在本仓库，部署请参考兄弟仓库
**[mVllm_2](../mVllm_2)**。当前 V4.1 中间服务只监听 loopback，本机通过 SSH tunnel
联调；默认配置指向 `127.0.0.1:18002`，预验收配置指向 `127.0.0.1:8002`，具体端口以
实际 deployment manifest 和 tunnel 为准。

仅链路验证或 Mock 模式无需启动该服务：

```bash
# 启动 V4.1 协议 Stub（默认配置会连接 127.0.0.1:18002）
python3 -m agent.http_vlm_stub --scenario fracture --port 18002 --contract-version tensile-vlm/v4.1

# 预检
python3 -m agent.doctor
```

### 运行分析

```bash
# CLI 单视频分析（默认使用 V4.1 配置）
python3 -m agent.run --video data/01_videos/video_0001.mp4

# 使用自然语言指定所需回答；仅请求原因时会额外运行固定 Evidence Prompt
python3 -m agent.run --video data/01_videos/video_0001.mp4 \
  --question "这个试样什么时候断的？为什么这样判断？"

# CLI 批量分析
python3 -m agent.run --videos-dir data/01_videos
python3 -m agent.run --input-list data/01_videos/list.txt

# 显式选择 V4.1 或 V2
python3 -m agent.run --video xxx.mp4 --contract-version tensile-vlm/v4.1
python3 -m agent.run --video xxx.mp4 --contract-version tensile-vlm/v2

# Mock 模式（无需真实推理服务）
python3 -m agent.run --video xxx.mp4 --mock
```

### 启动 Web 工作台

```bash
# 1. 安装前端依赖并构建（首次或前端代码有更新时）
cd web
npm install
npm run build
cd ..

# 2. 确保另一个终端已运行 ollama serve，然后启动后端
python3 -m agent.web_api

# 启动参数可临时覆盖当前进程，不修改本机持久配置
python3 -m agent.web_api --agent-backend local --agent-model tensile-qwen35:9b

# 3. 浏览器打开 http://127.0.0.1:8765
#    配置页可查看 Ollama 状态、已安装模型和当前模型 digest
#    任务详情的“模型传输”区域可回放逐轮请求、工具调用和响应
```

开发模式（前后端分离，支持热更新）：

```bash
# 终端 1: 启动后端
cd web && npm install && npm run build && cd ..
python3 -m agent.web_api

# 终端 2: 启动前端开发服务器
cd web && npm run dev
# 前端访问 http://localhost:5173，API 代理到 :8765
```

## 批量运行与验收

冻结的 V4.1 批量验收需要使用 acceptance manifest 与 Stage G 一次性授权：

```bash
# 预验收单视频
python3 -m agent.doctor --config agent/config.v4_1.pre_acceptance.yaml
python3 -m agent.run \
  --video /absolute/path/video_0001.mp4 \
  --config agent/config.v4_1.pre_acceptance.yaml \
  --contract-version tensile-vlm/v4.1

# 可恢复批处理
python3 scripts/run_v4_1_acceptance_batch.py \
  --manifest /absolute/path/agent_acceptance_manifest.json \
  --stage-g-authorization /absolute/path/stage_g_authorization.json \
  --input-list all_110 \
  --output-dir data/08_runtime/v4_1_acceptance

# Stage G 评分（开封后仅运行一次）
python3 scripts/score_v4_1_acceptance.py \
  --annotations /absolute/path/all_videos_tag.csv \
  --results-root data/08_runtime/v4_1_acceptance \
  --spec agent/scoring/v4_1_agent_acceptance_v1.json \
  --output data/08_runtime/v4_1_acceptance/accuracy_report.json
```

交付 bundle 的生成与验证见 [delivery/README.md](delivery/README.md)。

## CLI 参数

| 参数 | 说明 |
|------|------|
| `--video path` | 单视频分析 |
| `--videos-dir path` | 批量分析目录下所有 `.mp4` |
| `--input-list path` | 从文本文件读取视频路径列表 |
| `--mock` | Mock 模式 |
| `--agent-backend remote\|local` | 切换决策模型后端 |
| `--agent-model name` | 覆盖决策模型名称 |
| `--contract-version tensile-vlm/v4.1\|tensile-vlm/v2` | 固定本次任务的视觉契约版本 |
| `--question text` | 自然语言问题 |
| `--config path` | 配置文件路径（默认 `agent/config.yaml`） |
| `--output path` | 结果输出路径 |
| `--work-dir path` | 工作目录 |

### 模型切换示例

```bash
# 使用远程千问 Max（必须显式指定后端）
python3 -m agent.run --video xxx.mp4 --agent-backend remote --agent-model qwen3.7-max

# 切换到本地模型
python3 -m agent.run --video xxx.mp4 --agent-backend local

# 本地指定具体模型
python3 -m agent.run --video xxx.mp4 --agent-backend local --agent-model tensile-qwen3:8b
```

## 配置

主要配置集中在 `agent/config.yaml`：

```yaml
agent:
  backend: "local"               # 默认本地；远程必须手动选择
  temperature: 0.2
  tolerance_seconds: 1.0         # 断裂时间窗口
  max_rounds: 10                 # 最大决策轮次
  max_low_conf_rounds: 2         # 低置信连续轮数上限
  remote:
    provider: "dashscope"
    model: "qwen3.7-max"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  local:
    provider: "ollama"
    model: "tensile-qwen35:9b"
    base_url: "http://localhost:11434/v1"
    reasoning_effort: "none"

backend:                         # 微调模型推理服务
  api_url: "http://127.0.0.1:18002/v1"
  model: "tensile-vlm"
  contract_version: "tensile-vlm/v4.1"
  max_request_size: 536870912
```

预验收配置使用 `agent/config.v4_1.pre_acceptance.yaml`，其中 `agent.backend` 为
`deterministic`（`v4.1-interval-policy-v1` Planner），`backend.api_url` 指向
`127.0.0.1:8002`。V2 回滚请使用 `agent/config.v2.comparison.yaml` 或显式
`--contract-version tensile-vlm/v2`。

决策模型 Key 使用 `LLM_API_KEY`；视觉推理服务使用独立的 `INFERENCE_API_KEY`。
两者均可保存在被 Git 忽略的 `agent/.env`，不能混用或提交。Web 的持久选择写入同样被忽略的
`agent/config.local.yaml`；启动参数优先级最高但只影响当前进程。存在运行中或排队任务时禁止切换模型。

决策模型的脱敏传输记录保存在 `data/08_runtime/llm_traces/<task-id>/`，包含实际 messages、
tools、tool calls、usage 和耗时，不包含 API Key、Base64 或绝对路径。

## 测试

```bash
# 运行全部测试
pytest tests -q

# 特定模块
pytest tests/test_llm.py -v
pytest tests/test_inference.py -v
pytest tests/test_iterative_agent.py -v
pytest tests/test_schema.py -v
pytest tests/test_v4_1_contract_artifact.py -v
pytest tests/test_v4_1_runtime_contract.py -v
pytest tests/test_web_api.py -v
```

## 相关仓库

| 仓库 | 说明 |
|------|------|
| **[mVllm_2](../mVllm_2)** | V4.1 历史冻结/中间视觉服务与交付上游（`tensile-vlm/v4.1` 及回滚 `v2`） |
| **[TensileAgent-Finetune](../TensileAgent-Finetune)** | 新一代五类数据、微调与离线评测演进线（`mVllm_2` 的 `feat/tensileagent-finetune` worktree），尚未接入当前 V4.1 运行时 |

`mVllm_2/main` 当前作为冻结上游维护 `tensile-vlm/v4.1` 数据、训练、发布模型和中间推理服务；V2
数据与模型已在 archive 中冻结。新一代五类模型在 `TensileAgent-Finetune` 独立演进，待下一代运行时契约冻结后再接入本仓库。当前 V4.1 中间服务单轮返回
`clip_state`、`fracture_mechanism`、`fracture_site`、`special_case`，Agent 形成
`tensile-agent/result/v4.1`。V2 只作为历史回滚协议。

`临界未断裂` 的机制和位置属于 prospective 线索，必须由后续真实断裂证据确认。当前
服务和 Agent 已使用这套语义，但模型本身仍未通过任务质量门。

生产服务的 `deployment_manifest` 必须完整携带模型、adapter、base model、processor、
框架、配置、runtime、`contract_version` 和 `contract_hash`。Agent 在任务预检时冻结完整快照；
缺失、变化或不一致时拒绝使用该轮结果。

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11 + TypeScript |
| 决策模型 | Qwen3.5-9B（本地默认）/ Qwen3-8B（本地对照）/ qwen3.7-max（远程可选） |
| 视觉模型 | MiniCPM-V 4.5（HTTP API 调用） |
| Agent 框架 | Native Function Calling + Pydantic v2 契约 |
| 后端 | FastAPI + Uvicorn + SSE |
| 前端 | React 19 + Vite 8 + Tailwind CSS 4 + lucide-react |
| 测试 | pytest |
| 包管理 | uv |

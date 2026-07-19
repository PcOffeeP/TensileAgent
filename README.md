# TensileAgent

## 可替换视觉后端 MVP

运行时固定使用 `tensile-vlm/v2`。视觉服务必须提供
`GET /v1/tensile/contract`，并在每轮响应中返回与任务预检完全一致的
deployment manifest；旧 v1 服务会被拒绝。

本地联调可以启动协议 Stub：

```bash
python3 -m agent.http_vlm_stub --scenario fracture --port 8000
python3 -m agent.doctor
```

Stub 的 `--scenario` 还支持 `partial`、`no-fracture`、`not-clamped`、
`unknown`、`invalid`、`drift` 和 `transport-failure`。公共结果统一为
`tensile-agent/result/v2`；Evidence 始终标记为 `experimental`，confidence
数值在完成校准前保持 `null`。

材料拉伸断裂视频 Agent 分析系统。当前仓库只维护 Agent 端：通过 HTTP 调用外部视觉推理服务，并由 TensileAgent 迭代定位断裂区间。

## 仓库结构

```
TensileAgent/
├── agent/                  ← 核心 Agent 系统
│   ├── iterative_agent.py  ← TensileAgent 状态机（15+ 状态转换）
│   ├── llm.py              ← LLM 双后端（远程 DashScope / 本地 Ollama）
│   ├── inference.py        ← 推理客户端（HTTP 调用微调模型）
│   ├── runner.py           ← 共享执行内核（CLI + Web API 共用）
│   ├── schema.py           ← 三层 Pydantic 契约模型
│   ├── prompts.py          ← 提示词模板
│   ├── sampling.py         ← 视频裁剪与帧映射
│   ├── parser.py           ← 模型输出解析器
│   ├── web_api.py          ← FastAPI Web 后端（SSE 事件流）
│   ├── run.py              ← CLI 入口
│   ├── setup.py            ← 配置向导
│   ├── config_util.py      ← 配置工具（.env 读写、模型列表查询）
│   └── config.yaml         ← Agent 配置
├── web/                    ← React 19 + TypeScript 前端
│   └── src/
│       ├── App.tsx         ← 根组件（三视图切换）
│       ├── api.ts          ← API 通信层
│       └── components/     ← UI 组件（上传、配置、任务详情、导航）
├── tests/                  ← pytest 测试（25+ 文件）
├── docs/                   ← 设计文档
│   └── PROJECT_PLAN.md     ← Agent-only 项目计划 v14.0
├── data/08_runtime/        ← 运行时产物（gitignored）
├── pyproject.toml          ← Python 项目配置
├── .gitignore
└── README.md
```

## 架构概览

### 核心思路

TensileAgent 的核心是一个**两阶段迭代收敛**过程：

```
用户输入视频
      │
      ▼
┌──────────────────────────────────────────────────────────────────┐
│                    TensileAgent 决策层                           │
│                    (Qwen 系列 LLM)                               │
│                                                                  │
│  第 1 轮 ──── sample_and_infer([0, 60s], task_mode="analyze")    │
│  第 2 轮 ──── sample_and_infer([20s, 40s], task_mode="analyze")  │
│  第 3 轮 ──── sample_and_infer([28s, 32s], task_mode="analyze")  │
│  ...        （最多 10 轮，逐步收敛）                             │
│                                                                  │
│  每轮 TensileAgent 决定：                                        │
│  ① 裁剪哪段视频                                                  │
│  ② 是否继续缩小、扩展或覆盖检查                                  │
│  ③ 是否已经有足够证据可以下结论                                  │
└──────────────────────┬───────────────────────────────────────────┘
                       │ 每轮：裁剪视频片段 → 编码 → HTTP 调用
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    MiniCPM-V 4.5 视觉层                          │
│                    (HTTP API 调用远程推理服务)                   │
│                                                                  │
│  输入：视频片段（最多 8 帧）+ 文本提示                           │
│  输出：训练一致的严格四字段 JSON                                 │
│    { has_fracture, fracture_between, type, location }            │
│                                                                  │
│  将帧索引 [i, j] 映射为真实时间戳 [t0, t1]                       │
└──────────────────────────────────────────────────────────────────┘
```

### 状态机流程

TensileAgent 由一个有限状态机驱动，管理从开始到结论的完整生命周期：

```
                    ┌──────────┐
                    │  INITIAL  │  首次全量扫描，获取视频元数据
                    └────┬─────┘
                         │
                    ┌────▼─────┐
              ┌─────│ COVERAGE  │─────┐  5 个固定区间覆盖全视频
              │     └────┬─────┘     │
              │          │          │
              │     ┌────▼─────┐     │
              │     │ NARROWING │     │  │  多轮迭代：每轮根据上一轮
              │     └────┬─────┘     │  │  结果缩小候选区间
              │          │          │  │
              │          ▼          │
              │    [候选 ≤ 1s]      │         ┌──────────────┐
              │          │          │         │  NO_FRACTURE  │  ← 全视频无断裂
              │     ┌────▼─────┐    │         └──────────────┘
              │     │ VERIFYING │    │
              │     └────┬─────┘    │
              │          │          │
              └──────────┘          │
                         │          │
                    ┌────▼──────────▼──┐
                    │   TERMINATED     │
                    └──────────────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         fracture   no_fracture  unrecognized
```

### 一轮迭代的完整链路

TensileAgent 每轮调用 `sample_and_infer` 工具，内部依次执行：

```
TensileAgent 只决定要检查的区间 [start, end]；视觉 Prompt 由程序固定
      │
      ▼
  ① 视频裁剪 ──  ffmpeg 裁剪出 [start, end] 的连续片段
      │             同时建立帧映射表 {临时帧 → 原始帧 → 时间戳}
      ▼
  ② 编码传输 ──  片段编码为 data:video/mp4;base64
      │             POST 到推理服务（OpenAI-compatible 接口）
      ▼
  ③ 模型推理 ──  MiniCPM-V 4.5 分析视频，返回四字段 JSON
      │             例如：{has_fracture:true, fracture_between:[42,43], ...}
      ▼
  ④ 时间映射 ──  帧索引 [42,43] → 真实时间戳 [t0, t1]
      │
      ▼
  ⑤ 状态更新 ──  更新候选区间、轮次计数、置信度统计
      │
      ▼
  结果返回 TensileAgent，进入下一轮决策
```

### 关键设计要点

| 方面 | 说明 |
|------|------|
| **分层解耦** | Agent 和视觉模型通过 HTTP API + 版本化四字段 JSON 契约交互；用户原话和 Planner Prompt 不进入视觉调用 |
| **收敛保证** | 每次 fracture 结果会缩小候选区间；冲突或漏检会主动扩展区间 |
| **终止条件** | 候选窗口 ≤1s（fracture）、5 个覆盖全通过（no_fracture）、超 10 轮（unrecognized） |
| **错误隔离** | 基础设施故障连续 2 次 → 强制终止，不伪装为 unrecognized |

### 系统组件

| 组件 | 技术 | 说明 |
|------|------|------|
| **决策模型** | Qwen2.5-14b（远程）/ Qwen3.5:7b（本地） | TensileAgent 运行时的推理后端 |
| **视觉模型** | MiniCPM-V 4.5（3-fold LoRA SFT） | 分析视频片段，输出断裂判断 |
| **状态机** | IterativeAgent | 管理候选区间收敛、终止条件判断 |
| **契约** | Pydantic v2 严格校验 | 3 层校验：模型输出→工具结果→最终结果 |
| **视频采样** | ffmpeg 裁剪 + PTS 帧映射 | 将帧索引映射为真实时间戳 |
| **LLM 双后端** | RemoteAPIClient / LocalClient | 远程 DashScope 或本地 Ollama，统一接口 |
| **Web API** | FastAPI + SSE | 任务队列、实时事件流、历史持久化 |
| **前端** | React 19 + Vite + Tailwind CSS 4 | 深色三栏控制台 |

### 三种最终状态

| 状态 | 条件 |
|------|------|
| `fracture` | ≥2 轮断裂证据，交集窗口 ≤1s，类型/位置/置信度必填 |
| `no_fracture` | 全部 5 个覆盖区间完成，置信度 ≥ 阈值 |
| `unrecognized` | 7 种原因（max_rounds、conflicting_results、invalid_model_output 等） |

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

Web 默认使用 `tensile-qwen35:9b`。配置页可以手动切换到 `tensile-qwen3:8b` 或远程 `qwen3.7-max`；本地失败时不会自动调用远程服务。

运行固定 Agent-only A/B（每个模型 20 个场景，5 个关键场景各3次）：

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

真实分析需要 MiniCPM-V 4.5 推理服务（`http://localhost:8000/v1`），该服务不在本仓库，请参考兄弟仓库 **[mVllm_2](../mVllm_2)** 部署。

仅链路验证或 Mock 模式无需启动该服务（参见下方 `--mock` 用法）。

### 运行分析

```bash
# CLI 单视频分析
python3 -m agent.run --video data/01_videos/video_0001.mp4

# 使用自然语言指定所需回答；仅请求原因时会额外运行固定 Evidence Prompt
python3 -m agent.run --video data/01_videos/video_0001.mp4 \
  --question "这个试样什么时候断的？为什么这样判断？"

# CLI 批量分析
python3 -m agent.run --videos-dir data/01_videos

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

## CLI 参数

| 参数 | 说明 |
|------|------|
| `--video path` | 单视频分析 |
| `--videos-dir path` | 批量分析目录下所有 `.mp4` |
| `--input-list path` | 从文本文件读取视频路径列表 |
| `--mock` | Mock 模式 |
| `--agent-backend remote\|local` | 切换决策模型后端 |
| `--agent-model name` | 覆盖决策模型名称 |
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
  api_url: "http://localhost:8000/v1"
  model: "minicpmv4_5"
```

API Key 可通过 Web UI 或 `agent/setup.py` 写入 `agent/.env`。Web 的持久选择写入被 Git 忽略的 `agent/config.local.yaml`；启动参数优先级最高但只影响当前进程。存在运行中或排队任务时禁止切换模型。

决策模型的脱敏传输记录保存在 `data/08_runtime/llm_traces/<task-id>/`，包含实际 messages、tools、tool calls、usage 和耗时，不包含 API Key、Base64 或绝对路径。

## 测试

```bash
# 运行全部测试
pytest tests -q

# 特定模块
pytest tests/test_llm.py -v
pytest tests/test_inference.py -v
pytest tests/test_iterative_agent.py -v
pytest tests/test_schema.py -v
```

## 相关仓库

| 仓库 | 说明 |
|------|------|
| **[mVllm_2](../mVllm_2)** | MiniCPM-V 4.5 微调流水线（数据准备、训练、评估） |

`mVllm_2` 包含完整的数据流水线和训练配置，并维护 `tensile-vlm/v2` 权威契约。视觉模型单轮只返回四字段；TensileAgent 在多轮证据基础上形成 `tensile-agent/result/v2`，支持字段级 partial。confidence 未完成源视频隔离校准前只显示证据等级，数值保持 `null`。

生产服务的 `deployment_manifest` 必须完整携带模型、adapter、base model、processor、框架、配置、runtime、`contract_version` 和 `contract_hash`。Agent 在任务预检时冻结完整快照；缺失、变化或不一致时拒绝使用该轮结果。

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

# TensileAgent

材料拉伸断裂视频智能分析系统。核心采用「MiniCPM-V 4.5 微调模型 + Meta-Agent 迭代定位」两阶段方案。

## 仓库结构

```
TensileAgent/
├── agent/                  ← 核心 Agent 系统
│   ├── iterative_agent.py  ← Meta-Agent 状态机（15+ 状态转换）
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
│   ├── PROJECT_PLAN.md     ← 项目计划 v9.0
│   ├── PROJECT_WORKFLOW.md ← 双机协同工作流
│   └── IMPLEMENTATIONS/    ← 实施方案
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
│                    Meta-Agent 决策层                              │
│                    (Qwen 系列 LLM)                               │
│                                                                  │
│  第 1 轮 ──── sample_and_infer([0, 60s], "检查是否断裂")          │
│  第 2 轮 ──── sample_and_infer([20s, 40s], "检查这个区间")       │
│  第 3 轮 ──── sample_and_infer([28s, 32s], "精确定位")          │
│  ...        （最多 10 轮，逐步收敛）                              │
│                                                                  │
│  每轮 Meta-Agent 决定：                                           │
│  ① 裁剪哪段视频                                                 │
│  ② 用什么措辞提问                                               │
│  ③ 是否已经有足够证据可以下结论                                  │
└──────────────────────┬───────────────────────────────────────────┘
                       │ 每轮：裁剪视频片段 → 编码 → HTTP 调用
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    MiniCPM-V 4.5 视觉层                           │
│                    (HTTP API 调用远程推理服务)                     │
│                                                                  │
│  输入：视频片段（最多 8 帧）+ 文本提示                            │
│  输出：五字段 JSON                                               │
│    { has_fracture, fracture_between, type, location, confidence }│
│                                                                  │
│  将帧索引 [i, j] 映射为真实时间戳 [t0, t1]                       │
└──────────────────────────────────────────────────────────────────┘
```

### 状态机流程

Meta-Agent 由一个有限状态机驱动，管理从开始到结论的完整生命周期：

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

Meta-Agent 每轮调用 `sample_and_infer` 工具，内部依次执行：

```
Meta-Agent 决定要检查的区间 [start, end] 和提示词
      │
      ▼
  ① 视频裁剪 ──  ffmpeg 裁剪出 [start, end] 的连续片段
      │             同时建立帧映射表 {临时帧 → 原始帧 → 时间戳}
      ▼
  ② 编码传输 ──  片段编码为 data:video/mp4;base64
      │             POST 到推理服务（OpenAI-compatible 接口）
      ▼
  ③ 模型推理 ──  MiniCPM-V 4.5 分析视频，返回五字段 JSON
      │             例如：{has_fracture:true, fracture_between:[42,43], ...}
      ▼
  ④ 时间映射 ──  帧索引 [42,43] → 真实时间戳 [t0, t1]
      │
      ▼
  ⑤ 状态更新 ──  更新候选区间、轮次计数、置信度统计
      │
      ▼
  结果返回 Meta-Agent，进入下一轮决策
```

### 关键设计要点

| 方面 | 说明 |
|------|------|
| **分层解耦** | Agent 和视觉模型只通过 HTTP API + 五字段 JSON 契约交互，可独立开发部署 |
| **收敛保证** | 每次 fracture 结果会缩小候选区间；冲突或漏检会主动扩展区间 |
| **终止条件** | 候选窗口 ≤1s（fracture）、5 个覆盖全通过（no_fracture）、超 10 轮（unrecognized） |
| **错误隔离** | 基础设施故障连续 2 次 → 强制终止，不伪装为 unrecognized |

### 系统组件

| 组件 | 技术 | 说明 |
|------|------|------|
| **决策模型** | Qwen2.5-14b（远程）/ Qwen3.5:7b（本地） | Meta-Agent 运行时的推理后端 |
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
# 安装核心依赖
pip install -e .

# 安装开发依赖（pytest、ruff）
pip install -e ".[dev]"
```

### 配置远程模型

首次使用需要配置远程决策模型的 API Key：

```bash
# 交互式配置向导
python3 -m agent.setup

# 或静默配置
python3 -m agent.setup --api-key sk-xxx --model qwen-max
```

配置信息存储在 `agent/.env` 中（已 gitignored），不会提交到仓库。

### 运行分析

```bash
# CLI 单视频分析
python3 -m agent.run --video data/01_videos/video_0001.mp4

# CLI 批量分析
python3 -m agent.run --videos-dir data/01_videos

# Mock 模式（无需真实推理服务）
python3 -m agent.run --video xxx.mp4 --mock
```

### 启动 Web 工作台

```bash
# 启动后端 API 服务
python3 -m agent.web_api
# 访问 http://127.0.0.1:8765

# 开发模式（前后端分离）：
# 终端 1: python3 -m agent.web_api
# 终端 2: cd web && npm run dev
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
# 使用远程千问 Max
python3 -m agent.run --video xxx.mp4 --agent-model qwen-max

# 切换到本地模型
python3 -m agent.run --video xxx.mp4 --agent-backend local

# 本地指定具体模型
python3 -m agent.run --video xxx.mp4 --agent-backend local --agent-model qwen3.5:7b
```

## 配置

主要配置集中在 `agent/config.yaml`：

```yaml
agent:
  backend: "remote"              # remote 或 local
  tolerance_seconds: 1.0         # 断裂时间窗口
  max_rounds: 10                 # 最大决策轮次
  remote:
    provider: "dashscope"
    model: "qwen2.5-14b-instruct"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  local:
    provider: "ollama"
    model: "qwen3.5:7b"
    base_url: "http://localhost:11434/v1"

backend:                         # 微调模型推理服务
  api_url: "http://localhost:8000/v1"
  model: "minicpmv4_5"
```

API Key 通过 `agent/setup.py` 写入 `agent/.env`，不直接存储在配置文件中。

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

`mVllm_2` 包含完整的数据流水线和训练配置。TensileAgent 通过 HTTP API 调用 `mVllm_2` 部署的推理服务，两者通过严格的五字段 JSON 契约解耦。

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11 + TypeScript |
| 决策模型 | Qwen2.5-14b（远程）/ Qwen3.5:7b（本地） |
| 视觉模型 | MiniCPM-V 4.5（HTTP API 调用） |
| Agent 框架 | Native Function Calling + Pydantic v2 契约 |
| 后端 | FastAPI + Uvicorn + SSE |
| 前端 | React 19 + Vite 8 + Tailwind CSS 4 + lucide-react |
| 测试 | pytest |
| 包管理 | uv / pip |

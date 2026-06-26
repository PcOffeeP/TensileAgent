# TensileAgent

材料拉伸断裂视频智能分析系统。核心采用「MiniCPM-V 4.5 微调模型 + Meta-Agent 迭代定位」两阶段方案。

## 仓库结构

```
TensileAgent/
├── agent/           ← 核心 Agent 状态机、LLM 双后端、CLI/API 入口
├── web/             ← React 19 + FastAPI Web 工作台
├── tests/           ← pytest 测试
├── docs/            ← 设计文档和实施方案
└── pyproject.toml   ← Python 项目配置
```

## 快速开始

### 安装

```bash
pip install -e .
pip install -e ".[dev]"   # 开发依赖（pytest、ruff）
```

### 配置远程模型

首次使用需要配置百炼 API Key：

```bash
# 交互式配置
python3 -m agent.setup

# 或静默配置
python3 -m agent.setup --api-key sk-xxx --model qwen-max
```

### 运行分析

```bash
# CLI 单视频
python3 -m agent.run --video xxx.mp4

# CLI 批量
python3 -m agent.run --videos-dir /path/to/videos

# Web 工作台
python3 -m agent.web_api
```

### 切换模型

```bash
# 切换远程模型
python3 -m agent.run --video xxx.mp4 --agent-model qwen-max

# 切换本地模型
python3 -m agent.run --video xxx.mp4 --agent-backend local
```

## 架构

TensileAgent 是一个两层系统：

1. **MiniCPM-V 4.5（微调模型）** — 分析视频片段，输出五字段 JSON
2. **Meta-Agent（Qwen 系列）** — 多轮工具调用，逐步收敛断裂区间

两者通过 HTTP API 和严格的契约解耦。训练流水线在独立的 [mVllm_2](AgentPlayground/active-projects/mVllm_2) 仓库中。

## 依赖

| 包 | 用途 |
|---|---|
| openai | LLM 双后端客户端 |
| pydantic v2 | 三层契约校验 |
| fastapi + uvicorn | Web API 服务 |
| opencv-python | 视频处理 |
| pyyaml | 配置加载 |
| sse-starlette | 实时事件推送 |
| React 19 + TypeScript | 前端 UI |

# 视觉推理服务接入说明

TensileAgent 当前连接训练机上的全量微调模型服务。模型协议固定为
`tensile-vlm/v2`，实际部署参数如下：

| 项目 | 当前值 |
| --- | --- |
| 训练机 | `100.70.83.68` |
| Agent Base URL | `http://100.70.83.68:8001/v1` |
| 模型名 | `tensile-vlm` |
| 契约预检 | `GET /v1/tensile/contract` |
| 分析与 Evidence | `POST /v1/chat/completions` |
| 契约版本 | `tensile-vlm/v2` |

协议路径和契约是程序固定的；主机、端口和 API Key 属于部署配置。当前地址已经写入
`agent/config.yaml`。如果训练机地址或端口变化，应修改 `backend.api_url`，不要修改
客户端内部的 `/tensile/contract` 或 `/chat/completions` 路径。

## API Key

推理服务使用独立的 `INFERENCE_API_KEY`，不能与决策模型的 `LLM_API_KEY` 混用。
真实 Key 只保存在以下两个被 Git 忽略的位置：

- 训练机：`/home/liuyang/文档/mVllm_2/finetune/run_logs/tensile_vlm_service.env`
- TensileAgent 当前机器：`agent/.env`

初始化本机配置：

```bash
cp agent/.env.example agent/.env
```

然后只在 `agent/.env` 中填写：

```dotenv
INFERENCE_API_KEY=与训练机相同的值
```

禁止把真实 Key 写入 `agent/config.yaml`、README、测试、日志或 Git 提交。环境变量
`INFERENCE_API_KEY` 的优先级高于 `agent/.env`。

## 配置优先级

推理服务地址和模型名按以下顺序选择：

1. 有效配置中的 `backend.api_url` 和 `backend.model`；
2. `INFERENCE_BASE_URL` 和 `INFERENCE_MODEL`；
3. 本地开发默认值。

标准项目配置已经指向训练机：

```yaml
backend:
  api_url: http://100.70.83.68:8001/v1
  model: tensile-vlm
```

被 Git 忽略的 `agent/config.local.yaml` 可以覆盖上述地址，适合临时切换到本地 Stub。

## 连通性检查

确保训练机服务已经启动，并在 TensileAgent 仓库根目录执行：

```bash
python3 -m agent.doctor
```

`checks.visual_service` 应满足：

- `ok: true`
- `auth_configured: true`
- URL 为 `http://100.70.83.68:8001/v1/tensile/contract`
- contract version/hash 与本仓 artifact 一致

直接运行 Agent 时不需要额外拼接接口路径：

```bash
python3 -m agent.run --video /path/to/video.mp4
```

任务启动时客户端会先预检并锁定 deployment manifest；后续响应发生模型、adapter、
processor、runtime 或契约漂移时会 fail closed。

## Key 轮换

1. 在训练机停止 `tensile-vlm` 服务；
2. 更新训练机 `finetune/run_logs/tensile_vlm_service.env`；
3. 使用新 Key 重启并通过预检；
4. 更新本机 `agent/.env` 的 `INFERENCE_API_KEY`；
5. 运行 `python3 -m agent.doctor`；
6. 确认成功后再提交视频任务。

只更新其中一端会得到 HTTP `401`。不要为了绕过鉴权而把服务改成无 Key 模式。

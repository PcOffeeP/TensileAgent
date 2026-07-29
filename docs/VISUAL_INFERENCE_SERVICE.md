# V4.1 视觉推理服务接入说明

> 当前已经部署一个符合 `tensile-vlm/v4.1` 的中间推理服务。Agent 只依赖服务契约、
> 能力和性能边界；具体模型名称、fold、seed 与权重目录由 mVllm_2 管理。

## 当前身份

| 项目 | 当前值 |
| --- | --- |
| 训练机 | `100.70.83.68` |
| 训练机监听 | `127.0.0.1:8002` |
| Agent 模型名 | `tensile-vlm` |
| 契约 | `tensile-vlm/v4.1` |
| 契约预检 | `GET /v1/tensile/contract` |
| 分析 | `POST /v1/chat/completions` |
| 访问策略 | 同机 loopback 或 SSH tunnel |

权威 Agent 配置：

`agent/config.v4_1.pre_acceptance.yaml`

```yaml
backend:
  api_url: http://127.0.0.1:8002/v1
  contract_version: tensile-vlm/v4.1
  model: tensile-vlm
```

`agent/config.yaml` 保留 V2 回滚与旧默认行为，不得在同一任务中从 V4.1 静默降级。

## API Key

视觉服务使用独立的 `INFERENCE_API_KEY`，不能与决策模型的 `LLM_API_KEY` 混用。

TensileAgent 可以通过环境变量或 Git 忽略的 `agent/.env` 提供：

```dotenv
INFERENCE_API_KEY=与训练机 API_KEY 相同的值
```

真实 Key 不得写入 YAML、README、测试、日志或 Git。

## 同训练机检查

```bash
cd '/home/liuyang/文档/TensileAgent-acceptance'

export INFERENCE_API_KEY='由部署方提供的服务密钥'

/home/liuyang/miniconda3/envs/agent/bin/python \
  -m agent.doctor \
  --config agent/config.v4_1.pre_acceptance.yaml
```

`checks.visual_service` 必须包含：

- `ok: true`；
- `auth_configured: true`；
- `contract_version: tensile-vlm/v4.1`；
- 与 consumer artifact 一致的 contract hash。

## 跨机器 SSH tunnel

训练机服务只监听 loopback。开发机需要建立 tunnel：

```bash
ssh -N -L 18002:127.0.0.1:8002 100.70.83.68
```

然后使用本地覆盖配置：

```yaml
backend:
  api_url: http://127.0.0.1:18002/v1
  contract_version: tensile-vlm/v4.1
  model: tensile-vlm
```

不要为了省略 tunnel 而把训练机 8002 暴露为生产接口。

## 运行 Agent

```bash
python3 -m agent.run \
  --video /absolute/path/video.mp4 \
  --config agent/config.v4_1.pre_acceptance.yaml \
  --contract-version tensile-vlm/v4.1
```

任务启动时会先冻结完整 deployment identity。后续响应中的模型、adapter、processor、
runtime、contract version 或 contract hash 发生变化时，客户端必须 fail closed。

## 当前结果语义

V4.1 单轮视觉输出：

- `clip_state`；
- `fracture_mechanism`；
- `fracture_site`；
- `special_case`。

Agent 公共结果 schema：

`tensile-agent/result/v4.1`

`临界未断裂`中的机制和位置只是 prospective 线索，需要后续真实断裂证据确认。服务
返回合法 JSON、Agent 成功结束或 HTTP 200 都不能单独证明模型效果达标。

## 当前性能快照

冻结 Stage G 结果：

| 范围 | 样本 | 断裂准确率 / joint | 断裂召回 | 未断裂召回 |
| --- | ---: | ---: | ---: | ---: |
| 全量 | 110 | 40.91% | 31.11% | 85.00% |
| Held-out | 21 | 42.86% | 35.29% | 75.00% |
| Development | 89 | 40.45% | 30.14% | 87.50% |

该结果显示服务更容易识别未断裂样本，对断裂正例仍有明显漏检。冻结 scorer 没有正确
映射部分中文权威列，因此时间命中率、机制宏 F1、位置宏 F1 和特殊样例准确率当前不可用。
不可用不能解释为通过。

## Key 轮换

1. 停止训练机 V4.1 服务；
2. 更新权限 `0600` 的 `service.env`；
3. 使用新 Key 重启并完成 service smoke；
4. 更新 Agent 的 `INFERENCE_API_KEY`；
5. 运行 V4.1 doctor；
6. 成功后再提交视频任务。

只更新一端会得到 HTTP 401。不得通过关闭鉴权规避配置问题。

## V2 历史回滚

V2 使用 `agent/config.yaml` 和 `tensile-vlm/v2` consumer artifact。回滚必须在新任务中
显式完成，并与 V4.1 服务使用不同的运行身份；不能把 V2 响应解释为 V4.1，也不能在
V4.1 任务失败后自动回退。

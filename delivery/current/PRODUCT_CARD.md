# TensileAgent V4.1 中间开发交付卡

## 用途

该交付点用于受控开发、演示准备和本机到训练机的远程 GPU 联调。当前已经部署一个
符合 `tensile-vlm/v4.1` 的中间推理服务。具体模型身份和权重来源由 mVllm_2 的机器
manifest 管理，不作为 TensileAgent 的使用概念。

## 已验证范围

- 110/110 视频完成运行，0 个运行时失败；
- Agent 到视觉服务的 deployment、证据、clip 和时间映射链路完整；
- Agent Python 测试和 Web 构建通过；
- 模型与服务轻量 manifest 已绑定到交付 bundle。

## 当前交付门

中间交付只检查以下硬门：

- 模型文件、完整哈希和 manifest 身份一致；
- 视觉服务 contract 与 deployment identity 一致；
- Agent 与 Web 测试通过；
- SSH tunnel、doctor 和真实 development 视频 GPU 调用通过；
- tunnel 或身份错误时 fail closed，不自动混用 V2；
- 两仓双机 Git 和轻量 bundle 可复核。

这些链路硬门已通过。

## 性能快照（非门禁）

准确率、召回率和联合成功率记录在
`docs/results/v4_1_stage_g_intermediate/performance_snapshot.json`：

- 全量 110 条：断裂准确率/联合成功率 40.91%，断裂召回 31.11%，未断裂召回 85.00%；
- held-out 21 条：断裂准确率/联合成功率 42.86%，断裂召回 35.29%，未断裂召回 75.00%；
- development 89 条：断裂准确率/联合成功率 40.45%，断裂召回 30.14%，未断裂召回 87.50%。

这些指标不阻断当前中间交付，但清楚表明断裂正例漏检仍是主要问题。

冻结 scorer 未覆盖部分中文权威列名，因此时间、机制、位置和特殊样例指标不可用；
不可用既不解释为通过，也不作为本次中间交付失败。

## 历史状态与未完成

- Stage B、Stage D、Stage G 质量门失败；
- Stage C full-data 训练延期；
- 未完成新的独立 held-out 验收，也没有生产授权。

## 禁止表述

不得称为 final、full-data、independent-test-passed、`v4.1-core-validated`、
production-ready 或 production-approved。

## 部署边界

模型权重和具体身份只由训练机受管，视觉服务只监听训练机
`127.0.0.1:8002`。本机通过 `127.0.0.1:18002` SSH tunnel 访问；contract、
deployment identity 或 transport 失败时 Agent 应 fail closed，不自动降级到 V2。

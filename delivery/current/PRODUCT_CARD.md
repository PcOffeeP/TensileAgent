# TensileAgent V4.1 中间开发交付卡

## 用途

该交付点用于受控开发、演示准备和本机到训练机的远程 GPU 联调。模型为
coverage-first seed3407 merged BF16，Agent 使用 `tensile-vlm/v4.1` 契约。

## 已验证范围

- 110/110 视频完成运行，0 个运行时失败；
- Agent 到视觉服务的 deployment、证据、clip 和时间映射链路完整；
- Agent Python 测试和 Web 构建通过；
- 模型与服务轻量 manifest 已绑定到交付 bundle。

## 未通过与未完成

- Stage B、Stage D、Stage G 质量门失败；
- Stage C full-data 训练延期；
- Stage G 冻结 scorer 未覆盖部分中文权威列名，若干字段分母为 0；
- 未完成新的独立 held-out 验收，也没有生产授权。

## 禁止表述

不得称为 final、full-data、independent-test-passed、`v4.1-core-validated`、
production-ready 或 production-approved。

## 部署边界

模型权重只保留在训练机受管目录，视觉服务只监听训练机
`127.0.0.1:8002`。本机通过 `127.0.0.1:18002` SSH tunnel 访问；contract、
deployment identity 或 transport 失败时 Agent 应 fail closed，不自动降级到 V2。

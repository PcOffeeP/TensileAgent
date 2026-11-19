# TensileAgent 单一交付中心

`delivery/current/bundle.json` 是当前中间交付的机器入口，仅对应 `mVllm_2` 的
`v4.1` 冻结中间交付，不涵盖 `TensileAgent-Finetune` 的新一代五类模型。它绑定
Agent、模型、视觉服务、链路验收和性能快照的轻量组件，并明确能力边界。

`delivery_gate` 只检查模型/服务身份、产物完整性、测试、真实远程调用、fail-closed
和双机同步。`performance_snapshot` 仅记录当前测量值，不比较阈值、不阻断交付、
不触发优化或重训。

验证：

```bash
python3 scripts/validate_delivery_bundle.py \
  --mvllm-root ../mVllm_2
```

生成器只从本仓和指定的 mVllm_2 工作区读取轻量清单，不读取权重、视频、密钥或
逐样本结果：

```bash
python3 scripts/generate_delivery_bundle.py \
  --mvllm-root ../mVllm_2
```

当前 bundle 不是生产发布物。权重继续由训练机托管，服务只监听 loopback，并通过
SSH tunnel 提供本地联调。

# TensileAgent 单一交付中心

`delivery/current/bundle.json` 是当前中间交付的机器入口。它绑定 Agent、模型、
视觉服务和聚合验收报告的轻量组件快照，并明确能力边界。

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


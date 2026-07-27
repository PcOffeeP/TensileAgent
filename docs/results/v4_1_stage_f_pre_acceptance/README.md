# V4.1 Stage F pre-acceptance

Stage F 已将 TensileAgent 按任务显式迁移到 `tensile-vlm/v4.1`，但仍处于用户批准的
中间模型集成路线。原 Stage B 质量门与 LOSO 失败事实不变；本结果不授权重训、
正式别名或生产切换，也没有读取 held-out/sealed 语义标签。

冻结身份：

- Agent runtime commit:
  `50d0a9d4b463bca3db8a0a5837be6de1ee820fe4`
- Agent acceptance ID: `agent-acceptance-8a9ef687d7c7`
- Agent acceptance manifest SHA256:
  `6397cd3ee8e16dbba369fcbbb6683e2cd110cfdb07ba9db6006d8266e571129c`
- Stage B intermediate acceptance: `stage-b-intermediate-8e1fdb09f8e6`
- V4.1 runtime contract hash:
  `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`
- 服务模型身份: `v4.1-intermediate-stage-b-intermediate-8e1fdb09f8e6`

验收内容：

- V4.1 四字段 parser、三级 site、special-case 和公共
  `tensile-agent/result/v4.1` 投影；
- V4.1 搜索方向、Agent 自有时间区间、证据聚合和部署漂移 fail-closed；
- 显式 V2 回滚，无任务内协议自动降级；
- Doctor、HTTP stub、CLI、Web API 和 Web 展示；
- acceptance 专用确定性 Planner，不引入新模型权重或外部凭据；
- 身份绑定、成功不可覆盖的可恢复 batch runner；
- `all_110/heldout_21` 缺少一次性 Stage G authorization 时在首次 VLM 调用前
  fail closed；
- 固定 taxonomy、分母、阈值和合成金样例的版本化 scorer；
- 110 条和 21 条输入清单只冻结视频 ID/路径/hash，未读取语义标签。

验证结果：

- 本机完整 Python 测试：464 passed；
- 训练机独立 acceptance 工作区完整 Python 测试：464 passed；
- Web TypeScript/Vite build：通过；
- Doctor：V4.1 contract、hash、服务、确定性 Planner、ffmpeg/ffprobe 全通过；
- development-only 真实视频完整 Agent smoke：6 轮、`no_fracture`，公共 schema、
  contract/deployment identity、实际帧与诊断链完整；
- smoke JSONL SHA256:
  `9419584f79eb65b87bd58cd22260005611c5499f856af7e6720891b5ddc030f0`；
- diagnostics summary SHA256:
  `82e0dcb05f141de64d542e1d8deca79303b46d365d2a169cb4704e37deb2e4ab`。

训练机不可变运行时 manifest：

`/home/liuyang/文档/TensileAgent-acceptance/data/08_runtime/v4_1_acceptance_manifests/agent-acceptance-8a9ef687d7c7/agent_acceptance_manifest.json`

下一阶段只能使用上述 manifest 执行 Stage G。21 条 held-out 仍只允许一次语义开封；
Stage G 启动前不得修改 Agent、服务、配置、问题、scorer、输入清单或阈值。

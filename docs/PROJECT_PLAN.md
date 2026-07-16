# 材料拉伸断裂识别 Agent 项目计划

> 状态：已批准
>
> 实施状态（2026-07-16）：本机 MVP 与本地决策模型接入代码已完成；Fold 0、视觉反事实、真实端到端、confidence 校准和正式 test 仍需产生可追溯结果后验收。
> 版本：13.0

## 项目目标

TensileAgent 面向项目研究人员、演示人员和本地评测使用者，接受用户对拉伸试验视频的自然语言问题，识别用户真正关心的分析字段，并通过固定、版本化的生产 Prompt 调用外部 MiniCPM 视觉推理服务。系统内部完成多轮采样、局部帧到原视频时间的映射、证据聚合和置信度校准，最终只向用户展示其问题所需的信息，同时保留完整、可追踪、可回放的分析记录。

项目优先保证视觉调用不受用户措辞污染、训练与推理契约一致、失败显式、结论可核验和跨仓版本可追踪。当前版本不追求在线流式视频、工业实时告警或多事件识别。

## 需求与范围

本仓库包含自然语言意图识别、Agent 执行循环、Native Function Calling、视频裁剪与帧映射、视觉服务 HTTP 客户端、多轮证据记录、结论聚合、置信度校准接口、CLI、Web API 和本地工作台。用户可以询问是否断裂、断裂时间、类型、位置、置信度、视觉依据或完整分析；系统必须以用户问题为准投影回答，不能因用户只问二元问题而把异常、冲突或基础设施失败简化为“未断裂”。

MiniCPM 单轮主分析保持训练一致的四字段输出：`has_fracture`、当前 clip 实际采样帧中的局部 `fracture_between`、`type` 和 `location`。模型不直接输出 `confidence`。生产运行不从训练使用的多种 User Prompt 中随机抽取，也不允许 Planner 或用户覆盖视觉 Prompt；用户原话、Agent 历史和候选结论不得进入 MiniCPM 主分析请求。

Agent 最终业务结论包含 `has_fracture`、原视频 `time_range`、`type`、`location`、分项 `confidence` 和按需 `visual_evidence`。局部 `fracture_between` 只保存在对应轮次证据中，必须绑定 clip、实际帧表和映射元数据，不能直接充当最终原视频区间。`confidence` 至少区分决策、定位、分类和整体可靠度；未完成按源视频隔离的校准前不得伪装成概率。`visual_evidence` 默认内部可追踪、按需面向用户展示；当前基线通过第二次固定视觉调用在同一批实际输入帧上生成语义摘要，不允许 Meta-Agent 根据四字段凭空编写视觉现象。

训练数据治理、MiniCPM 微调、checkpoint、模型权重和视觉服务部署仍由独立 mVllm_2 仓库负责。本仓库只固定并校验其导出的 Prompt/schema/model/processor/generation 契约 artifact。在线流式分析、远程多用户服务、数据库、分布式队列、在线标注和每视频多个断裂事件不纳入当前范围。

## 技术方案

系统采用“自然语言意图层—确定性 Agent 策略—固定视觉调用—证据聚合—回答投影”架构。意图层把用户问题解析为受 schema 约束的请求字段、是否需要 evidence、是否需要 confidence、语言和歧义状态；无法识别、缺少视频或互相矛盾时先澄清，不启动视觉推理。Agent 可以执行完整内部分析，但公开响应只投影用户请求字段，并通过 `answered`、`unrecognized`、`failed` 区分正常回答、证据不足和运行失败。

Meta-Agent 决策模型默认通过本机 Ollama 使用固定 16K 上下文的 Qwen3.5-9B，Qwen3-8B 作为本地对照，qwen3.7-max 仅作为用户手动启用的远程后端。本地后端不可用、模型缺失或工具调用非法时 fail closed，不自动把上下文发送到远程服务。CLI 启动参数、本机持久配置和仓库默认配置按明确优先级解析；每个任务固定记录实际后端、模型、digest 和 reasoning 设置。

所有决策模型调用统一保存脱敏 transport trace，记录实际 messages、tools、tool calls、响应、usage、耗时和错误。API Key、Base64、临时路径和视频载荷不得进入 trace；reasoning 默认关闭，只有用户显式启用时才记录服务实际返回的 reasoning 字段。Web 工作台允许在无运行中或排队任务时手动切换本地/远程后端，并提供逐轮传输回放和 JSON 导出。

视觉 Prompt 由程序维护的版本化 registry 构造。主分析使用唯一四字段生产候选 Prompt；按需 evidence 使用独立固定 Prompt，查看与主调用相同的 clip 和实际采样帧，不接收主调用标签，避免确认偏差。两类调用均采用确定性生成配置，并记录 Prompt、schema、模型、processor、generation 和 calibration 版本或 hash。mVllm_2 是跨仓视觉契约 artifact 的权威来源，TensileAgent 在启动和请求时校验固定版本，不匹配时 fail closed。

Agent 的 Planner 只选择合法工具、采样区间和受控任务模式，不能传入任意视觉 Prompt、写入证据或生成公共结论。Executor 校验工具参数、视频边界、预算和外部响应；Evidence Store 只采信字段、帧表和时间映射均合法的事实；Verifier 强制至少两轮一致断裂证据、断裂时间交集与容差、五个重叠区间阴性覆盖、异常复查、冲突处理和最大预算。单次高置信全局阴性不得直接结束。

置信度由程序依据多轮一致性、覆盖完整度、区间交集、解析与映射成功、异常/冲突状态等特征产生，并在独立 calibration split 上校准。视觉模型自报分数不参与终止。用户要求视觉依据时，公开摘要必须引用可回放的 round、clip、帧和原视频时间；内部 Prompt、密钥、Base64、临时绝对路径和不必要的服务 metadata 不对外暴露。

## 实施规划

1. 在 mVllm_2 冻结四字段生产候选 Prompt 和跨仓契约 artifact，建立每个样本覆盖全部候选 Prompt 的配对评测，不再用样本哈希分配不同问法来选择生产 Prompt。
2. 在 TensileAgent 建立自然语言意图、四字段单轮结果、多轮证据、Agent 聚合结论和回答投影的分层契约，并封闭自由视觉 Prompt 入口。
3. 修正局部帧索引到原视频时间的聚合语义，统一 evidence 引用、阴性覆盖、冲突处理和最终 Verifier 出口。
4. 增加按需 evidence 视觉调用和分项 confidence 的特征采集、校准接口及公开展示策略。
5. 接入本地优先、远程可选的决策模型后端，固定任务级模型快照并建立脱敏传输审计。
6. 在 Fold 0 开发源视频上完成固定 Prompt、视觉反事实和端到端 Agent 验收；只有当前四字段基线不达标时，才由 mVllm_2 进入 evidence-first 或可空局部字段的重训设计。
7. 冻结模型、Prompt、schema、processor、generation 和 calibration 版本后，仅在独立 21 个正式 test 源视频上执行一次最终验收。

## 验收标准

1. “这个视频断了吗”“什么时候断的”“是什么类型、在哪里”“为什么”“你确定吗”和完整分析等中英文、口语、错别字输入都能解析为受控意图；无关、模糊、缺视频、矛盾和 Prompt 注入请求会澄清或拒绝，用户原话不会进入 MiniCPM 请求。
2. MiniCPM 主调用只接受程序生成的固定四字段 Prompt，输出、局部索引和服务端实际帧表可严格校验；相同模型、clip、Prompt 和生成配置重跑结果可复现。
3. 每个局部 `fracture_between` 都绑定来源轮次、clip 和帧表，并能映射为原视频 `time_range`；不同轮次相同局部索引不会被误认为同一帧。
4. 最终 `fracture` 至少由两轮可用断裂证据和非空时间交集支持；最终 `no_fracture` 必须完成五区间覆盖；异常、未夹紧、冲突、非法输出和基础设施失败不会收敛为错误的确定结论。
5. 用户只看到其请求字段和必要的不确定性。Evidence 摘要仅在按需视觉调用成功时展示，且每个声明都能追溯到帧和时间引用；未生成或失败时显式标记不可用。
6. 分项 confidence 在按源视频隔离的数据上校准并记录方法版本，报告 Brier score、ECE、可靠性曲线和 coverage-risk；校准器或契约版本不匹配时不输出已校准概率。
7. Fold 0 固定 Prompt 候选达到 JSON/schema 合法率至少 98%、断裂 source-macro recall 至少 85%，且不存在某个断裂源视频全部漏检；所有任务指标按源视频汇总并包含 type/location、时间命中和 joint success。
8. 跨仓 artifact 能自动检测 Prompt、schema、枚举、模型、processor 或 generation 漂移；不一致时拒绝语义结果。CLI、Web API 和 Web 工作台使用同一 Runner 与公开响应契约。
9. Agent-only 单元测试、契约测试、自然语言投影测试、反事实记录测试、前端构建和 `git diff --check` 通过；真实 GPU 推理和最终 test 验收在训练机器执行并保存完整 manifest。

## 风险与待确认事项

- [非阻塞] 当前四字段模型可能仍因同时承担检测、定位和分类而压缩正例边界；若固定 Prompt 基线达不到验收门槛，再进入重训，不在 Agent 侧用自由 Prompt 掩盖模型问题。
- [非阻塞] 第二次 evidence 调用可能产生事后合理化；必须通过断裂前截断、遮挡、无关帧替换和时序打乱反事实验证后才能作为公开视觉依据。
- [已解决] MiniCPM 主输出、Web DTO 和 Agent 公共结果已迁移到四字段视觉契约与分项 confidence；历史标量只在兼容入口被明确丢弃，不会冒充已校准概率。

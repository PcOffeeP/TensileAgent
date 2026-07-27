# 材料拉伸断裂识别 Agent 项目计划

> 状态：已批准
>
> 实施状态（2026-07-27）：V4.1 中间模型、Agent 集成和一次冻结的 110 视频运行已完成；
> 链路完整但 Stage B、Stage D、Stage G 质量门均失败，Stage C 延期。当前仅允许
> `intermediate_development_model` 处置，通过 loopback 服务与 SSH tunnel 联调；
> 不构成 final、full-data、independent-test-passed 或生产批准。
> 版本：17.0

## 项目目标

TensileAgent 面向项目研究人员、演示人员和本地评测使用者，接受用户对拉伸试验视频的自然语言问题，识别用户真正关心的分析字段，并通过固定、版本化的生产 Prompt 调用外部 MiniCPM 视觉推理服务。系统内部完成多轮采样、局部帧到原视频时间的映射、证据聚合和置信度校准，最终只向用户展示其问题所需的信息，同时保留完整、可追踪、可回放的分析记录。

项目优先保证视觉调用不受用户措辞污染、训练与推理契约一致、失败显式、结论可核验和跨仓版本可追踪。当前版本不追求在线流式视频、工业实时告警或多事件识别。

## 下一代视觉契约冻结边界

新的跨仓目标契约为 `tensile-vlm/v4.1`。单 clip 输出固定为 `clip_state`、
`fracture_mechanism`、`fracture_site`、`special_case`；其中只有 `clip_state`
向 Agent 提供搜索方向，其余字段只用于最终模式和断裂位置汇总。`fracture_site` 将 v3 中重复的
`root_break + location` 合并为互斥三级：`inside_gauge`（标距内，正常位置）、
`outside_gauge_non_root`（标距外非齐根，不理想）和 `grip_root`（夹具根部齐根，严重负面）。
严重程度由 Agent 确定性投影，不由视觉模型主观评价。`未断裂`指向更晚时间，
`已断裂`指向更早时间，`发生断裂`要求在当前区间继续收缩，`无法判断`不提供方向性证据。
边界、覆盖、收缩、预算、冲突和终止仍必须由确定性代码兜底。

`临界未断裂`表示尚未断裂但当前采样帧已出现明显韧性断裂临界征兆，搜索方向仍指向更晚区间。
该状态携带的机制和位置属于 `prospective` 预测线索，不能单独形成最终断裂类型、位置或已断裂
结论；必须由后续 `发生断裂` 或 `已断裂` 证据确认。普通 `未断裂` 的附加字段仍必须为 null。

阶段 A 的设计、artifact、Prompt 和契约测试已完成。用户已决定保留 coverage-first
seed3407 merged BF16 作为本版本中间训练产物，不再为本轮重新训练。V4.1 schema、
Prompt、Stub、HTTP 契约、Verifier、结果投影和 Web 展示已完成中间集成，并完成冻结的
110 视频运行。该运行链路完整、无运行时失败，但质量门失败；冻结 scorer 还缺少部分中文
权威列名映射，使时间、机制、位置和特殊样例分母为 0。官方门禁不做事后重算，存在性指标
本身也未达阈值。V2 继续作为回滚对象保留。

## 需求与范围

以下需求与技术方案描述的是当前仍在线的 V2 Agent 基线。V4.1 迁移不得只替换字段名；
必须按“实施规划”中的整体切换门一次性更新并重新验收这些行为。

本仓库包含自然语言意图识别、Agent 执行循环、Native Function Calling、视频裁剪与帧映射、视觉服务 HTTP 客户端、多轮证据记录、结论聚合、置信度校准接口、CLI、Web API 和本地工作台。用户可以询问是否断裂、断裂时间、类型、位置、置信度、视觉依据或完整分析；系统必须以用户问题为准投影回答，不能因用户只问二元问题而把异常、冲突或基础设施失败简化为“未断裂”。

MiniCPM 单轮主分析保持训练一致的四字段输出：`has_fracture`、当前 clip 实际采样帧中的局部 `fracture_between`、`type` 和 `location`。模型不直接输出 `confidence`。生产运行不从训练使用的多种 User Prompt 中随机抽取，也不允许 Planner 或用户覆盖视觉 Prompt；用户原话、Agent 历史和候选结论不得进入 MiniCPM 主分析请求。

Agent 最终业务结论固定为 `tensile-agent/result/v2`，包含显式 `has_fracture`、原视频 `time_range`、`fracture_type`、`location`、逐字段 `field_status`、分项 `confidence`、按需 `visual_evidence` 和安全 warning。断裂存在性成立但定位、类型或位置证据不足时返回 `fracture` 加字段级 `unavailable`，不得改写成阴性或整体不可识别。局部 `fracture_between` 只保存在对应不可变轮次证据中，绑定 clip hash、实际帧表、原视频映射、request ID 和任务级视觉部署快照。confidence 数值在校准前保持 `null`；Evidence 标记 `reliability=experimental`，不能声称已通过反事实可靠性验收。

训练数据治理、MiniCPM 微调、checkpoint、模型权重和视觉服务部署仍由独立 mVllm_2 仓库负责。本仓库只固定并校验其导出的 Prompt/schema/model/processor/generation 契约 artifact。在线流式分析、远程多用户服务、数据库、分布式队列、在线标注和每视频多个断裂事件不纳入当前范围。

## 技术方案

系统采用“自然语言意图层—确定性 Agent 策略—固定视觉调用—证据聚合—回答投影”架构。意图层把用户问题解析为受 schema 约束的请求字段、是否需要 evidence、是否需要 confidence、语言和歧义状态；无法识别、缺少视频或互相矛盾时先澄清，不启动视觉推理。Agent 可以执行完整内部分析，但公开响应只投影用户请求字段，并通过 `answered`、`unrecognized`、`failed` 区分正常回答、证据不足和运行失败。

TensileAgent 决策模型默认通过本机 Ollama 使用固定 16K 上下文的 Qwen3.5-9B，Qwen3-8B 作为本地对照，qwen3.7-max 仅作为用户手动启用的远程后端。本地后端不可用、模型缺失或工具调用非法时 fail closed，不自动把上下文发送到远程服务。CLI 启动参数、本机持久配置和仓库默认配置按明确优先级解析；每个任务固定记录实际后端、模型、digest 和 reasoning 设置。

所有决策模型调用统一保存脱敏 transport trace，记录实际 messages、tools、tool calls、响应、usage、耗时和错误。API Key、Base64、临时路径和视频载荷不得进入 trace；reasoning 默认关闭，只有用户显式启用时才记录服务实际返回的 reasoning 字段。Web 工作台允许在无运行中或排队任务时手动切换本地/远程后端，并提供逐轮传输回放和 JSON 导出。

视觉 Prompt 由程序维护的版本化 registry 构造。主分析使用唯一四字段生产候选 Prompt；按需 evidence 使用独立固定 Prompt，查看与主调用相同的 clip 和实际采样帧，不接收主调用标签，避免确认偏差。两类调用均采用确定性生成配置。mVllm_2 是跨仓 `tensile-vlm/v2` 自包含 artifact 的权威来源；artifact 同时承载 schema、枚举、分析/Evidence Prompt、generation、媒体约束和规范化 hash。视觉服务通过 `GET /v1/tensile/contract` 返回完整 deployment manifest 与能力声明；Runner 在任务开始时预检并锁定该快照，每轮发生 model、adapter、base model、processor、框架、配置、runtime 或 contract 漂移时立即 fail closed。旧 `tensile-vlm/v1` 不兼容且不保留双协议。

Agent 的 Planner 只选择合法工具、采样区间和受控任务模式，不能传入任意视觉 Prompt、写入证据或生成公共结论。Executor 校验工具参数、视频边界、预算和外部响应；Evidence Store 只采信字段、帧表和时间映射均合法的事实；Verifier 强制至少两轮一致断裂证据、断裂时间交集与容差、五个重叠区间阴性覆盖、异常复查、冲突处理和最大预算。单次高置信全局阴性不得直接结束。

置信度由程序依据多轮一致性、覆盖完整度、区间交集、解析与映射成功、异常/冲突状态等特征产生，并在独立 calibration split 上校准。视觉模型自报分数不参与终止。用户要求视觉依据时，公开摘要必须引用可回放的 round、clip、帧和原视频时间；内部 Prompt、密钥、Base64、临时绝对路径和不必要的服务 metadata 不对外暴露。

## 实施规划

1. **已完成**：冻结 V4.1 跨仓 Prompt/schema artifact、标签联动和 consumer hash。
2. **已完成但门禁失败**：冻结 Stage B 中间模型证据；不把失败改写为通过。
3. **延期**：Stage C full-data 训练；本轮不重新训练。
4. **已完成**：冻结中间 V4.1 服务 deployment manifest 和 V2 回滚对象。
5. **已完成**：迁移单轮 schema、搜索方向、证据结构、Stub、HTTP 客户端、Verifier、
   结果投影和 Web 展示。
6. **已完成但门禁失败**：Stage D 与 Stage G；110/110 运行和链路完整性通过，质量门失败。
7. **进行中**：建立单一交付中心、双机 Git 同步、训练机稳定部署、本机 SSH tunnel
   真实视频联调和断链 fail-closed 证据。
8. **生产切换门未满足**：只有未来重新完成并通过质量门、独立测试和生产授权，才允许
   标准配置或生产别名切换。

## 验收标准

1. “这个视频断了吗”“什么时候断的”“是什么类型、在哪里”“为什么”“你确定吗”和完整分析等中英文、口语、错别字输入都能解析为受控意图；无关、模糊、缺视频、矛盾和 Prompt 注入请求会澄清或拒绝，用户原话不会进入 MiniCPM 请求。
2. MiniCPM 主调用只接受程序生成的固定四字段 Prompt，输出、局部索引和服务端实际帧表可严格校验；相同模型、clip、Prompt 和生成配置重跑结果可复现。
3. 每个局部 `fracture_between` 都绑定来源轮次、clip 和帧表，并能映射为原视频 `time_range`；不同轮次相同局部索引不会被误认为同一帧。
4. 最终 `fracture` 至少由两轮可用断裂证据和非空时间交集支持；最终 `no_fracture` 必须完成五区间覆盖；异常、未夹紧、冲突、非法输出和基础设施失败不会收敛为错误的确定结论。
5. 用户只看到其请求字段和必要的不确定性。Evidence 摘要仅在按需视觉调用成功时展示，且每个声明都能追溯到帧和时间引用；未生成或失败时显式标记不可用。
6. 本 MVP 的分项 confidence 数值全部为 `null`，只允许输出代码推导的 evidence level；后续完成源视频隔离校准并记录方法版本后，才验收 Brier score、ECE、可靠性曲线和 coverage-risk。
7. V2 历史基线的 Fold 0 固定 Prompt 候选门槛继续作为回归参考，但不能直接套用到 V4.1。
   V4.1 必须基于三个 validation fold 重新报告严格 JSON/schema 合法率、`clip_state`、
   `fracture_mechanism`、`fracture_site`、`special_case`、联合准确率和源视频级失败分布，
   并单独检查 `临界未断裂` 与真实断裂状态的混淆。
8. 跨仓 artifact 能自动检测 Prompt、schema、枚举、模型、processor 或 generation 漂移；不一致时拒绝语义结果。CLI、Web API 和 Web 工作台使用同一 Runner 与公开响应契约。
9. Agent-only 单元测试、契约测试、自然语言投影测试、反事实记录测试、前端构建和 `git diff --check` 通过；真实 GPU 推理和最终 test 验收在训练机器执行并保存完整 manifest。
10. V4.1 切换前必须保存可回滚的 V2 服务与配置快照；切换后真实视频联调必须证明
    `临界未断裂` 只提供向后搜索线索、`grip_root` 与标距外非齐根语义不混淆，并且任何
    V2/V4.1 contract hash 漂移都会 fail closed。

## 风险与待确认事项

- [非阻塞] 当前四字段模型可能仍因同时承担检测、定位和分类而压缩正例边界；若固定 Prompt 基线达不到验收门槛，再进入重训，不在 Agent 侧用自由 Prompt 掩盖模型问题。
- [非阻塞] 第二次 evidence 调用可能产生事后合理化；必须通过断裂前截断、遮挡、无关帧替换和时序打乱反事实验证后才能作为公开视觉依据。
- [已解决] 视觉协议和公共结果直接升级到 v2，不保留 v1 DTO 兼容入口；历史标量不会冒充已校准概率。
- [已解决] 下一代视觉输出升级为 `tensile-vlm/v4.1`，既合并重复位置字段，又用独立 `临界未断裂` 状态承载韧性断裂前预测；迁移前 v2 继续是唯一运行时协议。

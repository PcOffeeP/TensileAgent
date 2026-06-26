# 统一模型—Agent 接口契约实施方案

> 状态：已批准
> 版本：3
> 项目计划：docs/PROJECT_PLAN.md
> 项目计划版本：8.1

## 步骤目标与范围

本步骤把项目计划中的模型输出、视频采样与 HTTP 传输、Prompt 分层、工具调用、最终结果和运行错误固化为唯一可执行契约，使数据构建、模型验证、Agent Runtime、CLI、UI 和评估后续都复用同一组字段、枚举和校验规则。完成后，仓库不得再以边界哨兵、宽松 JSON 提取、决策模型可选帧数或 FPS、共享本地路径、`has_fracture` 二值最终结果等旧接口继续工作。

本步骤实现契约模型、纯校验逻辑、采样与推理适配边界及其测试，但不建设训练数据、不训练或部署正式模型、不实现完整多轮决策循环，也不实现 CLI、Streamlit 和跨项目评估。完整覆盖、局部重复确认等规则在本步骤只体现为 `terminate` 提案的程序校验接口，实际调度在 Agent Runtime 实施方案中完成。

## 实施方案

### 契约分层

接口分为六层，各层不得复用同一个字段表达不同语义：

1. **微调视觉模型输出**：只描述本轮临时视频片段，严格包含五个字段。
2. **`sample_and_infer` 工具输入**：只允许决策模型提供检查区间和本轮完整 user prompt。
3. **工具可见结果**：向决策模型返回经过校验的紧凑结果，不暴露 Base64、临时路径和原始 HTTP 对象。
4. **内部诊断记录**：保存精确帧映射、HTTP 与服务元数据、重试和耗时，供追踪和评估使用。
5. **`terminate` 提案与公共结果**：决策模型只能提出结论和证据轮次；程序派生时间区间并执行终止门槛。
6. **Runner 运行信封**：区分正常分析结果与基础设施或配置失败，后者不能伪装成 `unrecognized`。

所有契约采用禁止额外字段的严格校验。数值字段接受 JSON number 但拒绝 boolean，并在通过校验后规范化为声明的 Python 类型。旧的 `BoundaryStatus`、置信度中文等级、估计时刻、公共帧区间和宽松兼容字段不进入新公共契约。

### 微调视觉模型输出

模型 assistant 内容必须整体是一个 JSON object，不接受 Markdown 代码块、前后解释文字、从噪声中截取 JSON、缺失字段、额外字段或静默默认值。对象固定包含：

| 字段 | 合法规则 |
|---|---|
| `has_fracture` | boolean / `null`；`null` 只表示视频异常导致无法确定是否断裂 |
| `fracture_between` | 七种正常断裂模式且时间可定位时为 `[i,i+1]`，满足 `0 <= i < i+1 < N`；其他情况为 `null` |
| `type` | 七种正常断裂模式之一，或 `未断裂`、`未夹紧`、`视频异常` |
| `location` | 七种正常断裂模式时为 `inside_gauge` 或 `outside_gauge`；其他情况为 `null` |
| `confidence` | `[0.0,1.0]` 内的 JSON number，拒绝 NaN、Infinity 和 boolean |

五字段只接受以下组合：

| 当前片段语义 | `has_fracture` | `fracture_between` | `type` | `location` |
|---|---|---|---|---|
| 正常断裂且可定位 | `true` | 严格相邻 `[i,i+1]` | 七种断裂模式之一 | `inside_gauge` / `outside_gauge` |
| 确认未断裂 | `false` | `null` | `未断裂` | `null` |
| 未夹紧 | `false` | `null` | `未夹紧` | `null` |
| 视频异常，无法确定是否断裂 | `null` | `null` | `视频异常` | `null` |
| 视频异常，确认断裂但时间不可靠 | `true` | `null` | `视频异常` | `null` |

其他组合全部非法。解析器先验证 JSON 语法和完整字段集合，再验证上述条件字段、类别闭集、相邻关系和本轮实际输入帧数 `N`。任何失败都返回带稳定错误码和具体字段信息的校验错误，不截断索引、不删除额外字段，也不猜测类别。

模型首次输出非法时，推理客户端保留相同 system prompt、原始 user prompt 和同一视频，在原始请求后追加具体校验错误及“仅重新输出完整五字段 JSON”的纠错信息；最多纠错两次，即一次初始请求加两次重试。三次均失败时，本轮工具结果为 `ok=false`、`model_output=null`、`inferred_time_range=null` 和 `validation_error.code=invalid_model_output`。重试不得把非法结果修补成合法结果。

### Prompt 与 HTTP 请求

微调视觉模型使用与训练完全相同且版本化的固定 system prompt，决策模型无权修改。决策模型根据当前候选区间、历史摘要和本轮目的生成完整 user prompt；程序只检查其非空、长度上限和禁止重复视觉标记，不改写分析意图。默认最大长度为 4096 个 Unicode 字符，可通过运行配置收紧。

运行时 user prompt 不包含字面量 `<video>`。`InferenceClient` 按 `video_url`、文本的顺序构造 OpenAI-compatible 多模态 user content，`video_url.url` 必须是 `data:video/mp4;base64,...`；服务模板负责产生模型所需的视觉标记。客户端不得把本地绝对路径、相对路径或 `file://` URI发送给服务，也不得要求 Agent 与模型服务共享文件系统。训练数据中的一个 `<video>` 标记与运行时的一段 `video_url` 在一致性测试中按同一语义核对。

HTTP assistant 内容仍严格只有五字段模型 JSON。项目侧模型服务适配层在标准响应外增加内部 `preprocessing` 元数据，至少包含请求 ID、实际处理器版本、实际最大帧数以及本轮选择的临时视频帧索引和时间戳。`InferenceClient` 使用临时视频生成清单把这些索引映射回原视频；该元数据不进入模型 prompt、五字段 JSON、决策模型上下文或公共结果。服务缺少元数据、最大帧数不是 8、索引数量超过 8、顺序异常或无法映射时，Runner 返回 `ok=false` 和 `missing_or_invalid_preprocessing_metadata`，不能只根据本地公式猜测。

客户端在发送前验证 MIME、Base64 可解码性和请求体大小，默认上限为 32 MiB；连接超时默认 10 秒、读取超时默认 300 秒。连接重置、超时和 HTTP 5xx 最多进行两次指数退避重试；认证失败、请求格式错误和其他确定性 4xx 不重试。传输重试与模型输出纠错重试分别计数。传输最终失败属于 Runner 运行错误，不转成模型非法输出或 `unrecognized`。

本步骤不修改 `LlamaFactory/` submodule。OpenAI-compatible 服务能力通过项目侧客户端、配置、启动前校验和部署清单适配；若当前服务不支持 Base64 `video_url`，应使启动或健康检查失败，而不是恢复本地路径传输。

### MiniCPM-V 最多 8 帧的采样与映射

`sample_and_infer` 的决策模型参数只有：

- `sample_range`：两个有限秒数 `[start,end]`，必须满足 `0 <= start < end <= video_duration`。
- `prompt`：符合上述约束的完整 user prompt。

源视频由当前 Runner 上下文绑定，不是工具参数。`num_frames`、`video_fps`、`sampling_strategy` 和 `expected_schema` 从 Native Function Calling schema 中移除，未知参数直接拒绝。

程序根据 `sample_range` 裁剪连续临时 MP4，不在模型处理器之前选帧，也不改变时间轴 FPS。允许为 HTTP 大小和模型输入分辨率进行确定性的空间缩放与视频压缩，但不得进行抽帧、补帧或改变播放时长；生成过程保存临时视频每个帧序号到原视频帧号和时间戳的清单。临时视频只作为本轮 HTTP Base64 数据来源，位于 ignored 的 `data/08_runtime/`，不得成为跨服务路径接口。

MiniCPM-V 4.5 的实际 `video_processor` 负责从连续视频时间轴均匀选择最多 8 帧，短视频允许少于 8 帧。项目不配置额外采样 FPS，也不能仅凭 LLaMA-Factory 外层 `video_maxlen` 判断配置生效；训练和模型服务启动时必须检查子处理器的实际最大帧数。服务部署清单记录模型、Transformers、LLaMA-Factory、处理器版本、实际最大帧数、基础模型、适配器或合并模型版本及配置指纹。配置指纹（fingerprint）由项目侧预处理器生成，包含：处理器 `NAME` 常量与模型路径/名称、关键模型配置文件 `config.json`（以 `cfg=` 标记）和 `preprocessor_config.json`（以 `pre=` 标记）内容的 SHA-256 前 16 位（本地目录存在时计算，不存在则退化到仅使用路径字符串）、`max_frames` 以及 backend 加载状态（`transformers-loaded` / `transformers` / `no-transformers`）；该指纹用于训练、推理与部署清单的可复现性校验，不得包含 mock/theoretical 标识。

训练数据构建器和模型服务复用同一项目侧预处理适配层：前者取得真实处理器选择结果后生成 `fracture_between` 标签，后者把同类元数据随 HTTP 响应返回。初始化校验使用带可识别顺序和时间戳的不同长度连续视频，通过真实 MiniCPM-V 4.5 处理器确认抽帧数量不超过 8、顺序单调、训练与服务选择一致，并能映射回源视频；任一条件不满足时禁止生成训练数据或定位结果。

只有七种正常断裂模式的 `fracture_between` 通过响应中的实际帧表直接映射成 `[frames[i].timestamp, frames[i+1].timestamp]` 和内部原视频帧区间，不根据 FPS、区间宽度或理论均匀间隔重新推算。未断裂、未夹紧和两种视频异常的派生时间区间均为 `null`；其中“确认断裂但时间不可靠”的异常不得使用 CSV 中的不可靠时间补出区间。

### 工具结果与内部诊断

决策模型只能看到以下紧凑工具结果：

| 字段 | 说明 |
|---|---|
| `ok` | 是否获得通过全部校验的五字段模型输出 |
| `sample_range` | 程序实际接受的原视频检查区间 |
| `model_output` | 合法五字段对象；失败时为 `null` |
| `inferred_time_range` | 由实际帧映射得到的区间；无断裂或失败时为 `null` |
| `validation_error` | 模型输出最终非法时的稳定错误对象；成功时为 `null` |
| `attempts` | 本轮模型输出尝试次数，范围为 1 至 3 |

内部诊断与公共结果分开保存，至少记录服务返回的实际输入帧表、连续临时视频到原视频的映射清单、内部原视频帧区间、临时视频哈希和字节数、MIME 与 Base64 长度、原始 HTTP 响应、传输和纠错重试明细、服务部署清单、请求耗时、资源信息及所有错误。工具根据合法组合在内部标记 `video_anomaly_kind`：`fracture_presence_unknown` 表示无法确定是否断裂，`fracture_time_unknown` 表示确认断裂但时间不可靠；该标记不增加模型输出字段。默认日志不得保存完整 Base64、API key 或 token。决策模型上下文只引用紧凑结果和必要历史摘要，不能读取或回传内部临时路径。

### 终止提案、公共结果与运行错误

决策模型调用 `terminate` 时只提出 `status`、`fracture_type`、`location`、`confidence`、`unrecognized_reason` 和 `evidence_rounds`。程序从指定且合法的证据轮次派生 `time_range`，检查至少两次局部断裂证据具有非空共同交集、完整视频未断裂检查等门槛；不合法提案被拒绝并把具体原因返回决策模型，程序不得静默改写为另一状态。两种视频异常都只能支持 `unrecognized_reason=video_anomaly`，不能支持 `fracture` 或 `no_fracture`。

公共结果固定包含 `video_id`、`status`、`time_range`、`fracture_type`、`location`、`confidence` 和 `unrecognized_reason`。字段条件如下：

- `fracture`：`time_range` 必填且宽度不超过 1 秒；`fracture_type` 为七类之一；`location` 为 `inside_gauge`、`outside_gauge` 或 `unknown`；`confidence` 必填；`unrecognized_reason=null`。
- `no_fracture`：`time_range`、`fracture_type`、`location` 和 `unrecognized_reason` 均为 `null`，`confidence` 必填。
- `unrecognized`：除 `video_id` 和 `status` 外只填写 `unrecognized_reason`；`time_range`、`fracture_type`、`location` 和 `confidence` 均为 `null`。

`unrecognized_reason` 闭集为 `video_anomaly`、`not_clamped`、`conflicting_results`、`invalid_model_output`、`insufficient_confidence`、`incomplete_coverage` 和 `max_rounds`。这些原因只表示分析流程正常运行但无法形成可靠结论。

Runner 统一返回 `{ok:true,result:<公共结果>,error:null}` 或 `{ok:false,result:null,error:{stage,code,message}}`。输入文件、配置、采样器、模型 HTTP 传输、决策模型 API 和程序内部故障属于 `ok=false`；错误 `stage` 使用 `input`、`configuration`、`sampling`、`inference_transport`、`decision_backend` 或 `internal`。公共结果和内部诊断可在持久化产物中并列保存，但 CLI、UI 和外部交换默认只把公共结果视为结论。

## 执行清单

- [ ] 建立唯一的契约模型和枚举，替换旧架构文档引用、边界哨兵、二值最终结果、置信度等级及宽松兼容字段；形成支持两类视频异常的模型输出、工具结果、终止提案、公共结果和 Runner 信封校验入口。
- [ ] 统一训练与推理的视觉模型 system prompt 和五字段 JSON 语义，删除噪声 JSON 提取、额外字段过滤和静默默认值，建立带稳定错误码的严格解析与两次纠错重试。
- [ ] 收紧 Native Function Calling 工具 schema，使 `sample_and_infer` 只接收 `sample_range` 与 `prompt`，并使 `terminate` 只提交结论字段和证据轮次；未知或越界参数能得到可操作的拒绝原因。
- [ ] 重构连续临时视频边界，保证裁剪和压缩不改变时间轴或预先抽帧，生成可把临时视频帧序号映射回原视频的清单，并通过 Base64 发送该连续媒体。
- [ ] 将 MiniCPM-V 4.5 实际子处理器的最大帧数设置为 8，移除项目级 FPS 覆盖；建立训练与服务共用的真实预处理适配层、校准样本和部署清单，参数、数量、顺序或映射不一致时显式失败。
- [ ] 实现只发送 Base64 `data:video/mp4` 的 OpenAI-compatible 推理客户端和项目侧服务适配层，保持 assistant 内容为五字段 JSON，并在响应内部扩展中返回实际抽帧元数据；完成媒体顺序、大小和超时检查、传输重试及敏感信息脱敏，不修改 LLaMA-Factory submodule。
- [ ] 分离决策模型可见工具结果与内部诊断，移除工具结果中的临时路径、完整帧表和 HTTP 对象，同时保证诊断产物可追踪每次采样、请求、响应和重试。
- [ ] 实现终止提案和 Runner 信封的纯契约校验，确保程序派生时间区间、拒绝不满足证据门槛的提案，并把运行故障与 `unrecognized` 原因严格分开。
- [ ] 更新契约 fixtures 和项目级测试，覆盖五种合法模型字段组合、两类视频异常、所有公共状态、类别闭集、相邻和越界索引、2 至 8 帧采样、Base64 请求、三次非法输出、传输失败、终止门槛及敏感信息不落日志。

## 预期结果

仓库形成一套绑定项目计划 v8.1 的唯一模型—Agent 接口。微调视觉模型、数据样本、单次推理和 Agent 工具共享同一个严格五字段模型输出，并能区分“无法确定是否断裂”和“确认断裂但时间不可靠”；决策模型只能控制允许自主选择的分析区间和 prompt；MiniCPM-V 4.5 从连续媒体中实际选择最多 8 帧，并通过内部响应元数据把帧索引追溯到原视频时间；本地和远程模型服务都通过相同 Base64 HTTP 接口接入。

后续 Agent Runtime 可以只消费合法紧凑结果并提交终止提案，不需要理解视频编码、模型响应清洗或本地文件路径。CLI、UI 和评估可以稳定区分公共结论、内部诊断、无法辨认和运行失败。

## 验收标准

- 项目计划保持 `已批准` v8.1，本实施方案批准后通过实施文档校验器，所有新契约不再引用已归档设计作为权威来源。
- 活动 Agent 工具不再暴露或接受 `num_frames`、`video_fps`、`sampling_strategy`、`expected_schema`；MiniCPM-V 4.5 实际子处理器的最大帧数为 8，项目不存在额外 FPS 覆盖，外层 `video_maxlen` 不能替代子处理器检查。
- 真实视频测试证明连续临时媒体未被预先抽帧或改变时间轴；真实 MiniCPM-V 4.5 处理器对任意合法区间最多选择 8 个顺序单调的帧，短区间允许少于 8 帧，训练与服务的数量、顺序和映射一致。
- HTTP 请求测试证明视频内容位于文本前、媒体为可解码的 `data:video/mp4;base64`，请求中没有本地路径；assistant 内容只有五字段 JSON，内部响应元数据能给出实际处理器版本、最大帧数和抽帧索引。缺失或非法元数据、超大媒体、确定性 4xx、可重试传输错误分别按约定处理。
- 模型输出只有完整、无额外字段且属于五种合法组合时才成功；Markdown、解释文字、缺失或额外字段、错误类别、boolean 置信度、错误的空值组合、非相邻或越界索引均失败，最多两次纠错后得到 `invalid_model_output`。
- 七种正常断裂输出只使用服务返回并成功映射的实际帧表得到唯一 `inferred_time_range`；未断裂、未夹紧和两种视频异常均为 `null`，且不使用不可靠的 CSV 时间补值；任何换算都不依赖理论 FPS 或区间平均间隔。
- 决策模型可见结果只包含六个约定字段；内部诊断保留完整追踪信息但不保存 Base64 和凭据，也不把本地路径暴露给决策模型。
- 两种视频异常都只能生成 `unrecognized_reason=video_anomaly`；三种公共状态及七种 `unrecognized_reason` 全部通过条件字段测试。不满足证据门槛的 `terminate` 提案被拒绝，连接、配置、文件和决策后端失败只产生 Runner `ok=false`。
- `python3 -m pytest tests -q`、真实预处理校准测试和 `git diff --check` 均通过，且无需修改 `LlamaFactory/` submodule。

## 风险与待确认事项

- [非阻塞] LLaMA-Factory 外层 `video_maxlen` 不一定传入 MiniCPM-V 4.5 子处理器，且后续版本可能改变视频读取行为；通过检查实际子处理器、锁定依赖、返回抽帧元数据和真实预处理校准阻止静默漂移。
- [非阻塞] Base64 会增加约三分之一请求体积，连续完整视频可能超过默认 32 MiB 请求上限；工具可以在不改变时间轴和帧序列的前提下做空间缩放与压缩，仍超限时作为运行错误显式报告，不能通过项目侧预抽帧规避。
- [非阻塞] LLaMA-Factory 默认 OpenAI-compatible 服务可能不返回实际抽帧元数据；项目侧服务适配层必须补充该内部元数据，否则该服务只能用于不涉及时间定位的诊断，不能接入正式 Agent。

## 实施进度标注

> 本章节由实施阶段维护，用于对照本文档的「执行清单」与「验收标准」记录实际落地状态、文件位置、关键缺口及下一步 owner。不影响正文内容。

### 总体状态

| 维度 | 状态 | 说明 |
|---|---|---|
| 契约模型与校验 | 已完成 | `agent/schema.py`、`agent/parser.py` 已覆盖 v3 五字段模型输出、工具 schema、公共结果信封和严格解析。 |
| Prompt 契约 | 已完成 | `agent/prompts.py` 已统一 system prompt 与五字段 JSON 语义。 |
| Native Function Calling 工具 schema | 已完成 | `agent/schema.py` 中 `ToolSampleAndInfer` / `ToolTerminate` 已收紧参数。 |
| 预处理适配层抽象 | 已实现，待训练机验证 | `pipeline/preprocessing/minicpm_preprocessor.py` 强制真实子处理器最大 8 帧；`finetune/train_with_contract.py` 在每个训练进程加载 processor 时应用同一约束；本机缺少模型依赖时 fail closed。 |
| 校准与质量冻结 | 已实现，待训练机执行 | 正式校准和训练数据 CLI 不允许 mock；校准比较适配层与 LLaMA-Factory 实际调用的帧表、tensor shape/digest，局部 case 处理同一个连续 clip 并映射回原视频。 |
| Base64 HTTP 推理客户端 | 已完成 | 已包含媒体校验、独立传输/纠错重试、纠错对话链、日志脱敏及强制 `preprocessing` 元数据校验；缺失或不可映射时 Runner fail closed。 |
| 连续临时视频边界裁剪 | 已完成 | `agent/sampling.py` 的 `FfmpegVideoClipBuilder.build_with_manifest` 已按 `sample_range` 直接裁剪连续 MP4 + manifest。 |
| 终止提案与 Runner 信封纯契约校验 | 已完成 | `agent/iterative_agent.py` 已迁移到 `ToolSampleAndInfer`/`ToolTerminate`/`FinalOutput` 契约模型，支持程序派生 `time_range`、拒绝不满足证据门槛的提案，并区分 Runner `ok=false` 与 `unrecognized`。 |
| 真实 MiniCPM-V 4.5 处理器接入 | 代码完成，需训练机验证 | `sample()` 已实现真实处理器调用、实际 PTS 和 8 帧上限校验；需在目标版本依赖上确认参数名及输出形状。 |
| LLaMA-Factory 实际 batch 校准 | 需训练机环境 | 校准脚本通过项目侧真实处理器捕获补充 stock plugin 不返回的帧映射，并比较同一连续 clip；尚未在真实训练机执行。 |

### 执行清单逐项状态

- [x] **建立唯一的契约模型和枚举**
  - 状态：已完成
  - 位置：`agent/schema.py`（`ModelOutput`、`FinalOutput`、`ToolSampleAndInfer`、`ToolTerminate`、`FractureType`、`LocationType` 等）
  - 说明：已替换旧架构文档引用、边界哨兵、二值最终结果、置信度等级；支持两类视频异常的模型输出、工具结果、终止提案、公共结果和 Runner 信封校验入口。
- [x] **统一训练与推理的视觉模型 system prompt 和五字段 JSON 语义**
  - 状态：已完成
  - 位置：`agent/prompts.py`（`SYSTEM_PROMPT`、`build_user_prompt`）
  - 说明：已删除噪声 JSON 提取、额外字段过滤和静默默认值，严格按五种合法组合定义。
- [x] **严格解析与两次纠错重试**
  - 状态：已完成
  - 位置：`agent/parser.py`（`ResultParser`、`ParseError`、`ParseResult`）
  - 说明：解析器带稳定错误码；重试接口已由 `ResultParser.parse_with_retry` 暴露，调用方负责追加纠错 prompt 并限制最多两次重试。
- [x] **收紧 Native Function Calling 工具 schema**
  - 状态：已完成
  - 位置：`agent/schema.py`（`ToolSampleAndInfer`、`ToolTerminate`）
  - 说明：`sample_and_infer` 只接收 `sample_range` 与 `prompt`；`terminate` 只提交结论字段和证据轮次。
- [x] **重构连续临时视频边界**
  - 状态：已完成
  - 位置：`agent/sampling.py`（`FfmpegVideoClipBuilder.build_with_manifest`）
  - 说明：已改为按 `sample_range` 直接裁剪连续 MP4，保留源视频时间轴；生成并返回临时视频帧序号到原视频帧号/时间戳的映射清单，作为后续 Base64 传输与 `fracture_between` 映射的依据。
- [x] **将 MiniCPM-V 4.5 实际子处理器的最大帧数设置为 8，建立真实预处理适配层与校准**
  - 状态：代码完成，真实环境验收待执行
  - 位置：`pipeline/preprocessing/minicpm_preprocessor.py`、`pipeline/llamafactory_contract.py`、`finetune/train_with_contract.py`、`pipeline/scripts/calibration.py`
  - 缺口：需在训练机验证目标 Transformers/LLaMA-Factory 版本的实际参数、抽帧数量、顺序及映射一致性。
  - 下一步 owner：训练机环境 owner + 预处理模块开发者。
- [x] **实现只发送 Base64 `data:video/mp4` 的 OpenAI-compatible 推理客户端**
  - 状态：已完成
  - 位置：`agent/inference.py`（`LlamaFactoryInferenceClient`）
  - 说明：已改为读取临时 MP4 并编码为 `data:video/mp4;base64` 发送；不再暴露本地路径；增加 MIME/请求大小检查、超时、传输重试、敏感信息脱敏；`ClipBuildResult.manifest` 通过请求 `extra_body` 作为内部预处理元数据发送；模型输出通过 `ResultParser` 解析为 `dict | None`。
- [x] **项目侧服务适配层扩展内部 `preprocessing` 响应元数据**
  - 状态：同进程集成服务与适配代码完成，真实部署待训练机执行
  - 位置：`pipeline/server_proxy.py`、`pipeline/llamafactory_contract.py`、`pipeline/server_adapter.py`、`agent/inference.py`
  - 说明：集成服务直接创建 LLaMA-Factory ChatModel，包装模型本次实际调用的 `video_processor`，捕获帧表和 tensor digest 后注入元数据；强制 `API_VERBOSE=0`，不依赖 submodule 不存在的采样字段或第二处理器重放。适配器和客户端严格验证版本、8 帧上限、连续索引、单调时间戳和部署清单，缺失、非法或无法映射时 fail closed。
- [x] **分离决策模型可见工具结果与内部诊断**
  - 状态：已完成
  - 位置：`agent/schema.py`（`ToolResult` / 公共结果模型，诊断字段在契约中定义）；`agent/iterative_agent.py` 已迁移到契约模型。
  - 说明：契约定义已完成；`agent/iterative_agent.py` 运行时已迁移到 `ToolSampleAndInfer`/`ToolTerminate`/`FinalOutput`，不再暴露临时路径、完整帧表和 HTTP 对象。
- [x] **实现终止提案和 Runner 信封的纯契约校验**
  - 状态：已完成
  - 位置：`agent/iterative_agent.py`（已迁移到 `ToolSampleAndInfer`/`ToolTerminate`/`FinalOutput` 契约模型）
  - 说明：已实现程序派生 `time_range`、拒绝不满足证据门槛的提案；Runner `ok=false` 与 `unrecognized` 严格区分，旧 `TOOLS_SCHEMA` 已移除。
- [x] **更新契约 fixtures 和项目级测试**
  - 状态：已完成本地测试
  - 说明：覆盖五种合法组合、两类视频异常、Base64、纠错重试、Runner 错误、固定覆盖、局部证据、复查门槛和元数据 fail-closed。

### 验收标准对照

| 验收标准 | 状态 | 位置/说明 |
|---|---|---|
| 项目计划保持 `已批准` v8.1，本实施方案通过实施文档校验器 | 已完成 | `validate_implementation_doc.py` 已确认结构完整、版本一致且允许执行。 |
| Agent 工具不再暴露/接受 `num_frames`、`video_fps`、`sampling_strategy`、`expected_schema`；MiniCPM-V 4.5 实际子处理器最大帧数为 8，无项目级 FPS 覆盖 | 已完成 | `agent/schema.py` 的工具 schema 已移除这些字段；`agent/iterative_agent.py` 已迁移到新契约模型，旧 `TOOLS_SCHEMA` 不再存在。真实 8 帧校验待训练机环境完成。 |
| 真实视频测试证明连续临时媒体未被预先抽帧或改变时间轴 | 已完成 | `agent/sampling.py` 的 `FfmpegVideoClipBuilder` 直接按 `sample_range` 裁剪连续 MP4，并通过测试验证临时视频帧数/时长/FPS 与源视频区间一致。 |
| 真实 MiniCPM-V 4.5 处理器对合法区间最多选择 8 个顺序单调帧，训练/服务一致 | 需训练机环境 | 代码已 fail closed；需用目标模型、Transformers 与 LLaMA-Factory 版本执行校准。 |
| HTTP 请求测试证明 Base64 `data:video/mp4`、无本地路径、assistant 内容为五字段 JSON | 已完成 | `agent/inference.py` 通过测试验证发送 `data:video/mp4;base64`，消息顺序为 video_url 后 text，不泄露本地路径；解析失败返回 `None`。 |
| 内部响应 `preprocessing` 元数据完整 | 代码完成，待部署验证 | `pipeline/server_proxy.py` 同进程捕获模型实际 `video_processor` 调用的帧与 tensor digest，并调用 `pipeline/server_adapter.py` 注入元数据；需在目标训练机启动服务并做真实请求验证。 |
| 模型输出只有完整、无额外字段且属于五种合法组合时才成功；非法情况均失败，最多两次纠错后得到 `invalid_model_output` | 已完成 | `agent/parser.py` + `agent/schema.py` 已实现。 |
| 七种正常断裂输出只使用服务返回的实际帧表得到唯一 `inferred_time_range`；其余情况为 `null` | 已完成 | Agent 通过服务帧时间戳与实际 PTS manifest 映射；缺失或不一致直接返回 Runner 错误。 |
| 决策模型可见结果只包含六个约定字段；内部诊断不保存 Base64/凭据/本地路径 | 已完成 | 契约定义已完成；`agent/iterative_agent.py` 已迁移到契约模型。 |
| 两种视频异常只能生成 `unrecognized_reason=video_anomaly`；三种公共状态及七种 `unrecognized_reason` 全部通过条件字段测试；不满足证据门槛的 `terminate` 提案被拒绝 | 已完成 | `agent/iterative_agent.py` 已实现终止提案和 Runner 信封纯契约校验。 |
| `python3 -m pytest tests -q`、真实预处理校准测试和 `git diff --check` 均通过，且无需修改 `LlamaFactory/` submodule | 部分完成 | 本地 `586 passed, 1 skipped`、`validate_no_oob` 1694 条零错误、实施文档校验器、compileall 和 `git diff --check` 通过，submodule 未修改；真实 MiniCPM/LLaMA-Factory 校准仍需训练机执行。训练机命令与证据要求见 `model-agent-contract-training-machine-checklist.md`。 |

### 关键缺口与下一步 owner

| 缺口 | 影响 | 下一步 owner |
|---|---|---|
| 在目标训练机启动同进程 `pipeline.server_proxy` 集成服务 | 阻塞真实服务端到端元数据验证 | 训练机环境 owner |
| 在目标模型/Transformers 版本运行真实 `MiniCPMVideoPreprocessor` | 阻塞 8 帧参数名、输出形状及实际 PTS 映射验收 | 训练机环境 owner |
| `pipeline/scripts/calibration.py` 尚未在真实训练机上执行 LLaMA-Factory 实际 batch 校准 | 无法确认训练配置指纹、处理器版本、部署清单一致性 | 训练机环境 owner |

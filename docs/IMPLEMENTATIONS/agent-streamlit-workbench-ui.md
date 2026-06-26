# Agent 本地 Web 工作台实施方案

> 状态：已批准
> 版本：2
> 项目计划：docs/PROJECT_PLAN.md
> 项目计划版本：9.0

## 步骤目标与范围

本步骤完成项目计划第 5 步中“本地 Web 工作台、本地 API、共享 Runner、决策循环、模型 API 调用和程序级终止门槛”的交互入口部分：用完整前端替代已实现的 Streamlit MVP 工作台，构建一个本地单用户 Web 工作台，使竞赛评委和研究人员可以上传或选择拉伸实验视频、查看顺序任务队列、实时观察 Agent 多轮分析过程、回看本地历史记录并导出公共结果。

本步骤以 `/Users/pcoffeep/Downloads/Kimi_Agent_Deployment_v4` 为 UI 结构和视觉参考。参考内容包括左侧导航、主工作区上传与队列、右侧实时日志与结果面板、历史记录筛选、配置摘要、紧凑深色控制台风格和状态色体系。实现时不直接复用压缩构建产物，不迁移其模拟数据、模型名称或不符合当前 Agent 契约的文案。

本步骤包含 React/Vite 前端、本地 FastAPI API、SSE 实时事件、本地 JSON 历史持久化、单 worker 顺序队列、静态产物托管、启动说明和配套测试。本步骤不修改 `IterativeAgent` 的决策规则、Native Function Calling 契约、模型五字段输出、训练 pipeline、模型 HTTP 服务或评估指标；不建设账号权限、多用户隔离、远程部署、数据库迁移、分布式队列、在线标注或真值读取能力。

原 Streamlit 工作台可以在实现过程中保留为旧入口或移除，但新验收入口以本地 Web 工作台为准。CLI 必须继续可用，并继续与 Web 工作台共享 `agent/runner.py`。

## 实施方案

采用“React/Vite 前端 + FastAPI 本地 API + 共享 Runner”的路线。前端源码放在 `web/`，使用 React、TypeScript、Vite、Tailwind CSS 和 lucide-react。后端新增项目内本地 API 入口，建议位于 `agent/web_api.py` 或 `agent/web/`，使用 FastAPI 和 Uvicorn 封装 `agent/runner.py`。前端不实现 Agent 决策逻辑，只消费 API、事件流和公共结果。

后端维护一个本地单用户任务注册表。任务状态至少包含 `queued`、`running`、`completed`、`failed`，可预留 `cancelled` 但本步骤不要求实现运行中取消。任务执行采用单 worker 顺序队列，同一时间只运行一个视频分析任务；前端可以一次上传多个视频并展示排队状态。API 保存上传文件、创建任务、启动队列、调用 runner、接收 runner 事件回调、写入事件摘要和最终结果。

实时过程展示使用 SSE 单向事件流。后端将 runner 的 `video_started`、`round_started`、`llm_tool_call`、`sample_and_infer_finished`、`state_updated`、`video_finished` 和 `video_failed` 规范化为前端事件，并追加必要的任务级事件，例如 `task_created`、`task_queued`、`task_started`、`task_completed` 和 `task_failed`。SSE 事件不得携带完整 Base64、API key、token 或不必要的内部临时路径。

历史记录使用 ignored runtime 目录下的本地 JSON 文件持久化，建议根目录为 `data/08_runtime/web_workbench/`。每个任务保存任务索引、上传文件元数据、公共结果、错误信封、事件摘要和导出所需的最小数据。历史记录需要支持前端刷新和服务重启后的回看；删除历史任务时只删除该任务的索引、事件、结果和上传副本，不触碰原始 `data/01_videos/` 数据。

前端采用参考 UI 的三栏控制台结构：左侧为品牌、导航和近期任务；中间为“实验分析”主工作区，包含上传区、路径/目录输入、队列和开始分析控制；右侧为当前任务详情，包含实时状态、轮次摘要、终端式日志流、结果卡片和折叠 JSON。历史视图提供搜索、状态筛选、结果回看和删除；配置视图展示当前 API 地址、配置文件路径、Mock 状态、模型服务提示和运行限制，但不保存密钥。

开发模式采用双进程：`python3 -m agent.web_api` 启动 API，`cd web && npm run dev` 启动前端并代理 `/api`。展示模式采用单进程托管：`cd web && npm run build` 生成 `web/dist`，FastAPI 在指定参数或默认配置下托管静态产物，用户打开本地地址即可使用完整前端。

## 执行清单

- [x] 清理当前 UI 路线边界，确认 Streamlit 工作台不再作为新验收入口；已移除旧 `ui/agent_app.py`，不影响 CLI 和共享 runner。
- [x] 补充 Python 依赖和启动入口，加入 FastAPI、Uvicorn 及必要的 multipart/SSE 支持，并确保项目包配置包含新的 API 模块。
- [x] 设计并实现本地 Web API 的任务模型、错误模型和事件模型，复用 `{ok, result, error}` Runner 信封和三种 Agent 最终状态。
- [x] 实现上传与任务创建 API，支持单文件上传、本地视频路径创建任务、目录批量创建任务，并把上传副本写入 ignored runtime 目录。
- [x] 实现单 worker 顺序队列，按 `queued` 到 `running` 到 `completed`/`failed` 的生命周期调用 `runner.run_one`，并保证单任务失败不阻塞后续队列。
- [x] 实现 SSE 事件流，把 runner 回调事件规范化为 UI 事件，同时持久化事件摘要并过滤 Base64、API key、token 和不必要的内部临时路径。
- [x] 实现本地 JSON 历史持久化，支持任务列表、任务详情、事件回放、结果读取、历史删除和服务重启后的索引恢复。
- [x] 实现结果导出 API，至少支持 JSON、JSONL 和 CSV，字段与 Runner 公共结果和现有 CLI 导出语义兼容。
- [x] 初始化 `web/` 前端工程，配置 React、TypeScript、Vite、Tailwind CSS、lucide-react、基础 lint/build/test 脚本和 `/api` dev proxy。
- [ ] 构建参考式前端布局，完成左侧导航、实验分析、历史记录、配置摘要和右侧任务详情面板。
- [ ] 实现前端上传、路径/目录输入、任务队列、任务选择、删除历史、开始分析、SSE 订阅、断线重连提示和错误状态展示。
- [ ] 实现公共结果展示，按 `fracture`、`no_fracture`、`unrecognized` 和运行失败分别展示状态、时间区间、断裂模式、位置、置信度、轮数、失败阶段、错误码和错误消息。
- [ ] 实现前端导出入口、折叠 JSON、历史筛选和配置摘要；普通分析界面不得读取标注 CSV 或冻结测试真值。
- [ ] 支持展示模式静态托管，使 FastAPI 能服务 `web/dist`，同时保留开发模式双进程启动。
- [ ] 更新 README 或运行文档，记录开发模式、展示模式、Mock 模式、API 地址、前端构建、历史目录和安全限制。
- [ ] 补充后端单元测试，覆盖任务创建、队列状态转换、runner 回调事件规范化、SSE 输出、历史 JSON 恢复、导出格式和敏感字段过滤。
- [ ] 补充前端或端到端测试，至少覆盖构建成功、主要视图渲染、上传/任务创建 mock、SSE 事件展示、结果卡片、历史筛选和窄屏布局不重叠。

## 预期结果

执行完成后，仓库提供一个本地单用户完整 Web 工作台。用户在本机启动 FastAPI 服务和前端开发服务，或启动托管静态产物的单进程展示服务后，可以在浏览器中完成视频上传、任务排队、Agent 实时过程观察、结果查看、历史回看和导出。

CLI 和 Web 工作台继续共享 `agent/runner.py`。Agent 运行结果仍遵循 Runner 信封和 `fracture`、`no_fracture`、`unrecognized` 三种最终状态。普通 Web 分析界面不读取真值，不暴露完整 Base64、token、API key 或不必要的内部临时路径。历史记录在本地 runtime 目录中跨服务重启保留。

## 验收标准

- `docs/PROJECT_PLAN.md` 保持 `已批准` v9.0，本文档通过实施文档校验器并绑定项目计划 v9.0。
- 开发模式下，从仓库根目录启动 `python3 -m agent.web_api`，再运行 `cd web && npm run dev`，浏览器可打开完整 Web 工作台，前端 `/api` 请求代理到本地 API。
- 展示模式下，`cd web && npm run build` 成功生成 `web/dist`，FastAPI 可以托管静态产物并在单个本地服务中打开工作台。
- 单视频 Mock 任务可以从上传文件或本地路径创建，状态依次进入 `queued`、`running` 和 `completed`/`failed`，SSE 面板实时显示 Agent 事件。
- 批量任务可以从多个上传文件或目录创建，后端同一时间只运行一个任务，前端正确展示排队、运行、完成和失败任务。
- 服务重启后，历史任务列表、公共结果、错误信封和事件摘要可以从本地 JSON 恢复；删除历史任务不会删除原始视频数据。
- `video_finished` 的公共结果展示不混入内部帧区间、完整 Base64、API key、token 或不必要的内部临时路径；运行失败展示 `stage`、`code` 和 `message`。
- JSON、JSONL 和 CSV 导出与 Runner 公共结果字段兼容，CSV 至少包含 video_id、最终状态、时间区间、断裂类型、位置、置信度、轮数、错误阶段、错误码和错误消息。
- 前端在桌面宽屏下呈现参考式三栏控制台；窄窗口下主要内容不重叠，任务列表、日志流和 JSON 区域可滚动，按钮文字不溢出。
- 后端测试通过：任务 API、队列、事件规范化、历史持久化、导出和敏感字段过滤均有覆盖。
- 前端验证通过：`npm run build` 成功，主要页面和交互在 mock API/SSE 下可验证；如引入 Playwright，需覆盖桌面和窄屏截图。
- 项目级验证通过：`python3 -m pytest tests -q`、`python3 scripts/validate_no_oob.py` 和 `git diff --check` 无新增失败；真实本地生成产物缺失导致的既有 skip 可以保留。

## 风险与待确认事项

- [非阻塞] 完整前端会引入 Node.js、前端构建和本地 API 维护成本；本步骤通过本地单用户边界、单 worker 队列和 FastAPI 静态托管控制范围。
- [非阻塞] 当前 runner 是同步执行；本步骤只要求单 worker 顺序运行，不要求运行中取消、暂停恢复或多任务并发。
- [非阻塞] 本地 JSON 历史适合单用户工作台，但不适合并发写入或远程部署；如后续需要多用户或远程访问，应另行修订项目计划并评估数据库和权限。
- [非阻塞] 参考包为构建产物且不是当前项目源码；实现时只吸收布局和视觉语言，所有字段、状态和文案必须以 TensileAgent v9.0 契约为准。

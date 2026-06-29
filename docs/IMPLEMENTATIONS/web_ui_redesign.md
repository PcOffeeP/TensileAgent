# TensileAgent Web 工作台 UI/交互改造实施计划

> 状态：已批准
> 关联项目计划版本：10.0
> 适用范围：`web/` 本地工作台、`agent/web_api.py` 的 Web 适配层、相关 Web/API 测试。
> 不适用范围：`IterativeAgent` 决策规则、模型推理契约、训练流水线、外部视觉服务部署。

## 1. 背景与目标

当前 Web 工作台仍以“上传区 + 近期任务表 + 右侧任务详情”为核心。这个结构无法清楚表达 TensileAgent 的关键价值：对同一个拉伸试验视频执行多轮 `sample_and_infer`，通过候选区间收缩、复核和终止门槛，最终输出 `fracture`、`no_fracture` 或 `unrecognized`。

本次改造目标是把主页面改成“当前分析会话工作台”：

1. 首屏只聚焦上传或输入视频路径，不直接堆历史任务。
2. 创建任务后无需点击任务，主页面自动进入当前任务视图。
3. 分析过程中实时展示 Agent 工具调用、采样区间、模型输出、状态更新和候选区间收敛。
4. 分析完成后在主页面直接显示最终结果和导出入口。
5. 历史任务保留在独立入口，支持回看事件和结果，但不干扰主流程。

这份文档用于指导多个 Agent 分工实施：Gemini 或 UI Agent 可负责前端视觉和组件实现；后端 Agent 需先修复 Web API 契约适配；集成 Agent 负责端到端验证。

## 2. Gemini 草稿评估

Gemini 草稿的方向正确，尤其是：

1. 使用 `ActiveAnalysisWorkspace` 替代主页面任务表。
2. 使用 `AgentProgressTimeline` 按轮次展示事件。
3. 使用 `IntervalConvergenceBar` 表示 `sample_range`、`candidate` 和最终区间。
4. 将历史任务移到次级入口。

但原草稿不足以直接交付实施，主要缺口是：

1. 没有把后端 P1 契约问题列为前端改造前置条件。
2. 没有明确当前 Runner 结果字段是 `RunnerResult{ok,result,error}`，不是旧的 `output/final_output/type`。
3. 没有规定事件归一化、轮次聚合、历史回放的精确定义。
4. 没有区分前端 UI 工作、后端 Web API 工作和 Agent 核心逻辑禁改范围。
5. 验收标准过粗，缺少单元测试、构建、手工流程、脱敏检查和截图验证。

因此本文保留 Gemini 的视觉方向，但补齐工程约束、实施细节和可验收标准。

## 3. 已知前置问题

前端 UI 改造前，后端 Web API 至少需要交付以下兼容修复。若这些修复尚未合入，前端实现必须在 mock fixture 中模拟修复后的事件/结果结构，但不得把错误契约固化进 UI。

### 3.1 RunnerResult 解包

当前 `agent.runner.run_one()` 返回：

```json
{
  "ok": true,
  "result": {
    "video_id": "sample",
    "status": "fracture",
    "time_range": [10.2, 10.8],
    "fracture_type": "韧性断裂",
    "location": "inside_gauge",
    "confidence": 0.91,
    "unrecognized_reason": null
  },
  "error": null
}
```

或：

```json
{
  "ok": false,
  "result": null,
  "error": {
    "stage": "sampling",
    "code": "sampling_error",
    "message": "..."
  }
}
```

后端 Web API 必须：

1. `ok=true` 时把 `result` 原样映射为公开任务结果，保留 `status`、`time_range`、`fracture_type`、`location`、`confidence`、`unrecognized_reason`。
2. `ok=false` 时将任务标记为 `failed`，填充 `task.error`，并通过 SSE 发出 `task_failed`。
3. 不再依赖旧字段 `output`、`final_output`、`type`、`start_time`、`end_time`、`fracture_between` 作为最终公共结果。

### 3.2 事件名适配

Agent 原始事件使用 `event_type`，例如：

```json
{
  "event_type": "sample_and_infer_finished",
  "round": 1,
  "display_round": 2,
  "model_output": {"has_fracture": true},
  "inferred_time_range": [10.1, 10.7]
}
```

Web API 包装层必须统一输出：

```json
{
  "task_id": "...",
  "event": "sample_and_infer_finished",
  "data": {
    "event_type": "sample_and_infer_finished",
    "...": "..."
  },
  "timestamp": "..."
}
```

前端也必须做防御式归一化：

```ts
const eventName = event.data?.event_type ?? event.event;
```

### 3.3 脱敏与公开 DTO

Web API、SSE、历史持久化和导出结果不得泄露：

1. Base64 视频内容。
2. API key、token。
3. 不必要的本地绝对路径，例如 `video_path`、`model_video_path`、临时 clip 路径。

允许 UI 展示的文件信息应限制为：

1. `video_id`。
2. 上传文件名或用户输入路径的 basename。
3. 视频时长、任务状态、创建/开始/完成时间。

如果后端暂未完成公开 DTO，前端不得在页面显著位置展示绝对路径；调试 JSON 面板也应默认折叠，并标记为开发诊断信息。

## 4. 信息架构

### 4.1 主导航

保留当前三类入口，但调整权重：

1. `实验分析`：默认入口，展示上传态或当前任务工作台。
2. `历史记录`：独立页面，负责检索、回放、删除、导出历史任务。
3. `系统配置`：保留现有配置能力。

侧边栏不再显示“最近任务”列表。可以保留轻量状态，例如后端健康、队列长度、当前模型，但历史任务必须通过 `历史记录` 进入。

### 4.2 实验分析页状态

实验分析页有三种主状态：

1. `idle`：无 active task，显示上传/路径输入。
2. `active`：存在 active task，显示当前任务工作台。
3. `finished`：active task 已完成或失败，工作台保留最终结果、轮次轨迹和重新分析入口。

页面不应再依赖右侧 `TaskDetail` 才显示结果。`TaskDetail` 可被移除、降级为历史详情组件，或重构为 `TaskReplayPanel`。

### 4.3 当前任务工作台布局

桌面端建议布局：

```text
+---------------------------------------------------------------------+
| Sidebar | Header: video_id / status / backend / elapsed / actions   |
|         +-------------------------+-----------------------------------+
|         | Video/Input Summary     | Final Result Panel                |
|         | preview, filename       | status, time_range, confidence    |
|         +-------------------------------------------------------------+
|         | Interval Convergence Bar                                    |
|         | total duration + sample ranges + candidate + final marker    |
|         +-------------------------+-----------------------------------+
|         | Agent Progress Timeline | Raw Event Log / Diagnostics       |
|         | RoundTraceCard list     | collapsible, not primary surface  |
+---------------------------------------------------------------------+
```

移动端建议顺序：

1. 状态 header。
2. 最终结果或当前进度。
3. 视频/输入摘要。
4. 区间收敛条。
5. 轮次时间线。
6. 折叠诊断。

## 5. 前端数据契约

### 5.1 Task 类型

前端 `Task` 应支持当前公共结果字段：

```ts
type TaskStatus = "queued" | "running" | "completed" | "failed";

interface FinalResult {
  video_id: string;
  status: "fracture" | "no_fracture" | "unrecognized";
  time_range: [number, number] | null;
  fracture_type: string | null;
  location: "inside_gauge" | "outside_gauge" | "unknown" | null;
  confidence: number | null;
  unrecognized_reason: string | null;
  rounds?: number;
  frame_range?: [number, number] | null;
}

interface Task {
  id: string;
  status: TaskStatus;
  video_id: string;
  video_name?: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: FinalResult | null;
  error: { stage: string; code: string; message: string } | null;
}
```

如果后端仍返回 `video_path`，前端类型可以暂时保留，但 UI 不应默认显示完整路径。

### 5.2 事件类型

前端应定义统一事件结构：

```ts
interface AgentEvent {
  task_id?: string;
  event: string;
  timestamp?: string;
  data?: Record<string, unknown>;
}
```

必须支持以下事件：

1. `task_created`
2. `task_started`
3. `video_started`
4. `round_started`
5. `llm_tool_call`
6. `sample_and_infer_started`
7. `sample_and_infer_finished`
8. `state_updated`
9. `termination_requested`
10. `video_finished`
11. `video_failed`
12. `task_completed`
13. `task_failed`
14. `ping`

未知事件不得导致 UI 崩溃，应进入 Raw Event Log。

最小事件夹具如下，前端 reducer 或等价测试必须覆盖这些形态：

| 输入形态 | 归一化事件名 | 必要处理 |
| --- | --- | --- |
| `{event:"task_started", data:{video_id}}` | `task_started` | 标记任务进入运行中 |
| `{event:"unknown", data:{event_type:"video_started", duration_sec, initial_candidate}}` | `video_started` | 写入 `videoDurationSec` 和 `initialCandidate` |
| `{event:"unknown", data:{event_type:"round_started", round, display_round, state, candidate}}` | `round_started` | 创建/更新 round，记录起始状态和 candidate |
| `{event:"unknown", data:{event_type:"llm_tool_call", tool_name, tool_args, reasoning}}` | `llm_tool_call` | 写入工具调用和 reasoning |
| `{event:"unknown", data:{event_type:"sample_and_infer_started", sample_range}}` | `sample_and_infer_started` | 写入本轮采样区间 |
| `{event:"unknown", data:{event_type:"sample_and_infer_finished", model_output, inferred_time_range, validation_error, round_confidence_level}}` | `sample_and_infer_finished` | 写入模型输出、推断区间、错误和置信度 |
| `{event:"unknown", data:{event_type:"state_updated", previous_state, state, previous_candidate, candidate}}` | `state_updated` | 写入状态转换和 candidate 更新 |
| `{event:"unknown", data:{event_type:"termination_requested", allowed, reason, tool_args}}` | `termination_requested` | 显示终止请求；`allowed=false` 时显示原因 |
| `{event:"unknown", data:{event_type:"video_finished", result}}` | `video_finished` | 写入最终结果 |
| `{event:"unknown", data:{event_type:"video_failed", stage, error}}` | `video_failed` | 写入失败信息 |
| `{event:"task_completed", data:{result}}` | `task_completed` | 与 `video_finished` 合并最终结果 |
| `{event:"task_failed", data:{stage, code, message}}` | `task_failed` | 与 `video_failed` 合并失败信息 |
| `{event:"ping"}` | `ping` | 更新连接状态，不创建 round |

### 5.3 Round 聚合模型

前端 reducer 应把事件归约为：

```ts
interface AnalysisRound {
  round: number;
  displayRound: number;
  stateAtStart?: string;
  candidateAtStart?: [number, number];
  toolCall?: {
    name: "sample_and_infer" | "terminate" | string;
    args: Record<string, unknown>;
    reasoning?: string;
    validationError?: string;
  };
  sampleRange?: [number, number];
  modelOutput?: {
    has_fracture?: boolean | null;
    fracture_between?: [number, number] | null;
    type?: string;
    location?: string | null;
    confidence?: number;
  } | null;
  inferredTimeRange?: [number, number] | null;
  inferredFrameRange?: [number, number] | null;
  validationError?: { code?: string; message?: string; field?: string | null } | null;
  confidenceLevel?: "高" | "中" | "低" | "不可信" | string;
  previousState?: string;
  nextState?: string;
  previousCandidate?: [number, number];
  nextCandidate?: [number, number];
  terminationRequest?: {
    allowed: boolean;
    reason: string;
    args: Record<string, unknown>;
  };
}
```

前端 hook 应输出一个整体分析状态：

```ts
interface AnalysisTrace {
  taskId: string;
  videoDurationSec: number | null;
  initialCandidate: [number, number] | null;
  rounds: AnalysisRound[];
  finalResult: FinalResult | null;
  taskError: { stage?: string; code?: string; message: string } | null;
  connectionState: "connecting" | "open" | "reconnecting" | "closed" | "error";
  rawEvents: AgentEvent[];
}
```

聚合规则：

1. `round_started` 创建或更新对应 round。
2. `llm_tool_call` 写入 tool call；若工具参数校验失败，显示为本轮警告。
3. `sample_and_infer_started` 写入 `sampleRange`。
4. `sample_and_infer_finished` 写入 `modelOutput`、`inferredTimeRange`、`validationError`、`confidenceLevel`。
5. `state_updated` 写入状态转换和 candidate 转换。
6. `termination_requested` 写入终止请求，`allowed=false` 必须明显显示原因。
7. `video_finished/task_completed` 更新最终结果。
8. `video_failed/task_failed` 更新错误结果。
9. `video_started.duration_sec` 是时间轴总时长来源；不得要求 Agent 核心改名为 `total_duration`。
10. `video_started.initial_candidate`、`round_started.candidate`、`state_updated.candidate` 共同构成 candidate 轨迹；时间轴优先展示最新 `state_updated.candidate`。

## 6. 组件拆分

### 6.1 顶层与状态管理

1. `App.tsx`
   - 管理 `currentView`、`activeTaskId`、`tasks`、`health`、`config`。
   - 不再管理 `selectedTask` 右侧抽屉作为主流程。
   - 创建任务后立即设置 `activeTaskId` 并切换到 `analysis`。
   - 切换历史任务时进入历史详情/回放，不复用主分析页的 active task 状态，除非用户明确点击“设为当前查看”。

2. `api.ts`
   - 增加 `replayEvents(taskId)`。
   - 明确 `FinalResult`、`AgentEvent`、`AnalysisRound` 相关类型。
   - `subscribeEvents` 返回 close 函数；组件 unmount 或 active task 切换时必须关闭旧连接。

3. `hooks/useAgentTaskEvents.ts`
   - 负责加载 replay 事件、订阅 SSE、归一化事件、聚合 rounds。
   - 暴露 `events`、`rounds`、`durationSec`、`finalResult`、`error`、`connectionState`。
   - 处理重复事件：以事件顺序为准，允许 replay + SSE 重叠时做轻量去重。

### 6.2 主流程组件

1. `AnalysisView.tsx`
   - 只负责根据 `activeTaskId` 分发到 `UploadPanel` 或 `ActiveAnalysisWorkspace`。
   - 不再展示近期任务表。

2. `UploadPanel.tsx`
   - 支持单视频上传和服务器路径输入。
   - 批量上传本阶段不作为主流程。若保留入口，必须放入折叠的“批处理”次级模式，且不承诺实时轮次可视化。
   - 不删除现有 `/api/tasks/batch` 或 `createBatchTasks` 能力；本计划只要求主工作台默认隐藏多文件入口。
   - 上传前可显示选中文件名、大小、视频预览。

3. `ActiveAnalysisWorkspace.tsx`
   - 当前任务主工作台。
   - 组合 `VideoInputSummary`、`FinalResultPanel`、`IntervalConvergenceBar`、`AgentProgressTimeline`、`RawEventLog`。
   - 提供“分析新视频”“查看历史”“导出 JSON/CSV”操作。

4. `VideoInputSummary.tsx`
   - 显示视频预览、视频名、任务状态、创建/开始/完成时间。
   - 不默认显示绝对路径。

5. `FinalResultPanel.tsx`
   - `fracture`：突出断裂类型、位置、时间区间、置信度。
   - `no_fracture`：突出未发现断裂、置信度、覆盖轮次说明。
   - `unrecognized`：突出不可识别原因和建议查看轮次。
   - `failed`：突出 stage、code、message。

6. `IntervalConvergenceBar.tsx`
   - 基于 `durationSec` 渲染 0 到视频总时长的水平轴。
   - 每轮显示 `sampleRange`，可用浅色条叠加。
   - 当前 `candidate` 用强调色条显示。
   - `inferredTimeRange` 或最终 `time_range` 用 marker 显示。
   - 没有 `durationSec` 时显示文本 fallback，不计算百分比。

7. `AgentProgressTimeline.tsx`
   - 按 `displayRound` 顺序展示 `RoundTraceCard`。
   - 当前运行中的 round 自动展开；旧 round 可折叠。
   - 顶部提供筛选：全部、异常/警告、工具调用、状态更新。

8. `RoundTraceCard.tsx`
   - 单轮信息密度要适中，默认显示：
     - round 编号和状态。
     - tool 名称和采样区间。
     - 模型输出摘要。
     - candidate 变化。
     - 置信度/校验错误/终止拒绝原因。
   - 原始 JSON 放在折叠区。

9. `RawEventLog.tsx`
   - 诊断用途，默认折叠。
   - 显示归一化事件名、时间戳、原始 payload。
   - 不应成为主要用户理解路径。

### 6.3 历史与配置

1. `HistoryView.tsx`
   - 保留搜索、状态筛选、删除。
   - 点击任务进入历史详情页或详情区域，必须加载 `/events/replay`。
   - 历史详情也应复用 `AgentProgressTimeline` 和 `FinalResultPanel`，实现“回放同一分析过程”。

2. `Sidebar.tsx`
   - 移除最近任务列表。
   - 保留任务总数/队列长度/模型摘要。
   - 若需要提示当前 active task，可只显示一个紧凑状态行。

## 7. 后端实施要求

后端 Agent 负责以下文件，前端 Agent 不应绕过这些问题：

1. `agent/web_api.py`
   - 修复 `_normalize_result` 或替换为 `RunnerResult` 解包函数。
   - `ok=false` 时设置 `task.status = failed` 和 `task.error`。
   - `_event_callback_factory` 使用 `event_data.get("event_type") or event_data.get("event")`。
   - 实现递归脱敏函数，覆盖 dict/list 嵌套结构。
   - 任务列表/详情返回公开 DTO，避免不必要绝对路径。
   - `/events/replay` 返回与 SSE 相同的归一化事件结构。

2. Web API 测试
   - 增加 `RunnerResult ok=true` 映射测试。
   - 增加 `RunnerResult ok=false` 失败状态测试。
   - 增加 `event_type` 转发测试。
   - 增加递归脱敏测试。
   - 增加 replay 与 SSE 事件结构一致性测试。

后端不得修改 `IterativeAgent` 状态机规则来迁就 UI。UI 只能消费 Agent 已有过程事件，不能实现第二套决策逻辑。

## 8. 前端实施要求

### 8.1 Gemini/UI Agent 输入约束

如果让 Gemini 生成前端代码，必须给它以下硬约束：

1. 使用现有 React + TypeScript + Tailwind + `lucide-react`，不引入新的 UI 框架。
2. 不创建营销落地页；首屏就是上传和分析工具。
3. 不使用大面积装饰性渐变、孤立装饰球、复杂 hero；整体是研究工具/实验工作台。
4. 不写 Agent 决策逻辑；只做事件归一化、展示和交互。
5. 使用当前公共结果字段 `fracture_type`、`time_range`、`unrecognized_reason`。
6. 对未知事件、缺失字段、连接断开、任务失败都有 UI fallback。
7. 移动端不得出现文本重叠、按钮溢出、时间轴压缩到不可读。

### 8.2 视觉设计要求

1. 视觉语气：克制、专业、实验工具。
2. 主色可沿用当前 `#002FA7`，但不要让页面成为单一蓝色主题；灰、白、蓝、琥珀、绿色、红色用于不同语义。
3. 卡片圆角不超过 8px，避免卡片套卡片。
4. 主工作区信息要有层级：状态和最终结果优先，过程追踪其次，Raw JSON 最后。
5. 所有按钮内文字必须在桌面和移动端完整显示；必要时换行或缩短标签。
6. 图标按钮使用 `lucide-react`，有不直观含义时加 `title`。

## 9. 分阶段实施

### Phase 0：后端契约修复

负责人：后端 Agent。

交付：

1. `RunnerResult` 正确映射为 task result/error。
2. Agent `event_type` 正确成为 SSE 顶层 `event`。
3. 递归脱敏和公开 DTO。
4. Web API 单测覆盖。

验收：

1. `ok=true` 任务在 `/api/tasks/{id}` 中返回 `result.status` 为真实 `fracture/no_fracture/unrecognized`。
2. `ok=false` 任务在 `/api/tasks/{id}` 中返回 `status=failed` 且 `error.stage/code/message` 可见。
3. SSE 中 `round_started`、`sample_and_infer_finished`、`state_updated` 不再是 `unknown`。
4. API 响应和事件 JSONL 不出现 `data:video`、`api_key`、`token`、临时 clip 绝对路径。

### Phase 1：前端数据层

负责人：前端 Agent。

交付：

1. `api.ts` 类型更新。
2. `replayEvents(taskId)`。
3. `useAgentTaskEvents` hook。
4. 事件 normalizer 和 reducer。
5. 纯函数测试或 fixture 验证：raw events -> rounds/final state。

验收：

1. replay 事件和实时 SSE 事件能进入同一个 reducer。
2. active task 切换会关闭旧 EventSource。
3. `event.data.event_type` 和 `event.event` 两种结构都能识别。
4. 缺失 `durationSec` 时 UI 不崩溃。
5. 刷新页面后从 `/events/replay` 恢复 rounds、candidate 轨迹和 final/error 状态。
6. reducer 夹具覆盖 `event:"unknown" + data.event_type`、`ping`、`task_completed`、`task_failed`。

### Phase 2：主页面结构

负责人：前端 Agent 或 Gemini/UI Agent。

交付：

1. `AnalysisView` 改为上传态/工作台态切换。
2. 新建 `UploadPanel`。
3. 新建 `ActiveAnalysisWorkspace`。
4. `App.tsx` 使用 `activeTaskId` 替代主流程 `selectedTask` 抽屉。
5. `Sidebar` 移除最近任务列表。

验收：

1. 首次打开 `实验分析` 只看到上传入口、路径输入、必要模型状态。
2. 创建任务后自动进入当前任务工作台。
3. 主页面没有近期任务表。
4. 不点击历史任务也能看到当前任务状态和事件。

### Phase 3：过程可视化

负责人：Gemini/UI Agent 优先。

交付：

1. `IntervalConvergenceBar`。
2. `AgentProgressTimeline`。
3. `RoundTraceCard`。
4. `RawEventLog`。

验收：

1. 每轮显示 tool call、sample range、model output、confidence、candidate update。
2. `termination_requested.allowed=false` 显示拒绝原因。
3. validation error、infra failure、低置信度有明显但不过度刺眼的状态。
4. 时间轴能表达全局扫描、局部采样、候选区间缩小和最终区间。

### Phase 4：最终结果与历史回放

负责人：前端 Agent。

交付：

1. `FinalResultPanel`。
2. 历史详情复用 timeline/result 组件。
3. 历史任务点击后加载 replay 事件。
4. 导出按钮保留 JSON/CSV。

验收：

1. `fracture` 显示断裂类型、位置、时间区间、置信度。
2. `no_fracture` 显示未断裂结论和覆盖/轮次摘要。
3. `unrecognized` 显示 `unrecognized_reason`。
4. `failed` 显示 stage/code/message。
5. 刷新页面后打开历史任务仍能看到轮次过程。

### Phase 5：响应式和视觉打磨

负责人：Gemini/UI Agent 优先，集成 Agent 复核。

交付：

1. 桌面、窄屏、移动端布局。
2. 空状态、加载态、连接断开态、失败态。
3. 文案统一为中文，必要技术字段保留英文 code。
4. 视觉截图记录。

验收：

1. 1280px、768px、390px 宽度下无文本重叠。
2. 主要操作按钮可点击，标签不溢出。
3. 当前运行 round 自动可见。
4. Raw JSON 默认折叠，不干扰主流程。

## 10. 验证计划

### 10.1 自动验证

前端相关：

```bash
cd web
npx tsc --noEmit
npm run build
```

后端/API 相关：

```bash
python3 -m pytest tests/test_runner.py tests/test_config_util.py -q
```

若新增 Web API 测试，应运行：

```bash
python3 -m pytest tests/test_web_api.py -q
```

全量测试当前存在历史训练流水线遗留导入问题。实施 Agent 不应把 `python3 -m pytest tests -q` 的失败简单归因于本次 UI 改造；但如果本次任务顺手清理测试边界，必须在 PR/总结中单独说明。

### 10.2 手工验证

必须至少完成以下流程：

1. 启动后端和 Vite dev server。
2. 首次进入只显示上传入口。
3. 上传一个 mock 或小视频后自动进入工作台。
4. SSE 事件到达时 timeline 实时追加 round。
5. 时间轴显示 sample/candidate/final 区间。
6. 任务完成后最终结果自动出现。
7. 刷新页面，进入历史记录，打开同一任务，能回放轮次事件。
8. 删除历史任务后，列表和详情状态一致。
9. 打开浏览器 devtools 检查 API/SSE 响应，不出现 Base64、API key、token、不必要临时 clip 绝对路径。
10. 在运行中刷新页面，重新打开该任务后，已发生的 rounds 和 candidate 轨迹不丢失。

### 10.3 视觉验证

实施完成后保存或提交说明以下截图：

1. 初始上传页。
2. 分析运行中，至少 2 个 round。
3. `fracture` 最终结果。
4. `unrecognized` 或 `failed` 状态。
5. 历史回放页。
6. 移动端窄屏截图。

## 11. 验收标准

本计划完成必须同时满足：

1. 主分析页不再直接展示历史任务列表。
2. 创建单个任务后，无需点击任务即可看到实时事件和最终结果。
3. 每轮 `round_started`、`llm_tool_call`、`sample_and_infer_started`、`sample_and_infer_finished`、`state_updated` 可以被归一化和展示。
4. UI 使用 `fracture_type/time_range/unrecognized_reason` 等当前公共结果字段。
5. `RunnerResult ok=false` 不显示为成功完成。
6. 历史任务支持 replay 并展示同样的 round timeline。
7. API/SSE/Raw JSON 不默认暴露敏感内容或不必要内部路径。
8. `cd web && npm run build` 通过。
9. 新增或修改的后端测试通过。
10. 桌面和移动端关键页面无明显布局重叠。

## 12. 不得做的事

1. 不得修改 `IterativeAgent` 的状态机规则来适配 UI。
2. 不得在前端重新判断最终 `fracture/no_fracture/unrecognized`。
3. 不得把历史任务重新堆回主分析页。
4. 不得把 Base64 视频、API key、token 或临时 clip 路径展示给普通用户。
5. 不得引入大型 UI 框架或路由框架，除非另行批准。
6. 不得把训练流水线、`pipeline/` 或 `LlamaFactory/` 重新纳入本仓库 Web 工作台依赖。

## 13. 交付建议

建议分成三个可并行但有依赖顺序的任务：

1. 后端契约修复 Agent：先完成 Phase 0。
2. 前端数据层 Agent：基于后端目标契约或 fixture 完成 Phase 1。
3. Gemini/UI Agent：在 Phase 1 数据模型稳定后完成 Phase 2 到 Phase 5 的视觉和交互实现。

集成顺序必须是：后端契约 -> 前端数据层 -> UI 组件 -> 历史回放 -> 验证截图。

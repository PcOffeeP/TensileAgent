# 意图识别混合改造初步实施计划

> 一句话方案：用户输入先由决策模型输出与 `UserIntent` 同构的 8 字段 JSON，再经代码三层合规校验（安全复核 → pydantic 合法性 → 一致性）；安全复核命中由代码裁决改写为 `action="unsupported"`，其余两层失败或模型异常、JSON 不可解析、`backend=deterministic` 时回退现有正则 `parse_user_intent`。

---

## 1. 目标与范围

### 目标

将 TensileAgent 的**用户意图识别**从当前纯确定性正则改造为：

> **决策模型识别为主 + 代码后置合规校验 + 现有正则兜底**

的混合架构。

模型负责理解用户自然语言的字段需求、语言、详细程度；代码负责三层合规校验：**① 安全复核（命中即裁决改写为 `action="unsupported"`）、② pydantic/Literal 合法性校验、③ 一致性校验**；除安全复核命中外，其余校验失败、模型异常、JSON 不可解析或 `backend=deterministic` 时回退到现有正则，保证行为不劣化。

### 本次范围

- 新增一条**意图识别模型调用路径**（`agent/interaction.py` 内）。
- 新增一份**意图识别 Prompt/JSON 输出契约**（`agent/prompts.py`）。
- 对 `UserIntent.rejection_code` 做唯一 schema 小改：`str|None` → `Literal[5 值]|None`。
- 保留现有 `parse_user_intent` 正则逻辑**原样**，作为合规兜底与回归基线。
- 现有 `runner.py`、`iterative_agent`、视觉推理链路、Web API 下游消费**不改动**。

---

## 2. 非目标

明确不进入本次改造：

| 非目标 | 说明 |
| --- | --- |
| 不修改下游分析流程 | `runner.py:259` `request_evidence=intent.wants_evidence` 等消费点保持不变。 |
| 不修改 `UserIntent` 其余 7 字段 | 只收敛 `rejection_code` 类型，其余字段、默认值、校验器不变。 |
| 不删除正则实现 | `parse_user_intent` 继续存在并承担 100% 兜底。 |
| 不补 `explain_previous` | 该 action 仍为死声明，本次只记录为后续事项，不扩大范围。 |
| 不做端到端架构重构 | 只在 `parse_user_intent` 内部增加模型路径，外部调用接口不变。 |

---

## 3. 背景与现状

### 3.1 当前实现：纯正则意图识别

当前入口为 `agent/interaction.py:21` 的 `parse_user_intent(question)`，逻辑为纯确定性正则：

- **错别字修正**：`断列→断裂`、`段裂→断裂`、`位直→位置`、`类形→类型`。
- **语言检测**（`zh`/`en`）：含字母且无汉字则判英文，否则中文。
- **安全检测**：命中注入/拒绝/矛盾模式直接返回 `action="unsupported"`，并附带对应 `rejection_code`。
  - 注入 → `prompt_injection`
  - 矛盾请求 → `contradictory_intent`
  - 明确拒绝分析 → `analysis_declined`
- **字段识别**：`has_fracture` / `time_range` / `type` / `location` / `confidence` / `visual_evidence`。
- **兜底分类**：通用请求给默认 4 字段 `["has_fracture", "time_range", "type", "location"]`；完全无关文本 → `unsupported_intent`。

`UserIntent` 定义在 `agent/schema.py:426-459`，8 字段 pydantic `BaseModel`，`extra="forbid"`：

```text
action / requested_fields / wants_evidence / wants_confidence
response_detail / language / ambiguity / rejection_code
```

`requested_fields` 含非空、去重校验器；`rejection_code` 当前为 `str|None`。

### 3.2 下游消费

- `agent/runner.py:172` 调用 `parse_user_intent(question)`。
- `runner.py:172-183`：若 `action == "unsupported"`，直接返回失败 envelope，`code` 取 `rejection_code`。
- `runner.py:259`：`request_evidence=intent.wants_evidence` 控制是否进入 Evidence Prompt。
- `runner.py:331`：`project_result(envelope["result"], intent)` 投影最终答案字段。
- `web_api.py:550` 左右通过 `task.response = _sanitize_event_data(runner_result.get("response"))` 透传 `project_result` 返回的错误/结果 envelope。

下游对 `rejection_code`/`ambiguity` 没有按取值分支，只做透传。

### 3.3 TODO 条目

`docs/PROJECT_TODO.md` 第一条「用户需求识别」已记录当前差异：

> 当前实现为纯确定性代码，无模型理解环节；期望设计并验证“模型理解 + 确定性代码校验与兜底”的混合方案。

### 3.4 可复用 LLM 基础设施

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| `BaseAgentLLM` 抽象 | `agent/llm.py:41` | 统一 LLM 后端接口。 |
| `chat_with_tools` | `agent/llm.py:45`（抽象）/ `llm.py:154` 等实现 | 对话调用。意图识别可复用其普通 `chat` 或改造成 tool-call。 |
| `RemoteAPIClient` | `agent/llm.py:309` | 远程 OpenAI 兼容 API。 |
| `LocalClient` | `agent/llm.py:375` | 本地 Ollama/vLLM。 |
| `AgentLLMFactory.create` | `agent/llm.py:444-448` | 根据 `agent.backend` 创建对应客户端。 |
| 后端枚举 | `agent/llm.py:471`、`agent/llm.py:548-555` | 支持 `local` / `remote` / `deterministic`。 |
| `TransportTraceRecorder` | `agent/llm_trace.py:85` | 决策模型调用落盘，可复用记录意图识别调用。 |
| 配置入口 | `agent/config.yaml` | `agent.backend`、`temperature: 0.2` 等。 |

---

## 4. 推荐架构

### 4.1 运行时流水线

```text
用户问题(question)
       │
       ▼
┌─────────────────────┐
│  ① 决策模型识别路径   │  ← 新增：调用意图识别模型，输出 JSON
│  （deterministic 后端跳过） │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│  ② 代码后置三层校验（按优先级执行）            │
│  ②-1 安全复核：命中 → 裁决改写为 unsupported     │
│  ②-2 pydantic 合法性：extra=forbid + Literal 枚举 │
│  ②-3 一致性：字段间自相矛盾                     │
└──────────┬──────────────────────────────────┘
           │ 通过
           ▼
     返回 UserIntent
           │
           ▼  ②-2/②-3 失败 或 ① 失败 或 deterministic
┌─────────────────────┐
│  ③ 回退正则 parse_user_intent │  ← 现状逻辑，行为不变
└─────────────────────┘
```

### 4.2 冲突原则

> **冲突时代码赢。**

模型若判 `analyze_video`，但安全正则命中注入/拒绝/矛盾，代码否决并改写为 `action="unsupported"`，`rejection_code` 由代码确定。

### 4.3 6 种运行时情形

| 情形 | 模型输出 | 代码校验 | 最终结果 | 说明 |
| --- | --- | --- | --- | --- |
| ① 模型正常识别通过 | 合法 8 字段，无安全/一致性问题 | 全通过 | 模型识别结果 | 主路径。 |
| ② 模型判 unsupported，代码确认 | `action="unsupported"` | 安全/合法/一致 | 模型识别结果 | 如模型正确识别无关问题。 |
| ③ 模型误判安全输入 | `action="analyze_video"` | 安全正则命中 | 代码改写为 unsupported，**不回退** | **冲突时代码赢**，命中即裁决。 |
| ④ 模型输出格式坏 / pydantic 失败 | JSON 不可解析或字段越界 | 失败 | 回退正则 | 兜底。 |
| ⑤ 模型超时 / 异常 | 无输出或抛异常 | 失败 | 回退正则 | 兜底。 |
| ⑥ `deterministic` 后端 | 不调用模型 | — | 直接正则 | 行为逐字节一致。 |

---

## 5. 模型输出契约

### 5.1 模型必须输出与 `UserIntent` 同构的 8 字段 JSON

pydantic 的 `extra="forbid"` 意味着模型**不能多字段**；`Literal` 字段意味着**取值必须在白名单内**。二者共同构成合法性第一道闸。

| 字段 | 类型 | 允许取值 / 默认值 | 谁主导 | 代码校验规则 |
| --- | --- | --- | --- | --- |
| `action` | `Literal` | `"analyze_video"` / `"explain_previous"` / `"unsupported"`；默认 `"analyze_video"` | 模型理解，但代码可否决 | `explain_previous` 本次按 unsupported 处理；安全命中时代码改写为 unsupported。 |
| `requested_fields` | `list[Literal[6 值]]` | `has_fracture/time_range/type/location/confidence/visual_evidence`；默认 `["has_fracture"]` | 模型主导 | 非空、去重（pydantic 校验器）；越界字段导致校验失败。 |
| `wants_evidence` | `bool` | 默认 `False` | 模型主导 | 为 `True` 时一致性要求 `requested_fields` 含 `visual_evidence`。 |
| `wants_confidence` | `bool` | 默认 `False` | 模型主导 | 为 `True` 时一致性要求 `requested_fields` 含 `confidence`。 |
| `response_detail` | `Literal` | `"concise"` / `"detailed"`；默认 `"concise"` | 模型主导 | `detailed` 不应与极窄字段需求冲突（作为一致性提示，不强制阻塞）。 |
| `language` | `Literal` | `"zh"` / `"en"`；默认 `"zh"` | 模型主导 | 必须命中二值之一。 |
| `ambiguity` | `str \| None` | 默认 `None` | 代码主导 | 当 `action="unsupported"` 时由代码按 `rejection_code` 填入固定中文文案。 |
| `rejection_code` | `Literal[5 值] \| None` | 默认 `None` | 代码主导 | 模型可提议；`out_of_scope` 采纳规则见下方确定规则。 |

> **pydantic 校验失败即视为“模型输出不合法”，直接触发正则兜底。** 不在代码里修补模型错误字段。

**`rejection_code` / `out_of_scope` 确定规则**

- 代码侧不主动推导 `out_of_scope`，没有确定性规则可依；仅对模型输出做复核。
- 仅当模型输出 `action="unsupported"` 且提议 `rejection_code="out_of_scope"`，并且安全复核与一致性校验均通过时，代码采纳该提议并填入 §5.2 固定文案。
- 模型未提议 `out_of_scope` 时，代码不会自行产出该取值。
- 若模型给出无法确认的其他 `unsupported` 理由，按既有规则回落到 `unsupported_intent`。

### 5.2 `rejection_code` 5 值 × 场景 × 固定文案

| 取值 | 触发场景 | 固定文案（中文，用户可见） | 主导方 |
| --- | --- | --- | --- |
| `prompt_injection` | 请求包含改变系统或视觉协议、越狱、要求把原话传给视觉模型等 | 请求包含改变系统或视觉协议的指令，已在推理前拒绝 | 代码 |
| `contradictory_intent` | 请求同时要求分析与不分析 | 请求同时要求分析与不分析 | 代码 |
| `analysis_declined` | 用户明确要求不执行视频分析 | 用户明确要求不执行视频分析 | 代码 |
| `unsupported_intent` | 完全无关文本，未识别到拉伸试验视频分析需求 | 未识别到拉伸试验视频分析需求 | 代码 |
| `out_of_scope` | 与拉伸试验场景相关，但超出当前 Agent 能力范围（如“这是什么材料？”“拉伸机/试样位置放对了吗？”） | 该问题超出当前分析能力范围。当前支持：断裂检测、断裂时间定位、断口类型与位置分析、置信度与图像证据。请围绕拉伸试验视频的分析需求提问。 | 代码 |

`out_of_scope` 与 `unsupported_intent` 的核心区别：前者**与场景相关但能力未覆盖**，后者**与场景无关**。

### 5.3 schema 唯一改动说明

```python
# 当前
rejection_code: str | None = None

# 改造后
rejection_code: Literal[
    "prompt_injection",
    "contradictory_intent",
    "analysis_declined",
    "unsupported_intent",
    "out_of_scope",
] | None = None
```

仅此一处改动。`UserIntent` 其余字段、默认值、校验器、下游消费方式均不变。这样 pydantic 会直接把非法 `rejection_code` 值当作校验错误抛出，自然触发兜底。

---

## 6. 代码后置校验三层规则详述

模型输出进入代码后置三层校验，按优先级执行。

### 6.1 第一层：安全复核（现有安全正则照跑）

安全复核在模型识别之后、结果返回之前强制执行，**优先级最高**。命中即由代码**裁决**改写为 `action="unsupported"` 并写入对应 `rejection_code`，**不回退**正则；未命中才进入后续两层。

**裁决与回退规则（全文统一口径）**

- 三层校验 = ① 安全复核 ② pydantic 合法性（类型 / 枚举 / `extra="forbid"`） ③ 一致性（字段间自相矛盾）。
- 安全复核命中 → 代码**直接改写**为 `unsupported`（这是裁决，不是回退，不触发正则兜底）。
- pydantic 校验失败、一致性校验失败、模型超时 / 异常 / JSON 不可解析、`backend=deterministic` → 回退现有正则 `parse_user_intent`。
- 三层均通过（含安全复核未命中）→ 返回模型识别结果。

- **注入检测**：命中 `prompt_injection` 模式 → 改写 `action="unsupported"`，`rejection_code="prompt_injection"`。
- **矛盾检测**：同时包含分析与拒绝分析信号 → 改写为 `contradictory_intent`。
- **拒绝检测**：明确拒绝分析 → 改写为 `analysis_declined`。
- 即使模型已判 `unsupported`，也重新检查并校正 `rejection_code`，确保文案统一。

### 6.2 第二层：合法性（pydantic + 枚举越界）

由 `UserIntent.model_validate_json(...)` 或 `UserIntent(**data)` 承担：

- `extra="forbid"`：多字段直接失败。
- `Literal` 字段越界：直接失败。
- `requested_fields` 非空、去重校验器：失败。
- `rejection_code` 收敛为 `Literal[5 值]|None`：非法取值直接失败。

### 6.3 第三层：一致性（自相矛盾输出）

代码根据业务规则检查字段间一致性。目前明确一条，其他按相同原则扩展：

- **示例规则**：若 `wants_evidence=True`，则 `requested_fields` 必须包含 `"visual_evidence"`；否则视为模型输出自相矛盾，校验失败并回退正则。
- **同类规则**：若 `wants_confidence=True`，则 `requested_fields` 应包含 `"confidence"`。
- **范围规则**：`out_of_scope` 不由代码主动推导。仅当模型已提议 `action="unsupported"` + `rejection_code="out_of_scope"`，且安全复核与一致性校验均通过时，代码采纳该提议并填入 §5.2 固定文案；否则不产出 `out_of_scope`。

一致性失败**不回写模型输出**，而是视为该次模型调用不可靠，回退到正则。

---

## 7. 组件与职责

| 文件 | 改动性质 | 职责 |
| --- | --- | --- |
| `agent/interaction.py` | **新增模型路径 + 保留正则** | 在 `parse_user_intent` 内新增模型调用、三层校验、兜底接线；正则原样保留。 |
| `agent/prompts.py` | **新增** | 新增意图识别 Prompt 与 JSON 输出契约说明。 |
| `agent/llm.py` | **复用，不改** | 复用 `BaseAgentLLM`、`RemoteAPIClient`/`LocalClient`、`AgentLLMFactory.create` 创建客户端。 |
| `agent/schema.py` | **小改** | 仅将 `UserIntent.rejection_code` 从 `str\|None` 收敛为 `Literal[5 值]\|None`。 |
| `agent/runner.py` | **不改** | 继续调用 `parse_user_intent(question)`，消费 `wants_evidence`，调用 `project_result`。 |
| `agent/iterative_agent.py` | **不改** | 下游迭代流程不变。 |
| `agent/web_api.py` | **不改** | 继续通过 `response` envelope 透传结果。 |
| `agent/config.yaml` | **可能新增配置项（可选）** | 可考虑加入意图识别超时阈值；当前复用 `agent.backend`、`temperature: 0.2`。本方案**不引入模型识别路径的启停开关**；`intent_timeout_seconds` 仅为模型调用超时阈值配置，是否入 `config.yaml` 留待 P3 决定。 |
| `agent/llm_trace.py` | **可能复用** | 是否将意图识别调用记入 trace，见开放问题。 |
| `tests/test_interaction.py` | **新增测试** | 保留现有用例，新增模型路径 mock 测试。 |
| `tests/test_v2_mvp.py` | **不改** | 现有安全类 rejection 测试必须继续全绿。 |
| `docs/PROJECT_TODO.md` | **更新状态** | P5 更新「用户需求识别」条目状态。 |

---

## 8. 失败处理与边界情况

| 场景 | 处理策略 |
| --- | --- |
| **模型超时/限流** | 捕获异常，直接回退正则；不阻塞 Runner。 |
| **模型输出被截断** | JSON 解析失败 → 回退正则。 |
| **JSON 可解析但字段越界** | pydantic `ValidationError` → 回退正则。 |
| **模型误判注入为正常问题** | 安全正则复核命中 → 代码裁决改写为 `action="unsupported"`，**不回退正则**。 |
| **代码安全正则误伤正常问题** | 因安全正则优先级最高，结果会被拒绝；后续可通过微调 Prompt 和补充白名单缓解，但本次不引入模型覆盖安全正则的机制。 |
| **`agent.backend == deterministic`** | 不调用模型，直接走正则；行为与现状逐字节一致。 |
| **中英混杂输入** | 语言字段由模型主导，但仍受 `Literal["zh","en"]` 限制；默认可保守取 `"zh"`。 |
| **空问题 / None** | 与现状一致：正则兜底会当作通用请求处理。 |
| **模型输出 `explain_previous`** | 代码层按 unsupported 处理；本次不消费该 action。 |

---

## 9. 测试策略

### 9.1 基线：现有测试必须全绿

- `tests/test_interaction.py`：现有正则用例全部保留并继续通过。
- `tests/test_v2_mvp.py:167-170` `test_unsafe_intents_stop_before_inference`：4 条安全类 rejection 用例必须继续通过（对应 `parametrize` 位于 158-165 行）。

### 9.2 新增 mock 测试清单（`tests/test_interaction.py` 中追加）

| # | 测试目标 | 构造方式 |
| --- | --- | --- |
| 1 | 合法模型输出直接通过 | mock LLM 返回完整合法 JSON，校验返回字段。 |
| 2 | 非法字段触发兜底 | mock 返回越界 `requested_fields`，断言走到正则结果。 |
| 3 | 不可解析 JSON 触发兜底 | mock 返回截断/非 JSON，断言回退正则。 |
| 4 | 模型超时触发兜底 | mock `chat_with_tools` 抛 `TimeoutError`，断言回退正则。 |
| 5 | 模型误判注入必须被代码拦下 | mock 返回 `action="analyze_video"`，但问题含注入关键词，断言最终 `action="unsupported"` 且 `rejection_code="prompt_injection"`。 |
| 6 | 模型提议 `out_of_scope` 被采纳 | mock 返回 `action="unsupported"` 且提议 `rejection_code="out_of_scope"`（安全/一致性均通过），断言代码采纳并填入 §5.2 固定文案。 |
| 7 | 模型未提议 `out_of_scope` 时代码不自行产出 | mock 返回 `action="unsupported"` 但未提议 `out_of_scope`（如理由无法确认），断言最终不出现 `rejection_code="out_of_scope"`，按既有规则回落到 `unsupported_intent`。 |
| 8 | 一致性矛盾输出触发兜底 | mock 返回 `wants_evidence=True` 但 `requested_fields` 不含 `"visual_evidence"`，断言回退正则。 |
| 9 | `deterministic` 后端行为逐字节一致 | 配置 `agent.backend=deterministic`，断言输出与当前正则完全相同。 |
| 10 | 5 种 `rejection_code` 契约覆盖 | 每个取值至少一个断言点。 |

### 9.3 真实模型冒烟（可选手动）

- 使用 `local`/`remote` 后端，对 10-15 条典型中英文问题进行冒烟，人工检查输出字段。
- 不归入 CI，作为合并前可选验证。

---

## 10. 实施步骤分期

### P1：意图识别 Prompt + JSON 输出契约

- 在 `agent/prompts.py` 新增意图识别 Prompt 与模型输出 JSON 样例。
- Prompt 要求：输出严格 8 字段 JSON，不得自由生成 `ambiguity` 文案，`rejection_code` 可提议但代码最终确定。
- 验收：Prompt 文本经过走读，包含 5 种 `rejection_code` 示例与字段说明。

### P2：`UserIntent` schema 小改

- `agent/schema.py:426-459` 中仅修改 `rejection_code` 为 `Literal[5 值]|None`。
- 验收：schema 可成功导入；非法 `rejection_code` 触发 `ValidationError`。

### P3：`interaction.py` 模型识别路径 + 三层校验 + 兜底接线

- 在 `parse_user_intent` 内新增：
  1. 读取配置判断 backend；
  2. `deterministic` 直接返回正则结果；
  3. 其他 backend 调用模型；
  4. pydantic 合法性校验（三层第二层）；
  5. 安全复核（命中即裁决改写，不回退）；
  6. 一致性校验；
  7. pydantic / 一致性 / 模型异常 / JSON 不可解析 → 回退正则。
- 保留现有正则函数体不变，作为独立函数或内部兜底分支。
- 验收：所有新增测试通过；现有测试全绿。

### P4：测试补齐

- 完成 9.2 中的新增 mock 测试。
- 验收：`pytest tests/test_interaction.py tests/test_v2_mvp.py::test_unsafe_intents_stop_before_inference` 全绿。

### P5：更新 `docs/PROJECT_TODO.md`

- 将「用户需求识别」从「待处理」移入「已解决」或更新为“模型+代码混合方案已落地，正则兜底保留”。
- 验收：TODO 文件状态与实现一致。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| **输出不稳定** | 模型偶发越界字段、格式错误 | `temperature: 0.2` 已较低；Prompt 明确 JSON schema；pydantic `extra="forbid"` + Literal 拦截；正则兜底保证不阻塞。 |
| **延迟增加** | 多一次决策模型网络/本地调用 | Prompt 保持轻量；模型调用与后续视频分析可视为串行但只增加一次；`deterministic` 后端直接跳过。 |
| **离线环境** | 无远程网络或本地模型未启动 | 已支持 `local` backend；`deterministic` 后端直接走正则。 |
| **安全回归** | 模型绕过安全规则 | **安全正则在代码层强制复核**，模型判 analyze_video 仍可被代码否决；安全类测试必须全绿。 |
| **维护两套路径** | 代码复杂度增加 | 正则路径作为兜底与基线不删除；模型路径与正则路径通过统一 `UserIntent` 接口对外隔离。 |

---

## 12. 开放问题（≤4 个，不阻塞 P1）

1. **意图识别调用是否记入 `llm_trace`**：是否复用 `agent/llm_trace.py:85` 的 `TransportTraceRecorder` 将意图识别请求落盘？不影响 P1 Prompt 设计。
2. **模型调用超时阈值取值与是否入 `config.yaml`**：建议新增 `agent.intent_timeout_seconds`，默认 5-10 秒，是否接受？本方案**不引入模型识别路径的启停开关**；`intent_timeout_seconds` 仅为模型调用超时阈值配置，是否入 `config.yaml` 留待 P3 决定。
3. **~~`out_of_scope` 文案定稿~~ 已完成**：§5.2 固定文案已定稿，无需再跟踪。
4. **`out_of_scope` 是否需要在 `runner.py` / `web_api.py` 层有区别于 `unsupported_intent` 的展示**：当前下游对 `rejection_code` 只做透传，预计不需要特殊分支，但需确认。

---

## 13. 验收标准

改造完成后，以下可验证条件必须满足：

- [ ] `pytest tests/test_interaction.py` 全绿（含新增 mock 测试）。
- [ ] `pytest tests/test_v2_mvp.py::test_unsafe_intents_stop_before_inference` 通过。
- [ ] 配置 `agent.backend=deterministic` 时，`parse_user_intent` 输出与改造前逐字节一致。
- [ ] 5 种 `rejection_code`（`prompt_injection` / `contradictory_intent` / `analysis_declined` / `unsupported_intent` / `out_of_scope`）均有契约测试覆盖。
- [ ] 模型误判安全输入时，代码层能够拦截并改写为对应 `rejection_code`。
- [ ] 模型输出非法字段 / JSON 不可解析 / 超时时，能回退到正则并给出合理结果。
- [ ] `docs/PROJECT_TODO.md` 中「用户需求识别」条目状态已更新。

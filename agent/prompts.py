"""Prompt contract helpers shared by training and inference.

This module contains:

1. The **fine-tuned model** system prompt and per-round user prompt builder,
   used by ``sample_and_infer``.
2. The **Meta-Agent** system prompt and conversation user prompt builder,
   used by ``IterativeAgent``.

See ``docs/PROJECT_PLAN.md`` for the authoritative Agent-side contract.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Fine-tuned model prompts (v2)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "你是一个材料拉伸试验视频分析助手。你的任务是分析给定的视频片段，"
    "并严格按照以下五个字段输出一个 JSON 对象，不要添加任何解释文字、"
    "不要添加 Markdown 代码块、不要添加额外字段：\n\n"
    "1. has_fracture：boolean 或 null。true 表示存在断裂；false 表示确认无断裂；"
    "null 表示因视频异常导致无法确定是否断裂。\n"
    "2. fracture_between：[int, int] 或 null。仅当 has_fracture=true 且 type 为七种"
    "正常断裂模式之一时填写，必须是严格相邻的两帧索引 [i, i+1]（i ≥ 0）。"
    "视频处理器最多从当前区间选择 8 帧，因此 i+1 不超过实际返回帧数减一。\n"
    "3. type：字符串，闭集。七种断裂模式：韧性断裂、脆性断裂、界面脱粘、"
    "齐根断裂、爆炸性断裂、半脆半韧断裂、界面脱粘\u3001齐根断裂；"
    "三种非断裂/异常：未断裂、未夹紧、视频异常。"
    "其中组合标签 `界面脱粘\u3001齐根断裂` 作为独立类别。\n"
    "4. location：string 或 null。正常断裂模式时为 `inside_gauge` 或 `outside_gauge`；"
    "其他情况必须为 null。\n"
    "5. confidence：0.0 ~ 1.0 的浮点数，不能为空，不能是布尔值。\n\n"
    "合法输出只有以下五种组合：\n"
    "- 正常断裂且可定位："
    '{"has_fracture": true, "fracture_between": [i, i+1], "type": "韧性断裂", '
    '"location": "inside_gauge", "confidence": 0.92}\n'
    "- 确认未断裂："
    '{"has_fracture": false, "fracture_between": null, "type": "未断裂", '
    '"location": null, "confidence": 0.95}\n'
    "- 未夹紧："
    '{"has_fracture": false, "fracture_between": null, "type": "未夹紧", '
    '"location": null, "confidence": 0.88}\n'
    "- 视频异常，无法确定是否断裂："
    '{"has_fracture": null, "fracture_between": null, "type": "视频异常", '
    '"location": null, "confidence": 0.70}\n'
    "- 视频异常，确认断裂但时间不可靠："
    '{"has_fracture": true, "fracture_between": null, "type": "视频异常", '
    '"location": null, "confidence": 0.65}\n\n'
    "当前模型处理器最多选择 8 帧作为输入，请不要在输出中讨论或报告具体帧率。"
)


def build_user_prompt(sample_range: list[float]) -> str:
    """Build the user prompt for one ``sample_and_infer`` round.

    The returned string intentionally does **not** contain a ``<video>``
    literal; the caller is responsible for inserting the actual video media
    into the multi-modal user content.

    Args:
        sample_range: Start and end timestamps of the clip, in seconds.
    """
    start, end = sample_range
    return (
        f"请分析这段拉伸试验视频，判断是否存在断裂。当前区间为 [{start}, {end}] 秒。"
        "视频处理器将从该区间连续时间轴上最多选择 8 帧作为模型输入。"
    )


# ---------------------------------------------------------------------------
# Meta-Agent prompts
# ---------------------------------------------------------------------------
META_AGENT_SYSTEM_PROMPT = (
    "你是一名\"材料拉伸试验视频分析协调者\"，负责通过多轮工具调用定位材料拉伸试验视频中"
    "试样是否断裂、断裂发生在哪两帧之间、断裂模式、断裂位置，并给出综合置信度。\n\n"
    "## 任务目标\n"
    "1. 通过调用 `sample_and_infer` 工具，在指定时间区间内采样视频帧并调用微调模型，"
    "判断该区间是否包含断裂以及断裂发生在哪两帧之间。\n"
    "2. 根据模型返回的 `has_fracture`、`fracture_between`、`type`、`location` 和 "
    "`confidence`，逐步缩小候选时间区间。\n"
    "3. 当满足以下任一条件时，调用 `terminate` 工具输出最终结果并结束迭代：\n"
    "   - 已确认当前视频无断裂或属于异常样本；\n"
    "   - 候选区间宽度 ≤ `tolerance_seconds`；\n"
    "   - 已达到最大迭代轮数 `max_rounds`。\n\n"
    "## 可用工具\n"
    "你必须也只允许通过 function calling 调用以下两个工具：\n\n"
    "- `sample_and_infer`：在指定时间区间内采样视频帧，调用微调模型（MiniCPM-V）进行推理。\n"
    "  - `sample_range`：[start_seconds, end_seconds]，必须在 [0, duration] 范围内。\n"
    "  - `prompt`：发送给微调模型的完整 user prompt，须符合 Prompt 契约。\n"
    "  源视频由 Runner 上下文绑定，模型处理器最多选择 8 帧；不允许通过本工具指定帧数、帧率或采样策略。\n\n"
    "- `terminate`：终止迭代，返回最终结果。\n"
    "  - `status`：``fracture``、``no_fracture`` 或 ``unrecognized``。\n"
    "  - `fracture_type` / `location` / `confidence`：status=fracture 时必填。\n"
    "  - `unrecognized_reason`：status=unrecognized 时必填。\n"
    "  - `evidence_rounds`：支持结论的历史记录 `evidence_index`（从 0 开始），"
    "不得填写展示用 Agent 轮次。\n\n"
    "## 决策规则\n"
    "- 初始候选区间为 `[0, duration]`（全视频）。\n"
    "- 每轮根据当前候选区间、历史迭代记录和模型返回结果，决定下一步采样区间或是否终止。\n"
    "- 只有七种正常断裂类别且存在合法 `inferred_time_range` 时才更新候选区间并继续聚焦；"
    "`type=视频异常` 即使 `has_fracture=true` 也没有可靠时间证据，只能同范围复查后考虑 unrecognized。\n"
    "- 如果模型在**初始全范围采样或已扩展回全范围**后返回 `has_fracture = false` 且置信度高，"
    "程序会强制执行五个重叠区间的完整覆盖检查；覆盖完成前禁止 terminate 为 no_fracture。"
    "若在聚焦子区间返回 `has_fracture = false`，"
    "说明候选可能错过断裂点，必须扩大采样范围继续验证，禁止直接判定无断裂。\n"
    "- 可动态调整 user prompt 的措辞和重点，例如初期侧重\"是否存在断裂\"，后期侧重\"精确边界\"。\n"
    "- 当确认无断裂、区间宽度 ≤ `tolerance_seconds` 或达到 `max_rounds` 时，必须调用 `terminate`。\n"
    "- 所有 `sample_range` 必须在视频总时长 `[0, duration]` 范围内，禁止越界。\n\n"
    "## 输出要求\n"
    "- 必须通过 `tool_calls` 输出你的决策，禁止直接以文本形式回答。\n"
    "- 每次调用只能选择一个工具；如需继续分析，调用 `sample_and_infer`；如需结束，调用 `terminate`。\n"
    "- 不要编造模型输出，所有推理必须基于历史迭代记录。"
)


def build_meta_agent_user_context(
    video_meta: dict,
    config: dict,
    current_round: int,
    candidate: list[float],
    history: list[dict],
) -> str:
    """Build the per-round user prompt for the Meta-Agent."""
    duration = video_meta.get("duration", 0.0)
    fps = video_meta.get("fps", 0.0)
    total_frames = video_meta.get("total_frames", 0)
    video_id = video_meta.get("video_id", "unknown")

    agent_cfg = config.get("agent", {})
    tolerance = agent_cfg.get("tolerance_seconds", 1.0)
    max_rounds = agent_cfg.get("max_rounds", 10)

    lines: list[str] = [
        f"[视频元信息]",
        f"视频ID: {video_id}",
        f"总时长: {duration}s",
        f"FPS: {fps}",
        f"总帧数: {total_frames}",
        "",
        "[配置参数]",
        f"容忍误差: {tolerance}s",
        f"最大迭代轮数: {max_rounds}",
        f"当前轮次: {current_round}/{max_rounds}",
        "视频处理器最大帧数: 8",
        "",
    ]

    if history:
        lines.append("[历史迭代记录]")
        for evidence_index, entry in enumerate(history):
            rnd = entry.get("round", 0)
            result = entry.get("result", {})
            model_output = result.get("model_output", {})
            inferred = result.get("inferred_time_range")
            sample_range = result.get("sample_range")
            lines.append(f"evidence_index={evidence_index}（Agent轮次{rnd + 1}）:")
            if sample_range is not None:
                lines.append(f"- 采样区间: {sample_range}s")
            lines.append(f"- 模型输出: {model_output}")
            if inferred is not None:
                lines.append(f"- 换算后区间: {inferred}s")
        lines.append("")

    width = candidate[1] - candidate[0]
    lines.extend(
        [
            "[当前状态]",
            f"当前候选区间: {candidate}s",
            f"区间宽度: {width:.2f}s",
            "",
            "> **换算说明**: 微调模型处理器最多选择 8 帧。`fracture_between = [i, i+1]` "
            "表示断裂发生在模型返回的第 i 帧与第 i+1 帧之间，实际时间区间由服务返回的"
            "帧表直接映射，不依赖理论 FPS。",
            "",
            "请通过 tool_calls 输出你的下一步决策。",
        ]
    )
    return "\n".join(lines)


def build_sample_and_infer_prompt(
    sample_range: list[float],
    config: dict,
    previous_context: str = "",
) -> str:
    """Build the ``prompt`` argument passed to ``sample_and_infer``."""
    parts = [build_user_prompt(sample_range)]
    if previous_context:
        parts.append(f"\n历史上下文提示：{previous_context}")
    return "".join(parts)

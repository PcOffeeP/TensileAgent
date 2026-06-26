"""Shared agent/model interface contract package."""

from __future__ import annotations

from agent.inference import InferenceClient, LlamaFactoryInferenceClient, MockInferenceClient
from agent.iterative_agent import IterativeAgent, TOOLS_SCHEMA
from agent.llm import AgentLLMFactory, BaseAgentLLM, LocalClient, RemoteAPIClient
from agent.parser import ResultParser
from agent.prompts import (
    META_AGENT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_meta_agent_user_context,
    build_sample_and_infer_prompt,
    build_user_prompt,
)
from agent.sampling import (
    ClipBuildResult,
    FfmpegVideoClipBuilder,
    VideoClipBuilder,
    fracture_between_to_frame_range,
    fracture_between_to_time_range,
)
from agent.schema import (
    FinalOutput,
    FractureType,
    LocationType,
    ModelOutput,
    SampleAndInferResult,
    ToolSampleAndInfer,
    ToolTerminate,
)


__version__ = "0.1.0"

__all__ = [
    "AgentLLMFactory",
    "BaseAgentLLM",
    "ClipBuildResult",
    "FfmpegVideoClipBuilder",
    "FinalOutput",
    "FractureType",
    "InferenceClient",
    "IterativeAgent",
    "LocalClient",
    "LlamaFactoryInferenceClient",
    "LocationType",
    "META_AGENT_SYSTEM_PROMPT",
    "MockInferenceClient",
    "ModelOutput",
    "RemoteAPIClient",
    "ResultParser",
    "SampleAndInferResult",
    "SYSTEM_PROMPT",
    "ToolSampleAndInfer",
    "ToolTerminate",
    "TOOLS_SCHEMA",
    "VideoClipBuilder",
    "build_meta_agent_user_context",
    "build_sample_and_infer_prompt",
    "build_user_prompt",
    "fracture_between_to_frame_range",
    "fracture_between_to_time_range",
]

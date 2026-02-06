"""Preset prompt definitions for batch LLM operations."""

from ambuda.utils.llm_structuring import DEFAULT_STRUCTURING_PROMPT

PRESET_PROMPTS = {
    "structuring": {
        "label": "LLM Structuring (XML tags)",
        "template": DEFAULT_STRUCTURING_PROMPT,
    },
}

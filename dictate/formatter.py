"""Compatibility shim — the implementation moved to dictate_core.formatter.

Stage-2 LLM path: when enabled, transcript (+ optional context/audio) leave
the Mac — privacy notes live on the dictate_core module.
"""
from dictate_core.formatter import *  # noqa: F401,F403
from dictate_core.formatter import (  # noqa: F401
    CONTEXT_LABELS, SYSTEM_TEMPLATE, Formatter, render_context_block,
)

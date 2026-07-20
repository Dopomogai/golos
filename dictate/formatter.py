"""Compatibility shim — the implementation moved to dictate_core.formatter."""
from dictate_core.formatter import *  # noqa: F401,F403
from dictate_core.formatter import (  # noqa: F401
    CONTEXT_LABELS, SYSTEM_TEMPLATE, Formatter, render_context_block,
)

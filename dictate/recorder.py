"""Compatibility shim — the implementation moved to dictate_core.recorder.

App code keeps `from .recorder import Recorder`; threading rules live in
the dictate_core module docstring (start may be main-thread; stop/abort not).
"""
from dictate_core.recorder import *  # noqa: F401,F403
from dictate_core.recorder import SAMPLE_RATE, Recorder  # noqa: F401

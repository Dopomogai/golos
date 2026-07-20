"""golos (package name: dictate) — macOS push-to-talk dictation.

Hold a hotkey to capture mic audio, run STT + optional LLM formatting, and
insert text into the frontmost app. Mutable runtime state lives in ~/.golos/;
UI/AppKit code is in this package, the UI-free pipeline in dictate_core.
"""

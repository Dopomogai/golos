#!/usr/bin/env python3
"""Regression guard: does the formatter transcribe questions instead of
answering them — and (with --mode answer) does answer mode behave?

Sends real chat calls with the CURRENT default template and the model from
~/.golos/config.toml, plus a context whose visible_text is an assistant-style
explanation of the cue system.

Run: .venv/bin/python scripts/test_formatter_behavior.py [--mode transcribe|answer]
Default (transcribe): one call — PASS = cleaned question, not an answer.
--mode answer: four calls — PASS = answers the answerable question with "2.5",
transcribes the unanswerable one, transcribes ordinary dictation, and
answer_questions=false still transcribes the question.
Exit 0 = PASS, 1 = FAIL.
"""

import sys
import tomllib
from pathlib import Path

TRANSCRIPT = ('explain to me how this works so I can verify that it '
              "doesn't trigger on the text we have not inserted")

VISIBLE_TEXT = (
    "The edit watcher polls the focused field every 2.5 seconds after an "
    "insertion. When the field text stays unchanged between two consecutive "
    "polls, the detected correction pair fires a cue: a clickable pill showing "
    "wrong -> right. Clicking it promotes the pair to corrections.tsv and "
    "reloads the dictionary live. The watcher stops after 3 minutes, on app "
    "switch, or when a new recording starts. This way transcription edits "
    "become dictionary entries within seconds of your manual fix."
)

PASS_MAX_WORDS = 40


def _load():
    """Build a Formatter from the live ~/.golos config (real network calls)."""
    import httpx
    from dictate_core.formatter import Formatter
    cfg = tomllib.load(open(Path.home() / ".golos" / "config.toml", "rb"))
    context = {"app_name": "Slack", "bundle_id": "com.tinyspeck.slackmacgap",
               "window_title": "#dev", "visible_text": VISIBLE_TEXT}

    def call(fmt, user):
        payload = {"model": fmt.model,
                   "messages": [{"role": "system",
                                 "content": fmt.build_system_prompt(context)},
                                {"role": "user", "content": f'Transcript: "{user}"'}],
                   "temperature": 0.2}
        with httpx.Client(timeout=90) as client:
            r = client.post("https://openrouter.ai/api/v1/chat/completions",
                            json=payload,
                            headers={"Authorization":
                                     f"Bearer {cfg['openrouter']['api_key']}"})
            r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def fmt_for(answer):
        c = dict(cfg)
        c["formatting"] = dict(cfg["formatting"],
                               answer_questions=answer, debug=False)
        return Formatter(c, ["golos"], [])

    return call, fmt_for, cfg["formatting"]["model"]


def _verdict(label, out, predicate):
    ok = predicate(out)
    print(f"[{label}] {out!r}")
    print(f"  -> {'PASS' if ok else 'FAIL'} ({len(out.split())} words)")
    return ok


def main() -> int:
    mode = "transcribe"
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    call, fmt_for, model = _load()
    print(f"model: {model} | mode: {mode}\n")

    if mode == "transcribe":
        out = call(fmt_for(False), TRANSCRIPT)
        ok = _verdict("question + trap context", out,
                      lambda o: len(o.split()) <= PASS_MAX_WORDS
                      and "\n-" not in o and "**" not in o)
        return 0 if ok else 1

    # --mode answer: the four behavior cases
    results = []
    out = call(fmt_for(False), TRANSCRIPT)
    results.append(_verdict("false + question + trap", out,
                            lambda o: len(o.split()) <= PASS_MAX_WORDS
                            and "\n-" not in o and "**" not in o))
    out = call(fmt_for(True),
               "what does the edit watcher poll every how many seconds?")
    results.append(_verdict("true + answerable question", out,
                            lambda o: "2.5" in o))
    out = call(fmt_for(True),
               "what is the airspeed velocity of an unladen swallow?")
    results.append(_verdict("true + unanswerable question", out,
                            lambda o: o.rstrip(".?").lower().endswith("swallow")
                            and "context" not in o.lower()))
    out = call(fmt_for(True), "schedule the sync for tomorrow at nine")
    results.append(_verdict("true + ordinary dictation", out,
                            lambda o: "schedule" in o.lower()
                            and len(o.split()) <= 15))
    ok = all(results)
    print(f"\n{'PASS' if ok else 'FAIL'}: {sum(results)}/4 cases")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

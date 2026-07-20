---
@purpose: "How to contribute to golos: environment, tests, PR expectations, and scope for the v0.3.1 macOS beta."
@why: "Keeps community patches aligned with real install paths, unsigned beta limits, and the documented test suite."
@role: reference
@stability: accepted
@tags: [golos, contributing, community, pr, tests]
related_docs: [README.md, docs/TESTING.md, docs/TECH.md, docs/ROADMAP.md, SECURITY.md, RELEASE_CHECKLIST.md]
---
# Contributing to golos

Thanks for helping. golos is an open-source macOS push-to-talk dictation app
(Python + PyObjC). The public packages are still named `dictate` /
`dictate_core`.

## What you are contributing to

- **Platform:** macOS 13+ only for the shipping app.
- **Architectures:** Apple Silicon (cloud + optional local MLX) and Intel
  (cloud-only OpenRouter).
- **Current public build:** **v0.3.1 unsigned beta** DMGs. First launch is
  **right-click → Open**. Builds are **not** signed or notarized, and there
  is **no** automatic updater (releases open via GitHub; install is manual).
- **User data:** runtime state lives under **`~/.golos/`** (config, history,
  dictionary, recordings). Never commit that directory or personal audio/text.

Read [README.md](README.md) for product overview, [docs/TECH.md](docs/TECH.md)
for architecture, and [docs/ROADMAP.md](docs/ROADMAP.md) for honest scope.

## Development setup

```sh
git clone https://github.com/Dopomogai/golos.git
cd golos
python3.11 -m venv .venv   # any Python ≥ 3.11
.venv/bin/pip install -r requirements.txt
# Optional local STT on Apple Silicon only:
# .venv/bin/pip install -r requirements-local.txt
.venv/bin/pip install -r requirements-dev.txt
# or: .venv/bin/pip install -e ".[dev]"
```

Grant **Microphone**, **Input Monitoring**, and **Accessibility** to the
terminal (or `golos.app` if you run a bundle). Set
**System Settings → Keyboard → "Press 🌐/fn key to" → Do Nothing**.

```sh
./dictate.sh            # start from source
./dictate.sh quit
```

## Tests (required for code changes)

Exact commands are documented in [docs/TESTING.md](docs/TESTING.md):

```sh
.venv/bin/python -m pytest -q
python3 -m compileall -q dictate dictate_core scripts tests
```

- Prefer **pytest** under `tests/` for headless regressions.
- Do **not** call live OpenRouter/Deepgram, open a GUI app, capture the mic,
  mutate the clipboard, or write to the real `~/.golos` in automated tests.
- Legacy scripts under `scripts/` still matter when they cover your area.

## Pull requests

1. Keep the change focused; one concern per PR when practical.
2. Add or update **focused tests** for behavior you change (when headless
   coverage is possible).
3. Align any user-facing **docs/copy** with the change (README, product docs,
   site copy only if the PR intentionally updates them).
4. **Never** include API keys, personal recordings, `history.jsonl`, or a
   populated `~/.golos` config.
5. If you touch **packaging** (`build_app.sh`, `build_intel_app.sh`,
   `make_dmg.sh`, `setup.py` py2app config, entitlements, or DMG layout):
   note signing/notarization implications. The public beta remains
   **unsigned**; do not claim signed/notarized distribution unless that is
   actually implemented and verified.

## Issues and security

- Bugs and features: use the GitHub issue forms.
- Security: see [SECURITY.md](SECURITY.md) — do not post secrets or exploit
  detail in public issues.

## License

By contributing, you agree your contributions are licensed under the
project [MIT License](LICENSE).

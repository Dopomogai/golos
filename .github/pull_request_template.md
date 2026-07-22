## Summary

<!-- What changed and why (user-visible outcome first). -->

## Type of change

- [ ] Bug fix
- [ ] Feature / enhancement
- [ ] Docs / community only
- [ ] Packaging / build (`build_*.sh`, `make_dmg.sh`, py2app / DMG)
- [ ] Tests only

## Checklist

- [ ] **Focused tests** added or updated when behavior changes and headless coverage is possible (`tests/` preferred; see `docs/TESTING.md`).
- [ ] Ran documented suite: `.venv/bin/python -m pytest -q` (and relevant `scripts/` probes if applicable).
- [ ] **Docs/copy alignment**: user-facing text matches the change (only files this PR intentionally updates).
- [ ] **No secrets / personal data**: no API keys, no `~/.golos` dumps, no personal recordings, history JSONL, or private transcripts.
- [ ] Scope stays honest for the **v0.3.3 unsigned macOS beta** (macOS 13+, Apple Silicon + Intel; no false signed/auto-update claims).

## Packaging changes (if any)

If this PR touches packaging, signing-related scripts, entitlements, or release artifacts:

- [ ] I understand public beta DMGs are **unsigned** and **not notarized**; first launch remains **right-click → Open**.
- [ ] I noted any implications for a future Developer ID / notarization path (do not claim auto-update or signed distribution unless implemented and verified).
- [ ] I did not commit `dist/`, `build/`, or architecture DMGs unless maintainers explicitly asked.

## Test plan

<!-- Exact commands and manual smoke you ran. -->

```sh
.venv/bin/python -m pytest -q
```

## Related issues

<!-- Fixes #… / Relates to #… -->

---
@purpose: "How to report security issues in golos without leaking API keys, private audio, or exploit detail."
@why: "Gives a truthful private-reporting path when no public security email is published on the org or repo."
@role: reference
@stability: accepted
@tags: [golos, security, vulnerability, privacy, community]
related_docs: [README.md, CONTRIBUTING.md, docs/TECH.md, docs/PRODUCT.md]
---
# Security policy

## Supported versions

Security reports are accepted for the **currently published macOS beta**
(**v0.3.3** at the time of writing) and for the default branch of this
repository. Older tags may not receive fixes.

## Product context (for reporters)

- macOS 13+ menu-bar dictation app; Apple Silicon and Intel builds.
- Public DMGs are an **unsigned beta** (right-click → Open). There is no
  code signing/notarization and **no** auto-updater yet.
- Local state is under **`~/.golos/`** (including `config.toml`, which may
  hold an OpenRouter API key, plus history and optional retained audio).
- Cloud STT/formatting send audio and/or text to third-party APIs when those
  features are enabled; see [docs/TECH.md](docs/TECH.md) § Security & privacy.

## Reporting a vulnerability

No dedicated security email is published in GitHub org/repo metadata for
**Dopomogai/golos**. Do **not** invent a contact address.

**Use GitHub private vulnerability reporting:** open a
[private security advisory](https://github.com/Dopomogai/golos/security/advisories/new),
or choose **Security → Report a vulnerability** in the repository. This is
enabled and is the supported private channel.

If GitHub private reporting is temporarily unavailable, open a **minimal
public issue** that:

1. States only that you found a security concern (no exploit steps, no PoC,
   no secrets, no private audio/text).
2. Asks maintainers to open a **private channel** (for example enable private
   vulnerability reporting or share a secure contact).
3. Waits for that channel before sharing details.

Do **not** file a full public bug report for security-sensitive findings.

## What to include (only over a private channel)

- Affected version (app about string / release tag / commit).
- Architecture and macOS version if relevant.
- Clear reproduction steps and impact.
- Sanitized logs only — **never** paste API keys, tokens, full `config.toml`,
  personal dictation history, or private audio/transcripts.

## Out of scope (usual)

- Issues that require a compromised macOS user account or already-granted
  Accessibility/Input Monitoring abuse outside golos’s own boundaries.
- Third-party service outages or OpenRouter model quality alone.
- Unsigned-binary Gatekeeper friction (known beta limitation; see roadmap).

Thank you for helping keep golos and its users safe.

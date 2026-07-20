"""Dictionary (vocabulary biasing terms) and corrections list loading.

Plain text files under ~/.golos/: dictionary.txt (one term per line) and
corrections.tsv (wrong\\tright). Used to bias STT prompts and stage-2
formatting; never sent as raw file uploads.
"""

from pathlib import Path


def load_terms(path: str) -> list[str]:
    """Load dictionary terms; blank lines and # comments are ignored."""
    p = Path(path)
    if not p.exists():
        return []
    terms = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def load_corrections(path: str) -> list[tuple[str, str]]:
    """Load corrections.tsv: lines of wrong<TAB>right."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip():
            out.append((parts[0].strip(), parts[1].strip()))
    return out

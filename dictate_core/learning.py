"""Pure text-diff helpers for the learning loop (UI-free, no AppKit).

Used by the dictate app (dictate/learning.py) and by dictate_core.VoicePipeline.
"""

import difflib
import logging
import re
import string

log = logging.getLogger(__name__)

_PUNCT = string.punctuation + "…“”‘’—–"

_BOX_DRAWING = (
    "─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┝┞┟┠┡┢┣┤┥┦┧┨┩┪┫┬┭┮┯┰┱┲┳┴┵┶┷┸┹┺┻"
    "┼┽┾┿╀╁╂╃╄╅╆╇╈╉╊╋═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬╭╮╯╰"
    "▀▄█▌▐░▒▓▔▕▖▗▘▙▚▛▜▝▞▟■□▪▫"
)


def normalize_visible(text: str) -> str:
    """Light cleanup of scraped UI text: box-drawing/block glyphs replaced by
    spaces, long space runs collapsed, 3+ newlines folded to one blank line."""
    text = "".join(" " if c in _BOX_DRAWING else c for c in text)
    text = re.sub(r" {2,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def norm_text(s: str) -> str:
    """Collapse all whitespace runs to single spaces."""
    return " ".join(s.split())


def _strip_punct(s: str) -> str:
    return s.strip(_PUNCT + " \t")


def extract_replacement_pairs(inserted: str, edited: str) -> list[tuple[str, str]]:
    """Token-diff two texts and return (wrong, right) replacement pairs.

    Tokens are matched punctuation-insensitively ("tomorrow" == "tomorrow?"),
    so punctuation-only edits don't create noise; case stays significant
    ("wisper" != "Wispr") since capitalization fixes are worth learning.
    Contiguous replaced token runs become one pair ("wisper flow" -> "Wispr
    Flow"). Pairs where either side is shorter than 2 chars are ignored.
    """
    a = norm_text(inserted).split()
    b = norm_text(edited).split()
    ka = [_strip_punct(t) for t in a]
    kb = [_strip_punct(t) for t in b]
    pairs = []
    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        wrong = " ".join(a[i1:i2])
        right = " ".join(b[j1:j2])
        if len(_strip_punct(wrong)) < 2 or len(_strip_punct(right)) < 2:
            continue
        pairs.append((wrong, right))
    return pairs


def pair_is_plausible(wrong: str, right: str) -> tuple[bool, str]:
    """Similarity gate: a real correction fixes a near-miss. Junk pairs from
    mis-anchored spans (e.g. 'We' -> 'likely') fail this."""
    if len(wrong.split()) > 6 or len(right.split()) > 6:
        return False, "more than 6 tokens on one side"
    ratio = difflib.SequenceMatcher(
        None, wrong.lower(), right.lower(), autojunk=False).ratio()
    if ratio >= 0.5:
        return True, ""
    wl, rl = wrong.lower(), right.lower()
    if wl in rl or rl in wl:
        return True, ""  # one side contains the other (e.g. added suffix)
    return False, f"not similar enough (ratio {ratio:.2f})"


def suggest_pairs(full_text: str, inserted: str) -> list[tuple[str, str]]:
    """Fuzzy-locate `inserted` inside `full_text` and diff the edited regions.

    Acceptance gates (v2, scroll-tolerant):
    - the field text is normalized like visible_text (box-drawing, whitespace)
      before matching;
    - the longest exact common block must be >= 12 chars (>= 8 with the
      stricter 60% coverage, so short-but-clean edits still pass);
    - coverage is computed against the OVERLAP: when the field is shorter
      than the insertion (a scrolled input box dropped the older part), the
      field length is the denominator — otherwise the insertion length;
      require >= 50% (>= 60% under the 8-char anchor);
    - each pair must still look like a near-miss (pair_is_plausible).
    Returns [] when the inserted text is unchanged or too changed to trust.
    """
    ins = norm_text(normalize_visible(inserted))
    full = norm_text(normalize_visible(full_text))
    if not ins or not full:
        return []
    if ins in full:
        return []  # untouched

    sm = difflib.SequenceMatcher(None, full, ins, autojunk=False)
    blocks = sm.get_matching_blocks()
    matched = sum(b.size for b in blocks)
    m = max(blocks, key=lambda b: b.size)
    # Scroll tolerance: a short field (scrolled input) is measured against
    # itself, not against the full insertion.
    denom = min(len(full), len(ins))
    coverage = matched / denom
    if m.size >= 12:
        need = 0.5
    elif m.size >= 8:
        need = 0.6
    else:
        log.info("Learning skipped: anchor %d chars too short.", m.size)
        return []
    if coverage < need:
        log.info("Learning skipped: inserted text not found in field / too "
                 "changed (coverage %.0f%% < %.0f%%, anchor %d chars).",
                 coverage * 100, need * 100, m.size)
        return []

    # Shrink the anchor to word boundaries so an edit touching the anchor's
    # edge (e.g. "flow" -> "Flow") stays inside the diffed region instead of
    # producing truncated pairs like "wisper" -> "Wispr".
    a, b, size = m.a, m.b, m.size
    while size > 0 and b > 0 and not ins[b - 1].isspace():
        a += 1
        b += 1
        size -= 1
    while size > 0 and b + size < len(ins) and not ins[b + size].isspace():
        size -= 1
    if size <= 0:
        return []

    # Diff only the unmatched head/tail regions around the anchor — never the
    # whole field. The field-side region is capped near the edit size so
    # unrelated surrounding text can't misalign into pairs.
    pairs = []
    regions = [
        (ins[:b], full[:a], True),                 # head: cap from the right
        (ins[b + size:], full[a + size:], False),  # tail: cap from the left
    ]
    for i_region, f_region, is_head in regions:
        if not i_region.strip():
            continue
        cap = int(len(i_region) * 1.5) + 10
        f_region = f_region[-cap:] if is_head else f_region[:cap]
        for wrong, right in extract_replacement_pairs(i_region, f_region):
            ok, reason = pair_is_plausible(wrong, right)
            if ok:
                pairs.append((wrong, right))
            else:
                log.debug("Discarded pair %r -> %r: %s", wrong, right, reason)
    return pairs

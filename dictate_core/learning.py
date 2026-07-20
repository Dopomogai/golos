"""Pure text-diff helpers for the learning loop (UI-free, no AppKit).

Used by the dictate app (dictate/learning.py) and by dictate_core.VoicePipeline.

Heuristics and false-positive guards (suggest_pairs / pair_is_plausible):
- scroll-tolerant fuzzy locate of the insertion inside the live field text;
- minimum anchor length + coverage so wholesale rewrites are ignored;
- short whole-field near-miss path when the field *is* the recent short
  insertion (scope + similarity), without relaxing the 8/12-char anchors
  used to locate short text inside large/embedded fields;
- near-miss similarity gate so mis-anchored spans (e.g. 'We'→'likely') drop;
- token runs only for replace ops; pure appends/prepends yield no pairs;
- when a replace block is unbalanced (trailing/leading field chrome after a
  short proper-name edit), fall back to per-token near-miss alignment so a
  5-char name like Mercy→Mercey is not dropped — never an 8-char token min.
All processing is local — no network, no AppKit.
"""

import difflib
import logging
import re
import string

log = logging.getLogger(__name__)

_PUNCT = string.punctuation + "…“”‘’—–"

# Short whole-field confidence path (anchor < 8 only).
# Why safe: when the field is essentially the insertion itself (similar length
# and high overall similarity), a whole-field token-diff cannot pull in
# unrelated surrounding UI text. Embedded short insertions in much larger
# fields fail the length-scope gate and still need the normal 8/12-char anchor.
_SHORT_MAX_CHARS = 64          # both sides must fit (short insertion / field)
_SHORT_LEN_RATIO = 2.0         # max(len)/min(len) — allows ok→okay, not rewrites
_SHORT_MIN_SIM = 0.5           # case-insensitive whole-string similarity

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


def _token_similarity(a: str, b: str) -> float:
    """Case-insensitive similarity of two tokens (punctuation stripped)."""
    al, bl = _strip_punct(a).lower(), _strip_punct(b).lower()
    if not al or not bl:
        return 0.0
    ratio = difflib.SequenceMatcher(None, al, bl, autojunk=False).ratio()
    if al in bl or bl in al:
        return max(ratio, 0.51)
    return ratio


def _near_miss_token_pairs(
    wrong_toks: list[str], right_toks: list[str],
) -> list[tuple[str, str]]:
    """1:1 greedy near-miss pairs inside an unbalanced replace block.

    Used when field chrome trails a short edit (e.g. Mercy. → Mercey. -- sig):
    the contiguous multi-token right side fails pair_is_plausible, but the
    real correction is still a single near-miss token. Min token length is 2
    chars (not 8) so proper names like Mercy stay eligible.
    """
    used: set[int] = set()
    pairs: list[tuple[str, str]] = []
    for wrong in wrong_toks:
        if len(_strip_punct(wrong)) < 2:
            continue
        best_j: int | None = None
        best_ratio = 0.0
        for j, right in enumerate(right_toks):
            if j in used or len(_strip_punct(right)) < 2:
                continue
            ratio = _token_similarity(wrong, right)
            if ratio > best_ratio:
                best_ratio = ratio
                best_j = j
        if best_j is not None and best_ratio >= 0.5:
            used.add(best_j)
            pairs.append((wrong, right_toks[best_j]))
    return pairs


def extract_replacement_pairs(inserted: str, edited: str) -> list[tuple[str, str]]:
    """Token-diff two texts and return (wrong, right) replacement pairs.

    Tokens are matched punctuation-insensitively ("tomorrow" == "tomorrow?"),
    so punctuation-only edits don't create noise; case stays significant
    ("wisper" != "Wispr") since capitalization fixes are worth learning.
    Contiguous replaced token runs with equal token counts become one pair
    ("wisper flow" -> "Wispr Flow") when still a near-miss. Unbalanced
    replace blocks (extra field tokens after a short name fix) fall back to
    per-token near-miss alignment so Mercy→Mercey is kept and trailing
    chrome is not. Pairs where either side is shorter than 2 chars are
    ignored — there is no 8-character token minimum.
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
        wrong_toks = a[i1:i2]
        right_toks = b[j1:j2]
        if not wrong_toks or not right_toks:
            continue
        wrong = " ".join(wrong_toks)
        right = " ".join(right_toks)
        if (len(wrong_toks) == len(right_toks)
                and len(_strip_punct(wrong)) >= 2
                and len(_strip_punct(right)) >= 2):
            ok, _ = pair_is_plausible(wrong, right)
            if ok:
                pairs.append((wrong, right))
                continue
        # Unequal counts, or equal-count but implausible as a whole span:
        # keep only near-miss token pairs (short proper names amid chrome).
        pairs.extend(_near_miss_token_pairs(wrong_toks, right_toks))
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


def _short_edit_credible(full: str, ins: str) -> tuple[bool, str]:
    """Whether a short-anchor edit is safe to learn via whole-field diff.

    Safe when the focused field is credibly the recent short insertion itself
    (both short, length within a tight band, overall near-miss similarity).
    Not safe when the insertion is a small span inside a much larger field —
    those still need the 8/12-char location anchor.
    """
    n_full, n_ins = len(full), len(ins)
    longer, shorter = max(n_full, n_ins), min(n_full, n_ins)
    if longer > _SHORT_MAX_CHARS:
        return False, (f"not whole-field short scope "
                       f"(field {n_full} chars, insertion {n_ins} chars, "
                       f"max {_SHORT_MAX_CHARS})")
    if shorter == 0 or longer / shorter > _SHORT_LEN_RATIO:
        return False, (f"length scope too wide "
                       f"(field {n_full} chars, insertion {n_ins} chars)")
    sim = difflib.SequenceMatcher(
        None, full.lower(), ins.lower(), autojunk=False).ratio()
    if sim < _SHORT_MIN_SIM:
        return False, f"similarity too low (ratio {sim:.2f} < {_SHORT_MIN_SIM})"
    return True, ""


def _plausible_pairs(inserted_region: str, field_region: str) -> list[tuple[str, str]]:
    """extract_replacement_pairs + pair_is_plausible, with debug discards."""
    pairs = []
    for wrong, right in extract_replacement_pairs(inserted_region, field_region):
        ok, reason = pair_is_plausible(wrong, right)
        if ok:
            pairs.append((wrong, right))
        else:
            log.debug("Discarded pair %r -> %r: %s", wrong, right, reason)
    return pairs


def suggest_pairs(full_text: str, inserted: str) -> list[tuple[str, str]]:
    """Fuzzy-locate `inserted` inside `full_text` and diff the edited regions.

    Acceptance gates (v2, scroll-tolerant + short whole-field path):
    - the field text is normalized like visible_text (box-drawing, whitespace)
      before matching;
    - the longest exact common block must be >= 12 chars (>= 8 with the
      stricter 60% coverage, so short-but-clean edits still pass);
    - coverage is computed against the OVERLAP: when the field is shorter
      than the insertion (a scrolled input box dropped the older part), the
      field length is the denominator — otherwise the insertion length;
      require >= 50% (>= 60% under the 8-char anchor);
    - when the longest exact anchor is < 8 chars, a short-confidence path
      may still accept a whole-field near-miss if the field is credibly the
      recent short insertion (both ≤ 64 chars, length ratio ≤ 2, overall
      case-insensitive similarity ≥ 0.5). Embedded short insertions in much
      larger fields fail that scope gate and still require the 8/12-char
      anchor — ambiguous 1–7 char anchors never locate into large text;
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
    coverage = matched / denom if denom else 0.0
    if m.size >= 12:
        need = 0.5
    elif m.size >= 8:
        need = 0.6
    else:
        # Short-confidence path: whole-field near-miss only when the field is
        # credibly the recent short insertion (see _short_edit_credible).
        ok, reason = _short_edit_credible(full, ins)
        if not ok:
            log.info("Learning skipped: short-edit refused (%s, anchor %d).",
                     reason, m.size)
            return []
        pairs = _plausible_pairs(ins, full)
        if not pairs:
            log.info("Learning skipped: short-edit had no plausible pairs "
                     "(anchor %d chars).", m.size)
        return pairs
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
        pairs.extend(_plausible_pairs(i_region, f_region))
    return pairs

"""Near-duplicate detection between generated tasks of the same template.

Code is canonicalized (identifiers, strings and numbers replaced by placeholders, comments and
docstrings dropped), cut into 5-token shingles, and compared with Jaccard similarity.

Two tasks of a template are near-duplicates if either
- their packages reach THRESHOLD similarity, or
- their reference fixes make the same canonicalized edit (FIX_KEY) and their packages reach
  FIX_THRESHOLD similarity: the agent would make the same edit in the same place, and the code around
  it differs only in ways that don't change the work. (Added after the CP1 human audit.)
"""

from __future__ import annotations

import difflib
import io
import keyword
import tokenize

THRESHOLD = 0.85
FIX_THRESHOLD = 0.70
SHINGLE = 5
_KEEP = set(keyword.kwlist) | {"self", "async", "await", "None", "True", "False"}


def canonical_tokens(source: str) -> list:
    out = []
    prev = None
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER):
            if tok.type in (tokenize.INDENT, tokenize.DEDENT):
                out.append(tokenize.tok_name[tok.type])
            prev = tok
            continue
        if tok.type == tokenize.STRING:
            # Docstrings: a string that is a whole statement.
            if prev is None or prev.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.NL):
                prev = tok
                continue
            out.append("STR")
        elif tok.type == tokenize.NUMBER:
            out.append("NUM")
        elif tok.type == tokenize.NAME:
            out.append(tok.string if tok.string in _KEEP else "ID")
        else:
            out.append(tok.string)
        prev = tok
    return out


def shingles(files: dict) -> frozenset:
    tokens = []
    for name in sorted(files):
        tokens += canonical_tokens(files[name])
    return frozenset(tuple(tokens[i:i + SHINGLE]) for i in range(max(0, len(tokens) - SHINGLE + 1)))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _notation(tokens: list) -> str:
    """Canonical tokens with notational differences removed: `x["k"]` reads as `x.k`, `self.x` as `x`."""
    out, i = [], 0
    while i < len(tokens):
        if tokens[i] == "[" and i + 2 < len(tokens) and tokens[i + 1] == "STR" and tokens[i + 2] == "]":
            out += [".", "ID"]
            i += 3
        elif tokens[i] == "self" and i + 1 < len(tokens) and tokens[i + 1] == ".":
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out)


def _canon_line(text: str) -> str:
    try:
        return _notation(canonical_tokens(text.strip() + "\n"))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text.strip()


def fix_key(files: dict, fixed: dict) -> str:
    """The reference fix's edit, canonicalized, for the near-duplicate rule.

    Removed and added lines whose canonical form appears on both sides of the diff are left out (lines
    the fix only moves or re-indents, but also lines that differ only in identifiers, which
    canonicalization erases), so a block wrapped in a try/except counts by the wrapper. The line on
    either side of each change is kept as context. The key errs toward calling two fixes the same:
    different fixes that only move or rename lines inside the same wrapper can get equal keys.
    """
    out = []
    for name in sorted(fixed):
        diff = list(difflib.unified_diff(files.get(name, "").splitlines(), fixed[name].splitlines(), lineterm="", n=1))
        removed = {_canon_line(line[1:]) for line in diff if line.startswith("-") and not line.startswith("---")}
        added = {_canon_line(line[1:]) for line in diff if line.startswith("+") and not line.startswith("+++")}
        moved = removed & added
        for line in diff:
            if line[:1] in "+- " and not line.startswith(("+++", "---")):
                canon = _canon_line(line[1:])
                if line[0] != " " and canon in moved:
                    continue
                out.append(line[0] + canon)
    return "\n".join(out)


def near_duplicates(a_shingles, a_fix, b_shingles, b_fix, threshold=THRESHOLD, fix_threshold=FIX_THRESHOLD):
    """(is_near_duplicate, package similarity)."""
    sim = jaccard(a_shingles, b_shingles)
    return sim >= threshold or (a_fix == b_fix and sim >= fix_threshold), sim

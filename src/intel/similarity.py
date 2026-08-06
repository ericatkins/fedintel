"""Deterministic text similarity. Embeddings can replace these functions later
(same signature, same 0..1 range); the dossier must work without AI."""
import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9][a-z0-9+.-]*")
_STOP = {
    "the", "and", "for", "with", "will", "shall", "this", "that", "are", "from",
    "any", "all", "into", "such", "not", "may", "its", "per", "via", "of", "to",
    "in", "on", "a", "an", "is", "be", "by", "or", "as", "services", "support",
}


def tokens(text: str | None) -> Counter:
    return Counter(t for t in _WORD.findall((text or "").lower())
                   if len(t) > 2 and t not in _STOP)


def cosine(a: str | None, b: str | None) -> float:
    """Token cosine similarity, 0..1."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    common = set(ta) & set(tb)
    num = sum(ta[t] * tb[t] for t in common)
    den = math.sqrt(sum(v * v for v in ta.values())) * math.sqrt(sum(v * v for v in tb.values()))
    return num / den if den else 0.0


def solnum_family(a: str | None, b: str | None) -> bool:
    """Same solicitation-number family: exact, or shared prefix of >= 8
    significant chars (handles -0001 / amendment suffixes)."""
    if not a or not b:
        return False
    na = re.sub(r"[^A-Z0-9]", "", a.upper())
    nb = re.sub(r"[^A-Z0-9]", "", b.upper())
    if not na or not nb:
        return False
    if na == nb:
        return True
    prefix = min(len(na), len(nb))
    return prefix >= 8 and na[:prefix] == nb[:prefix]

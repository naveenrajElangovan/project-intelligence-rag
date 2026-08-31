"""Tokenisation for the lexical (BM25) half of retrieval.

The original tokeniser treated a compound identifier as one atomic term:

    query  "APP_CLOSE_SHIFT_EVENT what does this event require?"
      -> ['app_close_shift_event', 'what', 'does', 'this', 'event', 'require']
    page   "### `APP_CLOSE_SHIFT` - id 104 ... `shiftSummary` (`shift_summary`)"
      -> ['app_close_shift', 'id', '104', ..., 'shiftsummary', 'shift_summary']

The most discriminating term in the question -- the event name -- matched
nothing, because a language constant ending in `_EVENT` and its wire name are
different strings. Scoring then fell to 'event', 'what',
'does', 'require', which are the least informative words in the query, and the
lexical channel ranked unrelated workflow prose above the page that defines the
event. The same blindness separated `shiftSummary` from `shift_summary`.

So: keep the whole token *and* emit its parts, splitting on the separators that
appear in identifiers and on camelCase boundaries. This is what a production
analyser does (Elasticsearch's word_delimiter_graph with preserve_original), and
it is symmetric -- query and document go through the same function, so BM25's
term statistics stay consistent.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:#-]*")
_SEPARATORS = re.compile(r"[_./:#-]+")
# Splits fooBar, FOOBar and foo2Bar without splitting FOO or foo.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# One character carries no lexical signal, and a bare digit run is already
# covered by the whole token (so `0.4` does not contribute a lonely `4`).
_MINIMUM_PART = 2


def tokens(value: str) -> list[str]:
    """Return BM25 terms for *value*: whole tokens plus identifier subwords."""

    result: list[str] = []
    for match in _TOKEN_RE.findall(value):
        whole = match.casefold()
        result.append(whole)
        result.extend(subtokens(match))
    return result


def subtokens(token: str) -> list[str]:
    """Return the identifier parts of *token*, or nothing if it is one word."""

    parts: list[str] = []
    for chunk in _SEPARATORS.split(token):
        if not chunk:
            continue
        parts.extend(_CAMEL.split(chunk))
    folded = [
        part.casefold()
        for part in parts
        if len(part) >= _MINIMUM_PART and not part.isdigit()
    ]
    # A single part means the token was already one plain word; re-emitting it
    # would double its term frequency and quietly distort BM25.
    if len(folded) < 2:
        return []
    return folded

"""English/Spanish language resolution and deterministic query autocorrection.

Two invariants this module exists to hold:

1. The assistant answers in English or Spanish and never in a third language.
   ``detect_query_language`` may still report ``"mixed"`` for a genuinely
   bilingual question, but ``resolve_response_language`` always collapses that
   to a supported language before it reaches a prompt.
2. Correction is deterministic and dictionary-bounded. A token is rewritten
   only when it is within a small edit distance of a *function or question
   word* -- never a domain term, identifier, acronym, or known entity. No model
   call is involved, so the same question always produces the same corrected
   question and evaluation runs stay reproducible.

Stdlib only, on purpose: this module is imported by prompt construction and by
pre-graph request handling, and it must stay cheap and independently testable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Literal


SupportedLanguage = Literal["en", "es"]
SUPPORTED_LANGUAGES: tuple[SupportedLanguage, ...] = ("en", "es")

# Tie-break for a question that carries no recognisable English or Spanish
# signal at all. Overridden per deployment by Settings.default_response_language.
DEFAULT_RESPONSE_LANGUAGE: SupportedLanguage = "es"

# Characters that only appear in Spanish orthography. Worth more than a single
# stopword hit because they cannot be produced by an English question.
_SPANISH_ORTHOGRAPHY = re.compile(r"[áéíóúüñ¿¡]")
_SPANISH_ORTHOGRAPHY_WEIGHT = 2

# Letters only: digits and underscores are excluded so identifiers never reach
# the corrector through this path.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Deliberately narrow. Every word here is unambiguous across the two languages:
# anything that is a real word in both (a, no, me, son, he, has, van, actual,
# ...) is excluded, because a shared token is evidence for neither side and a
# bad correction target.
ENGLISH_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "the", "of", "that", "for", "how", "what", "status", "tell", "about",
        "describe", "explain", "overview", "list", "all", "every", "feature",
        "features", "have", "which", "where", "when", "who", "why", "whose",
        "does", "did", "is", "are", "was", "were", "been", "being", "had",
        "this", "these", "those", "there", "their", "they", "them", "its",
        "with", "from", "into", "and", "but", "than", "then", "also", "only",
        "show", "give", "please", "can", "could", "should", "would", "must",
        "need", "want", "find", "search", "work", "works", "working", "used",
        "between", "during", "before", "after", "again", "any", "some", "more",
        "most", "each", "both", "such", "very", "many", "much", "summary",
        "details", "detail", "difference", "example", "current", "currently",
    }
)

SPANISH_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
        "al", "que", "para", "por", "con", "sin", "como", "cual", "cuales",
        "cuando", "donde", "quien", "quienes", "cuanto", "cuantos", "cuanta",
        "cuantas", "porque", "es", "esta", "estan", "este", "estos", "esta",
        "estas", "ese", "esa", "esos", "esas", "estado", "sobre", "hacia",
        "desde", "entre", "segun", "tambien", "pero", "mas", "muy", "todo",
        "todos", "toda", "todas", "funciona", "funcionan", "funcionamiento",
        "explica", "explicar", "dime", "lista", "listar", "informacion",
        "detalles", "resumen", "quiero", "necesito", "puedo", "puede",
        "pueden", "hay", "tiene", "tienen", "tener", "hacer", "hace", "ver",
        "saber", "decir", "sirve", "sirven", "ademas", "aunque", "mientras",
        "cuál", "cómo", "qué",
    }
)

def _ascii_fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).casefold()


_LEXICON: frozenset[str] = frozenset(
    _ascii_fold(word) for word in (ENGLISH_FUNCTION_WORDS | SPANISH_FUNCTION_WORDS)
)
_SPANISH_FOLDED: frozenset[str] = frozenset(
    _ascii_fold(word) for word in SPANISH_FUNCTION_WORDS
)
_ENGLISH_FOLDED: frozenset[str] = frozenset(
    _ascii_fold(word) for word in ENGLISH_FUNCTION_WORDS
)

# Real words that must survive verbatim even though they sit one edit away from
# a correction target: 'cuenta' is not a misspelling of 'cuanta', and 'last' is
# not a misspelling of 'list'. Extend this rather than widening the targets.
_NEVER_CORRECT: frozenset[str] = frozenset(
    {
        "last", "first", "next", "new", "old", "user", "users", "word", "words",
        "card", "cart", "case", "cost", "chat", "flow", "note", "node", "port",
        "sale", "sales", "sort", "test", "text", "role", "rule", "line", "link",
        "cuenta", "cuentas", "tienda", "tiendas", "venta", "ventas", "cuenta",
        "pedido", "pedidos", "cliente", "clientes", "tarjeta", "caja", "cajas",
        "pago", "pagos", "precio", "precios", "producto", "productos", "tienda",
    }
)

# The only words correction is allowed to produce. Keeping the output side
# closed is what stops a spellchecker from quietly rewriting domain vocabulary:
# an unknown token is either one edit from a question word or it is left alone.
_CORRECTABLE_TARGETS: frozenset[str] = frozenset(
    {
        "what", "that", "the", "how", "which", "where", "when", "why", "status",
        "list", "feature", "features", "explain", "describe", "about",
        "overview", "summary", "details", "between", "difference", "current",
        "como", "cual", "cuales", "cuando", "donde", "para", "porque", "sobre",
        "funciona", "funcionan", "funcionamiento", "estado", "explicar",
        "informacion", "detalles", "resumen", "quiero", "necesito", "tambien",
    }
)

# Short, high-frequency typos that distance-based matching cannot resolve
# unambiguously ('wat' is one edit from both 'what' and 'was'). Explicit beats
# clever here.
_SHORT_MISSPELLINGS: dict[str, str] = {
    "wat": "what",
    "whta": "what",
    "waht": "what",
    "hwat": "what",
    "teh": "the",
    "hte": "the",
    "adn": "and",
    "nad": "and",
    "taht": "that",
    "hwo": "how",
    "hoW": "how",
    "wich": "which",
    "wher": "where",
    "statu": "status",
    "comoo": "como",
    "cmo": "como",
    "kmo": "como",
    "cual3s": "cuales",
    "funcion": "funciona",
    "funcina": "funciona",
    "funtiona": "funciona",
    "functiona": "funciona",
    "fuciona": "funciona",
    "esatdo": "estado",
    "etsado": "estado",
    "pra": "para",
    "prq": "porque",
    "xq": "porque",
}

_MINIMUM_CORRECTABLE_LENGTH = 6


def fold(value: str) -> str:
    """Casefold and strip diacritics so 'cómo' and 'como' compare equal."""

    return _ascii_fold(value)


def _damerau_within_one(first: str, second: str) -> bool:
    """True when one insertion, deletion, substitution or transposition maps a->b."""

    if first == second:
        return False
    length_first, length_second = len(first), len(second)
    if abs(length_first - length_second) > 1:
        return False
    if length_first == length_second:
        differences = [
            index
            for index in range(length_first)
            if first[index] != second[index]
        ]
        if len(differences) == 1:
            return True
        if len(differences) == 2:
            left, right = differences
            return (
                right == left + 1
                and first[left] == second[right]
                and first[right] == second[left]
            )
        return False
    shorter, longer = (
        (first, second) if length_first < length_second else (second, first)
    )
    index = 0
    while index < len(shorter) and shorter[index] == longer[index]:
        index += 1
    return shorter[index:] == longer[index + 1 :]


def _is_protected(token: str, protected: frozenset[str]) -> bool:
    """True when a token must never be rewritten."""

    folded = fold(token)
    if len(token) < _MINIMUM_CORRECTABLE_LENGTH and folded not in _SHORT_MISSPELLINGS:
        return True
    # Acronyms and short product codes are identifiers, not prose.
    if token.isupper():
        return True
    # CamelCase and internal capitals mark identifiers, not prose.
    if any(character.isupper() for character in token[1:]):
        return True
    if folded in _LEXICON or folded in protected or folded in _NEVER_CORRECT:
        return True
    # A regular inflection of a known word is already correct: 'estados' must
    # not collapse into 'estado', nor 'detalle' into 'detalles', and change
    # what gets retrieved.
    if folded.endswith("s") and (folded[:-1] in _LEXICON or folded[:-1] in protected):
        return True
    if f"{folded}s" in _LEXICON or f"{folded}s" in protected:
        return True
    return False


def _best_correction(token: str) -> str | None:
    folded = fold(token)
    mapped = _SHORT_MISSPELLINGS.get(folded)
    if mapped is not None:
        return mapped
    matches = [
        candidate
        for candidate in _CORRECTABLE_TARGETS
        if _damerau_within_one(folded, candidate)
    ]
    # Ambiguity is left alone: a coin flip between two dictionary words is more
    # damaging than the original typo.
    return matches[0] if len(matches) == 1 else None


def _match_case(original: str, replacement: str) -> str:
    if original[:1].isupper():
        return replacement.capitalize()
    return replacement


def autocorrect_question(question: str, *, vocabulary: Iterable[str] = ()) -> str:
    """Repair obvious typos in function and question words, nothing else.

    Domain terms, identifiers, acronyms and anything in the project vocabulary
    are returned untouched, so 'wat is ACME como functiona?' becomes
    'what is ACME como funciona?' while the entity survives verbatim.
    """

    protected = frozenset(
        fold(str(entity)) for entity in vocabulary if str(entity).strip()
    )
    corrections: list[tuple[int, int, str]] = []
    for match in _WORD.finditer(question):
        token = match.group()
        if _is_protected(token, protected):
            continue
        replacement = _best_correction(token)
        if replacement is None or fold(token) == replacement:
            continue
        corrections.append((match.start(), match.end(), _match_case(token, replacement)))
    if not corrections:
        return question
    pieces: list[str] = []
    cursor = 0
    for start, end, replacement in corrections:
        pieces.append(question[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(question[cursor:])
    return "".join(pieces)


def correction_count(question: str, *, vocabulary: Iterable[str] = ()) -> int:
    """Number of tokens the corrector rewrites -- content-free telemetry."""

    protected = frozenset(
        fold(str(entity)) for entity in vocabulary if str(entity).strip()
    )
    return sum(
        1
        for match in _WORD.finditer(question)
        if not _is_protected(match.group(), protected)
        and _best_correction(match.group()) is not None
    )


def language_evidence(value: str) -> tuple[int, int]:
    """Return (english_score, spanish_score) for an already-corrected question."""

    tokens = [fold(token) for token in _WORD.findall(value)]
    english = sum(token in _ENGLISH_FOLDED for token in tokens)
    spanish = sum(token in _SPANISH_FOLDED for token in tokens)
    if _SPANISH_ORTHOGRAPHY.search(value.lower()):
        spanish += _SPANISH_ORTHOGRAPHY_WEIGHT
    return english, spanish


def detect_query_language(value: str) -> str:
    """Classify a question as 'en', 'es', or 'mixed'.

    The question is autocorrected first, so a misspelling ('functiona',
    'wat') no longer silently zeroes both counters and lands in 'mixed'.
    'mixed' now means what it says: bilingual, or no signal at all. Use
    ``resolve_response_language`` for anything that reaches a prompt.
    """

    corrected = autocorrect_question(value)
    english, spanish = language_evidence(corrected)
    if spanish > english:
        return "es"
    if english > spanish:
        return "en"
    return "mixed"


def is_unclassifiable(value: str) -> bool:
    """True when neither language left any evidence, even after correction."""

    return language_evidence(autocorrect_question(value)) == (0, 0)


def resolve_response_language(
    value: str,
    *,
    default: str = DEFAULT_RESPONSE_LANGUAGE,
    previous: str | None = None,
) -> SupportedLanguage:
    """Collapse detection to a supported language. Never returns 'mixed'.

    A tie between real English and real Spanish evidence keeps the previous
    turn's language when there is one; a question with no evidence at all falls
    back to the configured default.
    """

    detected = detect_query_language(value)
    if detected in SUPPORTED_LANGUAGES:
        return detected  # type: ignore[return-value]
    if previous in SUPPORTED_LANGUAGES:
        return previous  # type: ignore[return-value]
    return default if default in SUPPORTED_LANGUAGES else DEFAULT_RESPONSE_LANGUAGE  # type: ignore[return-value]


def latest_supported_user_language(
    history: Iterable[tuple[str, str]],
) -> SupportedLanguage | None:
    """Return the language of the newest meaningful user turn, if detectable.

    Assistant text is deliberately ignored: its language may already reflect a
    fallback decision and must not reinforce an earlier classification error.
    """

    for role, content in reversed(list(history)):
        if str(role).casefold() != "user":
            continue
        detected = detect_query_language(str(content))
        if detected in SUPPORTED_LANGUAGES:
            return detected  # type: ignore[return-value]
    return None


def resolve_conversation_response_language(
    value: str,
    history: Iterable[tuple[str, str]],
    *,
    default: str = DEFAULT_RESPONSE_LANGUAGE,
) -> SupportedLanguage:
    """Resolve a turn, inheriting user language only when the turn is ambiguous."""

    return resolve_response_language(
        value,
        default=default,
        previous=latest_supported_user_language(history),
    )


def language_name(value: str, *, default: str = DEFAULT_RESPONSE_LANGUAGE) -> str:
    """Prompt-facing language name. Always English or Spanish."""

    if value == "es":
        return "Spanish"
    if value == "en":
        return "English"
    return "Spanish" if (default or DEFAULT_RESPONSE_LANGUAGE) == "es" else "English"

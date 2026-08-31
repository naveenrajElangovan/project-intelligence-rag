from __future__ import annotations

import re
import unicodedata

from app.workflow_support.query_analysis import _normalized_words


def _bounded_history(
    history: list[tuple[str, str]], maximum_tokens: int
) -> list[tuple[str, str]]:
    """Trim prior turns to a token budget, keeping the most recent ones.

    A conversation message may carry 8,000 characters and six are forwarded, so an
    unbounded history can outgrow the whole context window on its own. Newest
    turns are the ones that resolve a follow-up reference, so trimming drops the
    oldest first and truncates rather than discarding the turn that survives.
    """

    if maximum_tokens <= 0:
        return []
    remaining = maximum_tokens
    kept: list[tuple[str, str]] = []
    for role, content in reversed(history):
        cost = _estimated_tokens(content)
        if cost <= remaining:
            kept.append((role, content))
            remaining -= cost
            continue
        if remaining > 0:
            kept.append((role, content[: remaining * 3]))
        break
    kept.reverse()
    return kept


def _estimated_tokens(value: str) -> int:
    """Conservative byte-based estimate, matching the generator's preflight math."""

    return max(1, -(-len(value.encode("utf-8")) // 3))


def _conversation_resolution_needed(question: str) -> bool:
    """Detect short anaphoric follow-ups without calling a model for direct questions."""

    return _conversation_resolution_decision(question)[0]


def _conversation_resolution_decision(question: str) -> tuple[bool, str]:
    """Return the follow-up decision and a content-free telemetry reason."""

    normalized = unicodedata.normalize("NFKC", question).casefold().strip()
    words = set(_normalized_words(normalized))
    pronouns = {
        "it",
        "that",
        "this",
        "those",
        "these",
        "they",
        "them",
        "their",
        "theirs",
        "its",
        "he",
        "him",
        "his",
        "she",
        "her",
        "hers",
        "same",
        "above",
        "previous",
        "eso",
        "esto",
        "esa",
        "ese",
        "esos",
        "esas",
        "ellos",
        "ellas",
        "anterior",
        "mismo",
        "misma",
    }
    followup_prefixes = (
        "tell me more",
        "more details",
        "what about",
        "how about",
        "and what",
        "explain further",
        "continue",
        "go deeper",
        "elaborate",
        "expand on",
        "what else",
        "anything else",
        "anything more",
        "more?",
        "how so",
        "why is that",
        "and the",
        "and its",
        "then what",
        "give examples",
        "give me examples",
        "show examples",
        "show me examples",
        "list them",
        "what are the risks",
        "what are the requirements",
        "what are the prerequisites",
        "dime más",
        "más detalles",
        "qué hay de",
        "y qué",
        "explica más",
        "cómo funciona eso",
        "continúa",
        "continua",
        "profundiza",
        "elabora",
        "qué más",
        "y el",
        "y la",
        "dame ejemplos",
        "muestra ejemplos",
        "cuáles son los riesgos",
        "cuáles son los requisitos",
    )
    # A pronoun inside a complete question does not make it a follow-up. For
    # example, “what is cluster that you know?” has its own topic (cluster),
    # while “what is it?” does not. Carrying the previous subject in the first
    # case contaminates retrieval and can switch the source route incorrectly.
    if normalized.startswith(followup_prefixes):
        return True, "FOLLOWUP_PREFIX"
    # An elliptical conjunction carries the previous predicate, not a new
    # question: "and the other app?" carries the prior predicate. Retrieving on the bare
    # token loses the verb, and the verb is what selects the source route, so the
    # answer comes back unanswerable even when the evidence is indexed. Bounded to
    # two trailing words so a real question that merely opens with a conjunction
    # -- "and how does the payment gateway retry?" -- stays standalone.
    stripped = normalized.strip(" ?¿!¡.")
    elliptical = re.sub(r"^(?:and|y|also|además|ademas)\s+", "", stripped)
    if elliptical != stripped and 0 < len(elliptical.split()) <= 2:
        return True, "ELLIPTICAL_CONJUNCTION"
    anaphoric_pronouns = words & (pronouns - {"that", "this", "these", "those"})
    if anaphoric_pronouns:
        return True, "ANAPHORIC_PRONOUN"
    # A short request can carry a verb but omit what the verb applies to. The
    # workflow adopts a rewrite only when bounded conversation state exists, so
    # classifying the sentence here is safe for fresh conversations too.
    short_followup_verbs = {
        "clarify", "compare", "continue", "describe", "detail", "elaborate",
        "explain", "expand", "give", "help", "include", "list", "need",
        "provide", "show", "tell", "use", "want",
    }
    if (
        0 < len(normalized.split()) < 8
        and words & short_followup_verbs
        and not _conversation_subject(question)
    ):
        return True, "SHORT_VERB_ELLIPSIS"
    topic_words = words - pronouns - {
        "a", "an", "and", "are", "be", "do", "does", "explain", "for", "how",
        "is", "know", "me", "of", "please", "tell", "the", "to", "what", "you",
        "implemented", "implementation", "funciona", "funcion", "como", "que", "sabes",
    }
    # A demonstrative plus nothing but attribute words is a follow-up about the
    # previous subject, not a new topic. Checked before the topic-word test
    # because that test treats any unrecognised word as a fresh subject.
    if words & _DEMONSTRATIVES and not (
        topic_words
        - _DEMONSTRATIVES
        - _NON_SUBJECT_WORDS
        - _SUBJECT_IGNORED_WORDS
    ):
        return True, "DEMONSTRATIVE_ATTRIBUTE_FOLLOWUP"
    if topic_words:
        return False, "EXPLICIT_SUBJECT"
    if words & pronouns:
        return True, "ANAPHORIC_PRONOUN"
    return False, "NO_FOLLOWUP_SIGNAL"


# Shared with the follow-up predicate so the two cannot drift apart. A word
# here never introduces a new subject on its own.
_SUBJECT_IGNORED_WORDS = frozenset({
        "a", "about", "all", "also", "an", "and", "anything", "are", "as", "at", "be",
        "available", "can", "check", "could", "describe", "detail", "details", "did", "do",
        "does", "explain", "for", "from", "full", "give", "how", "i", "in",
        "here", "information", "is", "it", "its", "me", "more", "of", "on", "or",
        "overview", "please", "provide", "show", "summary", "tell", "that", "the",
        "these", "this", "those", "to", "was", "were", "what", "when", "where",
        "which", "who", "why", "with", "would", "you",
        # Greetings, acknowledgements and degree modifiers describe the turn,
        # not its subject. Treating pairs such as "yes specifically" as a new
        # entity makes an otherwise valid follow-up lose its active subject.
        "actually", "again", "certainly", "continue", "deeply", "evening",
        "exactly", "further", "good", "hello", "hey", "hi", "indeed",
        "know", "now", "okay", "ok", "particularly", "precisely", "really",
        "specifically", "sure", "yes",
        "assistant", "ignore", "instruction", "instructions", "prompt", "system",
        "acerca", "ademas", "anterior", "como", "cual", "cuando", "de", "del",
        "dame", "detalles", "dime", "donde", "el", "ella", "ellos", "en", "esa",
        "ese", "eso", "esta", "este", "esto", "explica", "informacion", "la", "las",
        "lo", "los", "mas", "muestra", "para", "por", "que", "quien", "resumen",
        "sobre", "su", "sus", "un", "una", "y",
        "claro", "continuar", "especificamente", "específicamente", "exactamente",
        "hola", "realmente", "si", "sí",
})


# Words that name a property OF a subject rather than a subject. "these are the
# only fields available?" contains no new topic: "fields" is an attribute of
# whatever the previous turn established. Treating such a word as an explicit
# subject made every attribute follow-up retrieve as a standalone string, which
# matched generic documentation instead of the active subject.
_NON_SUBJECT_WORDS = frozenset({
    "attribute", "attributes", "column", "columns", "constant", "constants",
    "default", "defaults", "enum", "enums", "field", "fields", "id", "ids",
    "key", "keys", "kind", "kinds", "label", "labels", "name", "names",
    "only", "option", "options", "parameter", "parameters", "payload",
    "properties", "property", "required", "schema", "shape", "shortcut",
    "shortcuts", "signature", "structure", "type", "types", "value", "values",
    # Copulas and existentials. Added here rather than to the shared ignore set
    # so _conversation_subject keeps its current behaviour for Spanish.
    "son", "estan", "están", "hay",
    # Adjectives that qualify an attribute set without naming a new subject.
    "available", "declared", "defined", "existing", "mandatory", "optional",
    "possible", "present", "remaining", "supported", "valid",
    "disponible", "disponibles", "unico", "unicos", "unica", "unicas",
    "único", "únicos", "única", "únicas", "definido", "definidos",
    "atributo", "atributos", "campo", "campos", "clave", "claves",
    "parametro", "parametros", "parámetro", "parámetros", "propiedad",
    "propiedades", "tipo", "tipos", "valor", "valores",
})

_DEMONSTRATIVES = frozenset({
    "that", "these", "this", "those", "same", "above", "previous",
    "esa", "ese", "eso", "esos", "esas", "esta", "estas", "este", "estos",
    "esto", "anterior", "mismo", "misma", "mismos", "mismas",
})


def _deterministic_conversation_rewrite(
    question: str,
    history: list[tuple[str, str]],
    _language: str,
) -> str | None:
    """Carry forward a neutral subject from recent completed conversation turns."""

    for role, content in reversed(history):
        if role != "user":
            continue
        subject = _conversation_subject(content)
        if subject:
            return f"{question.rstrip()} (previous subject: {subject})"
    # Completed assistant messages have already passed citation and grounding
    # checks. They keep a resolved subject alive when the bounded history window
    # contains only vague user follow-ups.
    for role, content in reversed(history):
        if role != "assistant":
            continue
        subject = _conversation_subject(content)
        if subject:
            return f"{question.rstrip()} (previous subject: {subject})"
    return None


def _conversation_subject(value: str) -> str:
    """Extract bounded retrieval terms while dropping conversational instructions."""

    # "I need for …" omits the object of "need" and carries its predicate from
    # the prior turn. Treat the trailing application label as context, not as a
    # newly introduced subject. The caller still requires conversation state
    # before adopting any rewrite.
    if re.match(r"^\s*(?:i\s+)?need\s+for\s+", value, re.IGNORECASE):
        return ""

    ignored = _SUBJECT_IGNORED_WORDS
    tokens = [
        token.rstrip(".,:;")
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9_.:/-]*", value)
    ]
    meaningful = [token for token in tokens if token.casefold() not in ignored]
    if len(meaningful) < 2 and not any(
        re.search(r"[-_.:/]", token) or any(character.isdigit() for character in token)
        for token in meaningful
    ):
        return ""
    return " ".join(meaningful[:12])


def _resolved_conversation_subject(value: str) -> str:
    """Prefer the exact bounded subject attached by the conversation resolver."""

    match = re.search(r"\(previous subject:\s*(.+?)\)\s*$", value, re.IGNORECASE)
    if match:
        return match.group(1).strip()[:500]
    return _conversation_subject(value)


def _safe_conversation_rewrite(
    question: str,
    candidate: str,
    history: list[tuple[str, str]],
) -> bool:
    """Reject rewrites that introduce content absent from the current or prior chat."""

    rewritten = re.sub(r"\s+", " ", candidate).strip()
    if len(rewritten) < 2 or len(rewritten) > 4000:
        return False
    allowed = set(_normalized_words(question))
    for _role, content in history:
        allowed.update(_normalized_words(content))
    harmless = {
        "application",
        "are",
        "behavior",
        "code",
        "documented",
        "does",
        "flow",
        "function",
        "has",
        "have",
        "how",
        "implemented",
        "implementation",
        "is",
        "of",
        "project",
        "the",
        "what",
        "works",
        "aplicación",
        "cómo",
        "documentado",
        "el",
        "en",
        "es",
        "está",
        "flujo",
        "funciona",
        "implementación",
        "proyecto",
        "qué",
    }
    return set(_normalized_words(rewritten)) <= allowed | harmless

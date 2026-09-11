from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.workflow_support.language import fold
from app.workflow_support.query_analysis import _normalized_words


def _subject_matches_vocabulary(
    subject: str, vocabulary: Iterable[str]
) -> bool:
    """Return whether a candidate subject shares a normalized project term."""

    subject_words = set(_normalized_words(subject))
    vocabulary_words = {
        word
        for entry in vocabulary
        for word in _normalized_words(str(entry))
    }
    return bool(subject_words & vocabulary_words)


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


def _contextual_subtopic_followup(
    question: str, history: list[tuple[str, str]]
) -> bool:
    """Recognize a short named subtopic taken from the preceding answer.

    A fragment such as ``named subsystem flow?`` names a real entity, but it
    still borrows its predicate from the prior turn. Prior answer text is used
    only to link the topic; retrieved project evidence remains the sole source
    of answer facts.
    """

    normalized = unicodedata.normalize("NFKC", question).casefold().strip()
    words = set(_normalized_words(normalized))
    if not normalized.endswith(("?", "¿")) or not 1 < len(words) <= 8:
        return False
    relation_words = {
        "behavior", "details", "flow", "mechanism", "overview", "part",
        "path", "process", "sequence", "steps", "workflow",
        "comportamiento", "detalles", "flujo", "mecanismo", "parte",
        "pasos", "proceso", "secuencia",
    }
    if not words & relation_words:
        return False
    # A complete interrogative introduces its own predicate and must remain
    # standalone even if some of its nouns appeared in the previous answer.
    if words & {
        "can", "could", "did", "do", "does", "how", "is", "should",
        "what", "when", "where", "which", "who", "why", "would",
        "como", "cómo", "cuando", "cuándo", "cual", "cuál", "donde",
        "dónde", "por", "que", "qué", "quien", "quién",
    }:
        return False
    topic_words = words - relation_words - {
        "a", "an", "and", "de", "del", "el", "la", "of", "the", "y",
    }
    if not topic_words:
        return False
    previous_answer = next(
        (content for role, content in reversed(history) if role == "assistant"),
        "",
    )
    return bool(topic_words & set(_normalized_words(previous_answer)))


_ANCHOR_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:[_-][A-Z0-9]+)*\b")
_SECTION_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def conversation_anchor_terms(
    history: Iterable[tuple[str, str]], question: str, *, limit: int = 6
) -> tuple[str, ...]:
    """Identifiers a follow-up is asking about, taken from the last answer.

    Follow-up resolution carries a *subject* forward but not the terms the
    previous answer introduced. "what is MC, MP here" is answerable only if
    retrieval can reach the section that defines those codes, and two bare
    two-letter tokens carry no signal on their own -- the live trace showed that
    request retrieving twelve weakly related documents and refusing.

    Two kinds of anchor are returned: codes the question and the previous answer
    both name, and section identifiers the previous answer cited. A completed
    assistant turn has already passed citation and grounding, so its identifiers
    are safe to retrieve on -- which is why the caller may use these without
    _safe_query_variant, unlike a model-generated variant.
    """

    answer = next(
        (
            content
            for role, content in reversed(list(history))
            if role == "assistant" and str(content).strip()
        ),
        "",
    )
    if not answer:
        return ()
    answer_tokens = list(dict.fromkeys(_ANCHOR_TOKEN.findall(str(answer))))
    asked = set(_ANCHOR_TOKEN.findall(str(question)))
    shared = [token for token in answer_tokens if token in asked]
    sections = [token for token in answer_tokens if _SECTION_ID.fullmatch(token)]
    return tuple(dict.fromkeys([*shared, *sections]))[:limit]


def _complete_explicit_question(value: str) -> bool:
    """Return whether a turn supplies its own predicate and non-referential topic."""

    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    if re.search(
        r"\b(?:it|its|that|this|these|those|their|them|same|above|previous|"
        r"here|earlier|previously|"
        r"eso|esto|esa|ese|esos|esas|mismo|misma|anterior|"
        r"aqui|aqu\u00ed|arriba)\b",
        normalized,
    ):
        return False
    complete_interrogative = re.match(
        r"^(?:how|what|when|where|which|who|why|como|cómo|que|qué|cuando|"
        r"cuándo|donde|dónde|cual|cuál|quien|quién)\b.{0,80}\b(?:am|are|can|"
        r"could|did|do|does|is|should|was|were|would|es|son|esta|está|estan|"
        r"están|puede|pueden|hace|hacen)\b",
        normalized,
    )
    # A request that names its own subject is a new topic, whatever verb opens
    # it. This list used to hold eight verbs, so "Give me the flow for checking a
    # price for leche" fell through to the vocabulary test below, was classed as
    # a follow-up, and inherited the previous turn's entity -- which then scoped
    # every retrieved document to that entity and discarded the ones that could
    # have answered it. The pronoun guard above still keeps genuine follow-ups
    # ("give me the same answer", "tell me more about that") out of here.
    explicit_imperative = re.match(
        r"^(?:describe|explain|summarize|summarise|define|document|outline|"
        r"detail|give|show|tell|list|provide|share|walk|name|find|get|"
        r"i\s+(?:need|want)|"
        r"explica|explicame|expl\u00edcame|resume|detalla|documenta|dame|dime|"
        r"muestra|muestrame|mu\u00e9strame|enumera|lista|comparte|indica|"
        r"cuentame|cu\u00e9ntame|proporciona|necesito|quiero)"
        r"\s+(?!(?:(?:me|us|nos)\s+)?(?:more|further|again|m\u00e1s|mas)\b)",
        normalized,
    )
    return bool(complete_interrogative or explicit_imperative)


def _conversation_resolution_needed(
    question: str, vocabulary: Iterable[str] | None = None
) -> bool:
    """Detect short anaphoric follow-ups without calling a model for direct questions."""

    return _conversation_resolution_decision(question, vocabulary)[0]


def _conversation_resolution_decision(
    question: str, vocabulary: Iterable[str] | None = None
) -> tuple[bool, str]:
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
        "here",
        "earlier",
        "previously",
        "aqui",
        "aqu\u00ed",
        "arriba",
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
    # Accent-insensitive as well: people type "dime mas" and "que mas" far more
    # often than "dime más". Matching only the accented form made every Spanish
    # follow-up prefix a coin flip on the user's keyboard.
    if normalized.startswith(followup_prefixes) or fold(normalized).startswith(
        tuple(fold(prefix) for prefix in followup_prefixes)
    ):
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
        # Same set in Spanish, so an elliptical request behaves identically in
        # both languages rather than only being caught in English.
        "aclara", "compara", "continua", "contin\u00faa", "describe", "detalla",
        "elabora", "explica", "amplia", "ampl\u00eda", "dame", "ayuda",
        "incluye", "lista", "necesito", "proporciona", "muestra", "dime",
        "usa", "quiero",
    }
    if (
        0 < len(normalized.split()) < 8
        and words & short_followup_verbs
        and not _conversation_subject(question)
    ):
        return True, "SHORT_VERB_ELLIPSIS"
    # A turn that opens with a bare preposition carries the previous
    # predicate: "from the product types" is the tail of the question already
    # asked, not a new one. The topic-word test below counts "product" and
    # "types" as two fresh subjects and returns EXPLICIT_SUBJECT, which drops
    # the conversation and retrieves on a fragment no document answers.
    # Bounded to short fragments that carry no interrogative and no finite verb
    # of their own, so "from the product types, what is MC?" and "de acuerdo
    # con la politica, cual es el limite?" stay standalone.
    leading = _normalized_words(normalized)[:1]
    if (
        leading
        and leading[0] in _CONTINUATION_LEADING_WORDS
        and len(normalized.split()) <= _MAX_CONTINUATION_FRAGMENT_WORDS
        and not words & _INDEPENDENT_PREDICATE_WORDS
    ):
        return True, "LEADING_FRAGMENT_CONTINUATION"
    topic_words = words - pronouns - {
        "a", "an", "and", "are", "be", "do", "does", "explain", "for", "how",
        "is", "know", "me", "of", "please", "tell", "the", "to", "what", "you",
        "implemented", "implementation", "funciona", "funcion", "como", "que", "sabes",
        # Spanish function words. Without these a Spanish question keeps its
        # articles and prepositions as "topic words", which changes whether it
        # looks like a fresh subject and therefore whether it inherits the
        # previous one.
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
        "al", "para", "por", "con", "sobre", "es", "son", "esta", "estan",
        "cual", "cuales", "cuando", "donde", "quien", "y", "o", "en", "lo",
        "se", "su", "sus", "dame", "dime", "muestra", "muestrame", "necesito",
        "quiero", "explica", "describe", "resume",
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
        if _complete_explicit_question(normalized):
            return False, "EXPLICIT_SUBJECT"
        # A multiword topic supplies enough subject of its own even when none
        # of its nouns appear in the project vocabulary.  Keep one-word
        # fragments conservative: they may still be elliptical references to
        # the active subject.  Explicit referential forms have already returned
        # through the dedicated guards above.
        if len(topic_words) >= 2 and not words & pronouns:
            return False, "EXPLICIT_SUBJECT"
        if vocabulary is not None and not _subject_matches_vocabulary(
            " ".join(topic_words), vocabulary
        ):
            return True, "NON_VOCABULARY_SUBJECT"
        return False, "EXPLICIT_SUBJECT"
    if words & pronouns:
        return True, "ANAPHORIC_PRONOUN"
    return False, "NO_FOLLOWUP_SIGNAL"


# A question fragment that begins with one of these has no predicate of its own.
_CONTINUATION_LEADING_WORDS = frozenset({
    "from", "for", "about", "with", "within", "under", "regarding", "concerning",
    "de", "del", "para", "por", "sobre", "con", "desde", "segun", "respecto",
    "acerca",
})

# An interrogative or finite verb makes a fragment a question in its own right,
# whatever preposition opens it. Accent-stripped: _normalized_words folds
# diacritics, so "cual" here also matches "cuál".
_INDEPENDENT_PREDICATE_WORDS = frozenset({
    "how", "what", "when", "where", "which", "who", "whom", "whose", "why",
    "am", "are", "be", "can", "could", "did", "do", "does", "had", "has",
    "have", "is", "may", "must", "should", "was", "were", "will", "would",
    "como", "cuando", "cual", "cuales", "donde", "que", "quien", "quienes",
    "es", "son", "esta", "estan", "estuvo", "fue", "fueron", "hace", "hacen",
    "hay", "podria", "puede", "pueden", "sera", "seran", "tiene", "tienen",
})

_MAX_CONTINUATION_FRAGMENT_WORDS = 6


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


def _conversation_context_subject(
    original: str,
    resolved: str,
    existing: str,
    vocabulary: Iterable[str],
) -> tuple[str, bool]:
    """Keep an active entity across attribute follow-ups without trusting chat as evidence."""

    known = tuple(vocabulary)
    is_followup = _conversation_resolution_decision(original, known or None)[0]
    explicit = _conversation_subject(original)
    if is_followup and explicit and known and not _subject_matches_vocabulary(
        explicit, known
    ):
        explicit = ""
    carried = _resolved_conversation_subject(resolved)
    subject = (
        carried or _conversation_subject(existing) or existing
        if is_followup and not explicit
        else explicit
    )
    return subject or carried or existing, is_followup


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


def build_conversation_context_update(request, state, vocabulary):
    """Build semantic conversation memory independently of graph composition."""
    from app.models import ConversationContextUpdate, ConversationEntity

    original = request.question
    resolved = state.get("resolved_question", original)
    subject, is_followup = _conversation_context_subject(
        original, resolved, request.conversation_context.active_subject.strip(), vocabulary
    )
    return ConversationContextUpdate(
        standaloneQuestion=resolved,
        activeSubject=subject,
        entities=[ConversationEntity(value=subject, canonicalValue=subject)] if subject else [],
        intent=state.get("query_intent", ""),
        resolutionConfidence=1.0 if resolved != original or not is_followup else 0.5,
    )

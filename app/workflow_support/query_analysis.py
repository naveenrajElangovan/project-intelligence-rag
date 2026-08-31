from __future__ import annotations

from pathlib import Path
import re
import unicodedata

from langchain_core.documents import Document

from app.llm import GroundedAnswer, TokenUsage
from app.lexical_tokens import subtokens
from app.workflow_support.identifiers import member_identifiers

def detect_query_language(value: str) -> str:
    lowered = f" {value.lower()} "
    spanish = sum(
        lowered.count(f" {word} ")
        for word in ("el", "la", "de", "que", "para", "cómo", "cual", "estado", "sobre")
    )
    english = sum(
        lowered.count(f" {word} ")
        for word in (
            "the",
            "of",
            "that",
            "for",
            "how",
            "what",
            "status",
            "tell",
            "about",
            "describe",
            "explain",
            "overview",
            "list",
            "all",
            "every",
            "feature",
            "features",
            "have",
        )
    )
    if spanish > english or re.search(r"[áéíóúñ¿¡]", lowered):
        return "es"
    if english > spanish:
        return "en"
    return "mixed"


def _identifiers(value: str) -> set[str]:
    patterns = (
        r"[A-Z][A-Z0-9]+-\d+",
        r"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+\b",
        r"\b[A-Za-z][A-Za-z0-9_-]*::[A-Za-z0-9_:.-]+\b",
        r"\b[A-Z][A-Z0-9_.-]*\d[A-Z0-9_.-]*\b",
        r"['\"][^'\"]+['\"]",
    )
    return {match.group(0) for pattern in patterns for match in re.finditer(pattern, value)}


def _safe_query_variant(original: str, candidate: str) -> bool:
    if len(candidate) < 2 or len(candidate) > 4000 or candidate == original.strip():
        return False
    return _identifiers(candidate).issubset(_identifiers(original))


def _multi_part_question(value: str) -> bool:
    """Detect questions that benefit from independent retrieval formulations."""

    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    if len(_normalized_words(normalized)) < 8:
        return False
    return bool(
        re.search(r"[;]|\b(?:compare|versus|vs\.?|difference between|diferencia entre)\b", normalized)
        or len(re.findall(r"\b(?:and|also|as well as|y|también)\b", normalized)) >= 2
        or len(re.findall(r"\b(?:what|how|which|where|when|qué|cómo|cuál|dónde|cuándo)\b", normalized)) >= 2
    )


def _query_quality(value: str) -> tuple[str, str]:
    """Classify query shape without forcing a rewrite for good questions."""

    words = _normalized_words(value)
    if len(words) < 2:
        return "WEAK", "TOO_SHORT"
    generic = {
        "why", "what", "how", "when", "where", "tell", "explain", "more",
        "details", "please", "help", "it", "that", "this", "something",
    }
    meaningful = [word for word in words if word not in generic]
    if not meaningful:
        return "WEAK", "NO_TOPIC"
    if len(meaningful) == 1 and len(words) <= 4:
        return "AMBIGUOUS", "SINGLE_TOPIC"
    return "GOOD", "SUFFICIENT_TOPIC"


def _code_location_query(value: str) -> bool:
    """Recognize source-location questions that benefit from query expansion."""

    normalized = " ".join(_normalized_words(value))
    asks_location = bool(
        re.search(
            r"\b(?:which|what)\s+(?:(?:source|github|repository)\s+)?"
            r"(?:files?|code|classes?|methods?|functions?)\b|\bwhere\b",
            normalized,
        )
    )
    implementation_terms = bool(
        re.search(
            r"\b(?:implemented|implementation|located|contains?|defines?|"
            r"functionality|screen|home|main|entry|flow|feature|logic|code|"
            r"implementado|ubicado|pantalla|inicio|principal|funcionalidad)\b",
            normalized,
        )
    )
    return asks_location and implementation_terms


def _exact_terms(value: str) -> set[str]:
    identifiers = _identifiers(value)
    quoted = {item.strip("'\"") for item in identifiers}
    technical = set(re.findall(r"\b[A-Za-z][A-Za-z0-9_.:/-]*\d[A-Za-z0-9_.:/-]*\b", value))
    members = set(member_identifiers(value))
    exact = {item.lower() for item in quoted | technical | members if len(item) >= 2}
    # A question naming a constant ending in `_EVENT` can ask about the same thing
    # as a page that omits the suffix. Counting the identifier's parts as
    # exact terms lets the boost fire on that page instead of only on a verbatim
    # repeat of the constant, which the documentation rarely contains.
    for item in list(exact):
        exact.update(subtokens(item))
    return exact


def _exact_term_ratio(terms: set[str], content: str) -> float:
    if not terms:
        return 0.0
    lowered = content.lower()
    return sum(term in lowered for term in terms) / len(terms)


def _add_usage(first: TokenUsage, second: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cached_tokens=first.cached_tokens + second.cached_tokens,
        reasoning_tokens=first.reasoning_tokens + second.reasoning_tokens,
        retry_count=first.retry_count + second.retry_count,
    )


def _dedupe_source_documents(documents: list[Document]) -> list[Document]:
    unique: dict[tuple[str, str, str], Document] = {}
    for document in documents:
        identity = (
            str(document.metadata.get("source_type") or "DOCUMENT"),
            str(document.metadata.get("reference") or ""),
            str(document.metadata.get("source_url") or ""),
        )
        unique.setdefault(identity, document)
    return list(unique.values())


def _source_diverse_order(documents: list[Document]) -> list[Document]:
    """Place the best chunk from each source before secondary chunks."""

    primary: list[Document] = []
    secondary: list[Document] = []
    seen_sources: set[str] = set()
    for document in documents:
        source_id = _source_identity(document)
        if source_id in seen_sources:
            secondary.append(document)
        else:
            seen_sources.add(source_id)
            primary.append(document)
    return [*primary, *secondary]


def _implementation_evidence_order(
    documents: list[Document], question: str = "", code_extensions: tuple[str, ...] = ()
) -> list[Document]:
    """Prefer executable/configuration files over repository prose for code questions."""

    implementation_suffixes = frozenset(code_extensions)
    generic_query_words = {
        "a",
        "able",
        "can",
        "code",
        "github",
        "in",
        "of",
        "see",
        "source",
        "the",
        "to",
        "which",
        "you",
    }
    query_words = set(_normalized_words(question)) - generic_query_words
    query_words.update(
        word[:-1] for word in tuple(query_words) if len(word) > 3 and word.endswith("s")
    )

    def ordering_key(document: Document) -> tuple[bool, int]:
        path = str(document.metadata.get("path") or document.metadata.get("title") or "")
        searchable = " ".join(
            (
                path,
                str(document.metadata.get("symbol") or ""),
                document.page_content,
            )
        )
        # Split CamelCase identifiers so a natural-language term such as "speed"
        # matches ObserveSpeedUseCase and SpeedometerGauge metadata.
        searchable = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", searchable)
        lexical_matches = len(query_words & set(_normalized_words(searchable)))
        return (
            Path(path).suffix.casefold() not in implementation_suffixes,
            -lexical_matches,
        )

    return sorted(documents, key=ordering_key)


def _inventory_documents(documents: list[Document], entity: str) -> list[Document]:
    """Keep one evidence item per entity feature page, grounded by its title."""

    inventory: list[Document] = []
    seen_titles: set[str] = set()
    for document in documents:
        title = str(document.metadata.get("title") or "").strip()
        if not _is_feature_document(document, entity):
            continue
        normalized_title = " ".join(_normalized_words(title))
        if normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)
        inventory.append(
            Document(
                page_content=f"Indexed feature document title: {title}",
                metadata=dict(document.metadata),
            )
        )
    return inventory


def _is_feature_document(document: Document, entity: str) -> bool:
    """Use ingestion-owned classification instead of a title convention."""

    return bool(
        entity
        and str(document.metadata.get("entity") or "").casefold() == entity.casefold()
        and str(document.metadata.get("doc_category") or "").casefold()
        in {"feature-page", "feature"}
    )


_GENERIC_TITLE_WORDS = {
    "documentation",
    "document",
    "documents",
    "doc",
    "docs",
    "page",
    "feature",
}

_ENTITY_OVERVIEW_FILLER_WORDS = {
    "a",
    "about",
    "acerca",
    "an",
    "application",
    "aplicacion",
    "describe",
    "dime",
    "do",
    "does",
    "el",
    "es",
    "explain",
    "give",
    "good",
    "hablame",
    "hello",
    "hey",
    "hi",
    "informacion",
    "information",
    "la",
    "me",
    "overview",
    "now",
    "proyecto",
    "please",
    "qu",
    "que",
    "sobre",
    "sabes",
    "conoces",
    "cuentame",
    "de",
    "del",
    "resumen",
    "tell",
    "the",
    "un",
    "una",
    "what",
    "is",
    "evening",
    "know",
    "you",
}


def _normalized_words(value: str) -> tuple[str, ...]:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return tuple(re.findall(r"[a-z0-9]+", folded))


def _source_route_intent(
    question: str, available_source_types: tuple[str, ...] = ()
) -> str:
    """Classify only the source authority needed; never create answer content."""

    normalized = " ".join(_normalized_words(question))
    # A specific work-item signal wins over generic words such as configuration
    # or implementation that commonly occur in ticket titles.
    if re.search(
        r"\b(?:jira|tickets?|issues?|bugs?|sprints?|statuses|status|delivery|"
        r"releases?|priority|priorities|estado|entrega|incidencias?|errores?|"
        r"prioridad(?:es)?)\b",
        normalized,
    ):
        return "DELIVERY"
    cross_source_signal = re.search(
        r"\b(?:compare|compares|comparison|versus|vs|match|matches|align|alignment|"
        r"differ|differs|difference|architecture|architectural|compara|comparar|"
        r"comparacion|contra|coincide|alineacion|diferencia|arquitectura)\b",
        normalized,
    )
    source_types = {value.upper() for value in available_source_types}
    if cross_source_signal and (
        not source_types or {"PAGE", "CODE"} <= source_types
    ):
        return "CROSS_SOURCE"
    if re.search(
        r"\b(?:implement|implemented|implementation|code|source code|github|repository|"
        r"class|classes|function|functions|file|files|path|paths|package|"
        r"packages|module|modules|test|tests|configuration|config|dependency|implementa|"
        r"implementado|implementacion|codigo|repositorio|clase|clases|funcion|funciones|"
        r"archivo|archivos|ruta|rutas|paquete|paquetes|modulo|modulos|"
        r"prueba|pruebas|configuracion|dependencia)\b",
        normalized,
    ):
        return "IMPLEMENTATION"
    # All other project questions inspect documentation and code independently.
    return "CODE_ASSISTED"


def _intent_source_scope(intent: str) -> tuple[tuple[str, ...], str]:
    return {
        # Code maps and implementation inventories may live in project pages even
        # when the mapped repository covers a different application.
        "IMPLEMENTATION": (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        "CODE_ASSISTED": (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        "DELIVERY": (("ISSUE",), "JIRA"),
        "CROSS_SOURCE": (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        # Documentation lives only in Confluence; the repositories carry code and
        # nothing else. These two intents answer *about* the documentation -- what
        # a product is, which features are documented -- so admitting CODE gave
        # source files a chance to win reranked slots from the pages that are the
        # actual subject, and to be cited as if they documented anything. Both
        # already required PAGE evidence downstream; scoping the retrieval to
        # match means a project with no pages says so instead of answering from
        # source it should not be reading.
        "ENTITY_OVERVIEW": (("PAGE",), "CONFLUENCE"),
        "FEATURE_INVENTORY": (("PAGE",), "CONFLUENCE"),
    }.get(intent, ((), "MIXED"))


def _required_evidence_source_types(intent: str) -> tuple[str, ...]:
    return {
        "CODE_INVENTORY": ("CODE",),
        "DELIVERY": ("ISSUE",),
        "CROSS_SOURCE": ("PAGE", "CODE"),
        "FEATURE_INVENTORY": ("PAGE",),
        "ENTITY_OVERVIEW": ("PAGE",),
    }.get(intent, ())


def _document_source_type(document: Document) -> str:
    return str(document.metadata.get("source_type") or "").upper()


def _source_type_count(documents: list[Document], source_type: str) -> int:
    return sum(_document_source_type(document) == source_type for document in documents)


def _source_authority_valid(
    intent: str, generated: GroundedAnswer, documents: list[Document]
) -> tuple[bool, str]:
    cited_types = {
        _document_source_type(documents[index - 1])
        for index in generated.citations
        if 1 <= index <= len(documents)
    }
    if intent == "IMPLEMENTATION":
        valid = bool(cited_types) and cited_types <= {"PAGE", "CODE"}
        return valid, "CODE_AUTHORITY_VERIFIED" if valid else "CODE_AUTHORITY_REQUIRED"
    if intent in {"FUNCTIONAL", "FEATURE_INVENTORY", "ENTITY_OVERVIEW"}:
        valid = bool(cited_types) and cited_types <= {"PAGE"}
        return valid, "PAGE_AUTHORITY_VERIFIED" if valid else "PAGE_AUTHORITY_REQUIRED"
    if intent == "CODE_ASSISTED":
        valid = bool(cited_types) and cited_types <= {"PAGE", "CODE"}
        return valid, "PROJECT_AUTHORITY_VERIFIED" if valid else "PROJECT_AUTHORITY_REQUIRED"
    if intent == "DELIVERY":
        valid = bool(cited_types) and cited_types <= {"ISSUE"}
        return valid, "ISSUE_AUTHORITY_VERIFIED" if valid else "ISSUE_AUTHORITY_REQUIRED"
    if intent == "CROSS_SOURCE":
        valid = {"PAGE", "CODE"} <= cited_types
        return valid, "CROSS_SOURCE_VERIFIED" if valid else "CROSS_SOURCE_EVIDENCE_REQUIRED"
    return True, "SOURCE_AUTHORITY_NOT_REQUIRED"


def _entity_overview_entity(question: str, entities: tuple[str, ...] = ()) -> str:
    """Return a bounded product entity only for broad overview questions."""

    words = _normalized_words(question)
    matches = {word for word in words if word in frozenset(entities)}
    if len(matches) != 1:
        return ""
    entity = next(iter(matches))
    remaining = [
        word
        for word in words
        if word != entity and word not in _ENTITY_OVERVIEW_FILLER_WORDS
    ]
    has_overview_phrase = bool(
        re.search(
            r"\b(?:tell\s+me\s+about|what\s+(?:is|does)|what\s+(?:do\s+)?you\s+know\s+about|"
            r"explain|describe|overview|"
            r"informacion\s+sobre|que\s+es|que\s+sabes\s+(?:de|del|sobre)|"
            r"que\s+conoces\s+(?:de|del|sobre)|hablame\s+(?:de|del|sobre)|"
            r"cuentame\s+(?:de|del|sobre)|dime\s+(?:de|del|sobre))\b",
            " ".join(words),
        )
    )
    is_short_entity_request = len(words) <= 4
    return entity if not remaining and (has_overview_phrase or is_short_entity_request) else ""


def _feature_inventory_entity(question: str, entities: tuple[str, ...] = ()) -> str:
    """Recognize an exhaustive feature-list request for a discovered entity."""

    words = _normalized_words(question)
    matches = {word for word in words if word in frozenset(entities)}
    if len(matches) != 1:
        return ""
    normalized = " ".join(words)
    asks_for_features = bool(
        re.search(
            r"\b(?:features?|functionalities|functions?|modules?|capabilities|"
            r"caracteristicas|funcionalidades|funciones|modulos|capacidades)\b",
            normalized,
        )
    )
    asks_for_exhaustive_list = bool(
        re.search(
            r"\b(?:all|every|complete|full|entire|list|enumerate|todos|todas|"
            r"completa|completo|lista|listar|enumera|enumerar)\b",
            normalized,
        )
    )
    return next(iter(matches)) if asks_for_features and asks_for_exhaustive_list else ""


def _code_inventory_requested(question: str) -> bool:
    normalized = " ".join(_normalized_words(question))
    exhaustive = bool(
        re.search(
            r"\b(?:all|every|complete|full|entire|list|enumerate|todos|todas|"
            r"completa|completo|lista|listar|enumera|enumerar)\b",
            normalized,
        )
    )
    code_subject = bool(
        re.search(
            r"\b(?:code|files?|classes|functions?|methods?|paths?|packages?|modules?|tests?|"
            r"configuration|codigo|archivos?|clases|funciones?|metodos?|rutas?|paquetes?|"
            r"modulos?|pruebas?|configuracion)\b",
            normalized,
        )
    )
    return exhaustive and code_subject


def _project_overview_requested(question: str, project_id: str) -> bool:
    """Recognize only broad requests for the authorized project as a whole."""

    lowered = " ".join(_normalized_words(question))
    project_mentioned = (
        bool({"project", "proyecto"} & set(_normalized_words(lowered)))
        or "this project" in lowered
        or "este proyecto" in lowered
        or _normalized_identifier(project_id) in lowered
    )
    overview_phrase = bool(
        re.search(
            r"\b(?:what\s+do\s+you\s+know\s+about|tell\s+me\s+about|"
            r"describe|explain|project\s+overview|overview\s+of|what\s+is|"
            r"que\s+sabes\s+(?:de|del|sobre)|que\s+conoces\s+(?:de|del|sobre)|"
            r"hablame\s+(?:de|del|sobre)|cuentame\s+(?:de|del|sobre)|"
            r"dime\s+(?:de|del|sobre)|que\s+es|resumen\s+(?:de|del))\b",
            lowered,
        )
    )
    specific_scope = bool(
        re.search(
            r"\b(?:status|ticket|issue|bug|file|class|function|count|line|test|"
            r"payment|cash|shift|login|funding|estado|incidencia|error|archivo|"
            r"clase|funcion|conteo|linea|prueba|pago|efectivo|turno|"
            r"inicio\s+de\s+sesion|financiamiento)\b",
            lowered,
        )
    )
    return project_mentioned and overview_phrase and not specific_scope and len(_normalized_words(lowered)) <= 14


def _normalized_identifier(value: str) -> str:
    return " ".join(_normalized_words(value))


def _low_information_project_document(document: Document) -> bool:
    content = re.sub(r"\s+", " ", document.page_content).strip()
    marked = document.metadata.get("low_information")
    score = document.metadata.get("information_score")
    return not content or marked is True or (
        isinstance(score, (int, float)) and float(score) <= 0
    )


def _project_overview_topic(document: Document) -> str:
    entity = str(document.metadata.get("entity") or "").casefold()
    category = str(document.metadata.get("doc_category") or "narrative").casefold()
    return f"entity:{entity}" if entity else f"category:{category}"


def _project_overview_evidence_order(documents: list[Document]) -> list[Document]:
    """Round-robin discovered entities and document categories."""

    buckets: dict[str, list[Document]] = {}
    for document in _source_diverse_order(documents):
        if not _low_information_project_document(document):
            buckets.setdefault(_project_overview_topic(document), []).append(document)
    ordered: list[Document] = []
    while any(buckets.values()):
        for values in buckets.values():
            if values:
                ordered.append(values.pop(0))
    return ordered


def _overview_repair_kwargs(query_intent: str) -> dict[str, str]:
    if query_intent == "PROJECT_OVERVIEW":
        return {"answer_style": "project_overview"}
    if query_intent == "ENTITY_OVERVIEW":
        return {"answer_style": "entity_overview"}
    if query_intent == "FEATURE_INVENTORY":
        return {"answer_style": "feature_inventory"}
    if query_intent == "IMPLEMENTATION":
        return {"answer_style": "implementation"}
    if query_intent == "DELIVERY":
        return {"answer_style": "delivery"}
    if query_intent == "CODE_ASSISTED":
        return {"answer_style": "code_assisted"}
    if query_intent == "CROSS_SOURCE":
        return {"answer_style": "cross_source"}
    return {}


def _source_identity(document: Document) -> str:
    return str(
        document.metadata.get("source_id")
        or document.metadata.get("reference")
        or document.metadata.get("parent_id")
        or document.metadata.get("chunk_id")
    )


def _feature_title_anchor(title: str, entity: str = "") -> tuple[str, ...]:
    words = list(_normalized_words(title))
    while words and words[-1] in _GENERIC_TITLE_WORDS:
        words.pop()
    for index, word in enumerate(words):
        if entity and word == entity.casefold():
            return tuple(words[index:])
    return ()


def _contains_ordered_phrase(words: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    if not phrase or len(phrase) > len(words):
        return False
    return any(words[index : index + len(phrase)] == phrase for index in range(len(words) - len(phrase) + 1))


def _exact_feature_title_match(question: str, document: Document) -> bool:
    anchor = _feature_title_anchor(
        str(document.metadata.get("title") or ""),
        str(document.metadata.get("entity") or ""),
    )
    question_words = _normalized_words(question)
    # Natural questions often place filler words between an application and its
    # feature ("the app has the close shift"). Ordered term presence keeps the match
    # specific without requiring the user to repeat an exact page title.
    cursor = 0
    for word in question_words:
        if cursor < len(anchor) and word == anchor[cursor]:
            cursor += 1
    return len(anchor) >= 2 and cursor == len(anchor)


def _exact_feature_source_ids(question: str, documents: list[Document]) -> set[str]:
    title_matches = [
        (
            _feature_title_anchor(
                str(document.metadata.get("title") or ""),
                str(document.metadata.get("entity") or ""),
            ),
            document,
        )
        for document in documents
        if _exact_feature_title_match(question, document)
    ]
    longest_anchor = max((len(anchor) for anchor, _document in title_matches), default=0)
    return {
        _source_identity(document)
        for anchor, document in title_matches
        if len(anchor) == longest_anchor
    }


def _entity_overview_source_ids(entity: str, documents: list[Document]) -> set[str]:
    """Keep only sources explicitly classified for the requested entity."""

    return {
        _source_identity(document)
        for document in documents
        if _feature_title_anchor(
            str(document.metadata.get("title") or ""),
            str(document.metadata.get("entity") or ""),
        )[:1]
        == (entity,)
    }

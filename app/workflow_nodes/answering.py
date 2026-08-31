from __future__ import annotations

import math
import re

from langgraph.config import get_stream_writer

from app.llm import BilingualQueryPlanner, GroundedAnswer, TokenUsage, answer_sentence_floor
from app.telemetry import stage_complete, started
from app.table_evidence import contains_table
from app.workflow_nodes.state import RagState
from app.workflow_support.citations import (
    _citation_failure_reason,
    drop_uncited_claims,
    _citations_valid,
    _material_sentence_count,
    _normalize_citations,
    _overview_style_repair_needed,
    _remove_unsupported_claims,
)
from app.workflow_support.answer_structure import (
    AnswerLineKind,
    answer_shape_metrics,
    classify_answer_lines,
    material_claims,
)
from app.workflow_support.inventory_intent import is_inventory_question
from app.workflow_support.identifiers import member_identifiers
from app.workflow_support.filtering import preserve_non_empty
from app.workflow_support.completeness import (
    _answer_requirements,
    _completeness_repair_query,
    _include_repair_evidence,
    _merge_ranked_documents,
    _missing_answer_requirements,
)
from app.workflow_support.deterministic_answers import (
    _code_inventory_answer_verified,
    _deterministic_code_inventory_answer,
    _deterministic_code_location_answer,
    _deterministic_delivery_answer,
    _deterministic_feature_inventory_answer,
    _deterministic_identifier_answer,
    _deterministic_structured_inventory_answer,
    _feature_inventory_answer_verified,
)
from app.workflow_support.query_analysis import (
    _add_usage,
    _overview_repair_kwargs,
    _safe_query_variant,
    _source_authority_valid,
)


_ENTITY_STOP_WORDS = {
    "all",
    "application",
    "app",
    "code",
    "current",
    "details",
    "project",
    "repository",
    "service",
    "shortcuts",
    "system",
    "the",
}


def _normalized_entity(value: object) -> str:
    entity = re.sub(r"[^a-z0-9_-]+", "", str(value).strip().casefold())
    return entity.removesuffix("3b")


def _explicit_entity_scope(question: str, entities: tuple[str, ...] = ()) -> str:
    """Extract a user-named application/repository present in corpus vocabulary."""

    known_entities = {_normalized_entity(entity) for entity in entities}
    known_entities.discard("")
    patterns = (
        r"\b([A-Za-z][A-Za-z0-9_-]{1,40})\s+(?:application|app|repository|service)\b",
        r"\b(?:in|for|from|about|of|by)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_-]{1,40})(?:\s+(?:application|app|repository|service))?\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, question, flags=re.IGNORECASE):
            candidate = _normalized_entity(match.group(1))
            if candidate in known_entities:
                return candidate
    mentioned = {
        entity
        for entity in known_entities
        if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(entity)}(?![A-Za-z0-9_])",
            question,
            flags=re.IGNORECASE,
        )
    }
    if len(mentioned) == 1:
        return next(iter(mentioned))
    return ""


def _list_response_requested(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", question).strip().casefold()
    return bool(
        re.search(
            r"\b(?:list|listado|lista|enumerate|enumerar|all|every|each|todos|todas|cada)\b",
            normalized,
        )
    )


def _structured_tabular_evidence(documents: list[object]) -> bool:
    """Detect tabular answer shape from evidence, independent of planner intent."""

    return any(
        str(getattr(document, "metadata", {}).get("doc_category") or "").casefold()
        in {"entity-contract", "registry-table"}
        or contains_table(str(getattr(document, "page_content", "")))
        for document in documents
    )


def _attribute_table_requested(question: str) -> bool:
    """Return whether the user asked for member-level or attribute-level data."""

    return bool(
        re.search(
            r"\b(?:field|fields|parameter|parameters|payload|attribute|attributes|"
            r"property|properties|schema|columns?|values?|enum|contract)\b",
            question,
            flags=re.IGNORECASE,
        )
    )


def _comparison_subjects(
    question: str, entities: tuple[str, ...]
) -> tuple[str, ...]:
    """Resolve explicit comparison subjects without inventing project concepts."""

    identifiers = member_identifiers(question)
    if len(identifiers) >= 2:
        return identifiers

    normalized_entities = tuple(
        dict.fromkeys(
            entity
            for raw_entity in entities
            if (entity := _normalized_entity(raw_entity))
            and re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(entity)}(?![A-Za-z0-9_])",
                question,
                flags=re.IGNORECASE,
            )
        )
    )
    if len(normalized_entities) >= 2:
        return normalized_entities

    source_families = tuple(
        label
        for label, pattern in (
            ("PAGE", r"\b(?:page|pages|documentation|docs|confluence)\b"),
            ("CODE", r"\b(?:code|implementation|github|repository)\b"),
            ("ISSUE", r"\b(?:issue|issues|jira|ticket|tickets)\b"),
        )
        if re.search(pattern, question, flags=re.IGNORECASE)
    )
    return source_families if len(source_families) >= 2 else ()


def _enforce_table_claim_shape(
    generated: GroundedAnswer, answer_style: str
) -> tuple[GroundedAnswer, int]:
    """Remove format-invalid claims without changing grounding policy."""

    if answer_style not in {"structured_tabular", "comparison_table"}:
        return generated, 0
    invalid = [
        claim.text
        for claim in material_claims(generated.answer)
        if not re.search(r"\[SOURCE \d+\]", claim.text)
        or re.search(r"(?i)(?<!\w)N\s*/?\s*A(?!\w)", claim.text)
    ]
    if not invalid:
        return generated, 0
    return _remove_unsupported_claims(generated, invalid)


# Words that describe the shape of a request rather than its subject. A label
# built from these would match every population and filter nothing.
_POPULATION_LABEL_STOP_WORDS = frozenset({
    "all", "and", "another", "any", "are", "available", "can", "complete", "configured",
    "defined", "describe", "detail", "details", "did", "do", "does", "each", "enumerate",
    "every", "exist", "existing", "explain", "for", "from", "full", "get", "give", "has",
    "have", "how", "in", "is", "its", "know", "list", "many", "me", "more", "much",
    "need", "of", "on", "one", "only", "or", "please", "provide", "remain", "show",
    "supported", "tell", "the", "their", "them", "there", "these", "this", "those",
    "to", "use", "used", "uses", "want", "was", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "you", "your",
    "todos", "todas", "cada", "dame", "lista", "listado", "muestra", "cuales", "cual",
    "que", "los", "las", "del", "para", "por", "con", "hay", "son", "tiene", "tienen",
})


def _population_labels(
    question: str, entities: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """Describe which population the question asks to enumerate.

    Numeric and version labels ("all 1xx items") were the only thing extracted
    here, so a question naming a different kind of member -- keyboard shortcuts
    rather than contracts -- produced no label at all. With no label the loader
    admitted every entity-contract chunk in the project, and the coverage contract
    then ordered the generator to enumerate that population verbatim. The answer
    listed the wrong member kind because that was the population it was handed,
    not because retrieval or grounding failed.

    Including the question's own subject words means the population has to be
    about what was asked. A question whose subject matches no population loads
    none, which drops the coverage contract and answers normally -- a graceful
    loss of the exhaustiveness guarantee rather than a confidently wrong list.
    """

    versioned = re.findall(
        r"(?i)(?<![A-Za-z0-9])(?:\d+[a-z]{1,4}|v\d+(?:\.\d+)+)(?![A-Za-z0-9])",
        question,
    )
    # The application name is already applied as its own filter by the loader.
    # Keeping it as a label as well would match every population in the project,
    # and one matching label is enough to admit a population, so it would undo
    # the filter entirely.
    entity_words = {value.strip().casefold() for value in entities if value.strip()}
    subjects: list[str] = []
    deferred_gerunds: list[str] = []
    for word in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_-]{2,}", question):
        folded = word.casefold()
        if folded in _POPULATION_LABEL_STOP_WORDS or folded in entity_words:
            continue
        # Match the singular stem so a plural request ("events") still matches a
        # population whose records are written in the singular ("Event contract").
        # Both forms are kept: stripping only the suffix turned "libraries" into
        # "librari", which matches neither "library" nor "libraries" and so
        # silently dropped the subject the question was about.
        if len(folded) > 5 and folded.endswith("ing"):
            gerund_stem = folded[:-3]
            if (
                len(gerund_stem) > 2
                and gerund_stem[-1] == gerund_stem[-2]
            ):
                gerund_stem = gerund_stem[:-1]
            # A gerund before a plural noun describes the relation, not the
            # population member kind ("sending events"). Defer it so the noun
            # becomes the primary subject while the relation remains available
            # for source matching.
            deferred_gerunds.extend((folded, gerund_stem))
            continue
        subjects.append(folded)
        if len(folded) > 4 and folded.endswith("ies"):
            subjects.append(folded[:-3] + "y")
        elif len(folded) > 4 and folded.endswith("es"):
            subjects.append(folded[:-2])
        elif len(folded) > 3 and folded.endswith("s"):
            subjects.append(folded[:-1])
    return tuple(dict.fromkeys([*versioned, *subjects, *deferred_gerunds]))


def _coverage(expected: tuple[str, ...], answer: str) -> tuple[str, ...]:
    normalized_answer = answer.casefold()
    return tuple(key for key in expected if key.casefold() not in normalized_answer)




def _member_label(value: str) -> str:
    """Return the leading identifier of a registry row or list item, else empty.

    A registry names one member per row or bullet, and the member's name leads
    the line. The member must be a *name*, not a description: verified against
    the live corpus, accepting any short leading phrase collected 166 "members"
    from one contract page, among them the column descriptions "Kotlin constant"
    and "Wire event name". A coverage contract built from those would have
    reported every answer as incomplete.

    A name is a single token -- ``ORDER_CREATED``, ``Ctrl+B``, ``F1``,
    ``some-app-kotlin``, ``Streams.ConsumerC2D``. A phrase containing whitespace
    is a description of a member, not the member. That distinction needs no
    vocabulary and holds for any corpus.
    """

    text = value.strip().strip("|").strip()
    if not text:
        return ""
    if "|" in text:
        text = text.split("|", 1)[0]
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text)
    text = text.strip().strip("`*_ ").split(":")[0].strip().rstrip(",;")
    if not text:
        return ""
    if re.search(r"\s", text) or text.endswith((".", "!", "?")):
        return ""
    # A bare number is a row ordinal, not a member name.
    if text.isdigit():
        return ""
    return text


def _subject_label_frequencies(
    documents: list[object], subject_labels: tuple[str, ...]
) -> dict[str, int]:
    """Count how many candidates carry each subject label."""

    labels = tuple(
        dict.fromkeys(label.casefold() for label in subject_labels if label)
    )
    if not labels or not documents:
        return {}
    fields = [_subject_fields(document) for document in documents]
    return {
        label: sum(
            1 for heading, body in fields if label in heading or label in body
        )
        for label in labels
    }


def _subject_label_weights(
    documents: list[object], subject_labels: tuple[str, ...]
) -> dict[str, float]:
    """Weight each subject label by how rare it is among the candidates.

    Counting label matches is not enough on its own. A question's subject words
    include generic ones -- measured across the live corpus, ``key`` and
    ``application`` occur in nine of ten sources -- so a rule that admits on any
    match hands the contract to whichever off-subject registry ranks first. A
    word every candidate contains carries no information and is weighted zero; a
    word only the right source has is decisive. No vocabulary and no
    per-question tuning.
    """

    frequencies = _subject_label_frequencies(documents, subject_labels)
    if not frequencies:
        return {}
    total = len(documents)
    # Classic inverse document frequency: a label every candidate carries weighs
    # nothing, and one no candidate carries weighs nothing either -- the second
    # case is read separately by _subject_is_evidenced, because a label nothing
    # matches is a statement about the corpus, not a weak label.
    return {
        label: math.log(total / frequency) if frequency else 0.0
        for label, frequency in frequencies.items()
    }


def _subject_label_groups(subject_labels: tuple[str, ...]) -> list[set[str]]:
    """Keep a written plural and its emitted singular stem as one concept."""

    groups: list[set[str]] = []
    for label in dict.fromkeys(value.casefold() for value in subject_labels if value):
        if groups and any(
            label in existing
            or existing in label
            or (existing.endswith("y") and label.endswith("ies"))
            or (label.endswith("y") and existing.endswith("ies"))
            for existing in groups[-1]
        ):
            groups[-1].add(label)
        else:
            groups.append({label})
    return groups


def _required_subject_labels(
    frequencies: dict[str, int], subject_labels: tuple[str, ...]
) -> set[str]:
    """Choose the first evidenced subject concept, not a rarer trailing noun.

    In "shortcut keys", ``keys`` can be rarer than ``shortcut`` because the
    registry calls its column ``Shortcut``. Treating raw IDF as semantic
    importance therefore selects an incidental "Arrow keys" controls table.
    Question order identifies the compound's specific subject, while frequencies
    still skip words absent from the evidence. Morphological variants are one
    concept, so ``events`` and ``event`` cannot disagree about presence.
    """

    for group in _subject_label_groups(subject_labels):
        if any(frequencies.get(label, 0) for label in group):
            return group
    return set()


def _subject_is_evidenced(
    documents: list[object], subject_labels: tuple[str, ...]
) -> bool:
    """Return whether the asked-for subject appears in the candidates at all.

    Zero weight has two very different causes. A label every candidate carries
    ("key") is uninformative. A label *no* candidate carries ("shortcut") means
    the thing asked about is not in the retrieved evidence -- and if the only
    labels that did match are the uninformative ones, then nothing here is about
    the question. Forming a population in that situation is what answered a
    shortcut question with the event registry: one weak word admitted the whole
    wrong registry, and the coverage contract then ordered it enumerated.
    """

    frequencies = _subject_label_frequencies(documents, subject_labels)
    groups = _subject_label_groups(subject_labels)
    if not frequencies or not groups:
        return True
    # The first concept is the specific subject phrase supplied by the user.
    # Later words may be a generic head noun ("shortcut keys") or a verb. An
    # unrelated registry that contains only the generic word must not form a
    # contract, while a registry headed "Shortcuts" need not literally repeat
    # the word "keys" in every chunk.
    return any(frequencies.get(label, 0) for label in groups[0])


def _subject_fields(document: object) -> tuple[str, str]:
    """Return the document's heading text and body text, both case-folded."""

    metadata = getattr(document, "metadata", {}) or {}
    structure_path = metadata.get("structure_path") or []
    if isinstance(structure_path, str):
        structure_path = [structure_path]
    heading = " ".join(
        (
            str(metadata.get("title") or ""),
            str(metadata.get("source") or ""),
            " ".join(str(value) for value in structure_path),
        )
    ).casefold()
    body = str(getattr(document, "page_content", "") or "").casefold()
    return heading, body


def _subject_score(heading: str, body: str, weights: dict[str, float]) -> float:
    """Score subject overlap, counting a heading match double a body match."""

    score = 0.0
    for label, weight in weights.items():
        if label in heading:
            score += 2 * weight
        elif label in body:
            score += weight
    return score


def _subject_document_ranking(
    documents: list[object], weights: dict[str, float]
) -> list[object]:
    """Order candidates by informative subject overlap, ties keeping rank.

    Which source may define the contract is decided by subject, not by size: a
    registry that enumerates 158 members is exactly the population an
    enumeration request asks for, and rejecting it for being large is what
    produced silent partial lists. What must be rejected is a source about a
    *different* population. With no labels, or labels that match nothing, the
    retrieval order is preserved exactly.
    """

    if not weights:
        return list(documents)
    scored = []
    for index, document in enumerate(documents):
        heading, body = _subject_fields(document)
        scored.append((-_subject_score(heading, body, weights), index, document))
    scored.sort(key=lambda entry: (entry[0], entry[1]))
    return [document for _, _, document in scored]


def _enumerable_blocks(document: object) -> list[tuple[str, list[str]]]:
    """Group a document's enumerable lines under the heading they sit below.

    One source can carry several registries -- a module table and a shortcut
    table on the same page. Taking the first one that enumerates answers a
    different question than the one asked, which is the same failure as choosing
    an off-subject source, one level down.
    """

    blocks: list[tuple[str, list[str]]] = [("", [])]
    for line in classify_answer_lines(
        str(getattr(document, "page_content", "") or "")
    ):
        if line.kind is AnswerLineKind.HEADING:
            blocks.append((line.text, []))
        elif line.kind in {AnswerLineKind.TABLE_ROW, AnswerLineKind.LIST_ITEM}:
            blocks[-1][1].append(line.text)
    return [(heading, rows) for heading, rows in blocks if rows]


def _block_subject_fields(
    document: object, heading: str, rows: list[str]
) -> tuple[str, str]:
    """Return the local heading and rows for one enumerable block.

    The document title is deliberately excluded. A bilingual Confluence page can
    name multiple applications while each chunk belongs to only one of them.
    Using that broad title as the block scope makes every application's chunk
    look like evidence for every other application. The structure path is the
    ingestion-owned local heading that survives chunking.
    """

    metadata = getattr(document, "metadata", {}) or {}
    structure_path = metadata.get("structure_path") or []
    if isinstance(structure_path, str):
        structure_path = [structure_path]
    local_heading = " ".join(
        [*(str(value) for value in structure_path), heading]
    ).casefold()
    return local_heading, " ".join(rows).casefold()


def _scope_is_evidenced(
    heading: str,
    body: str,
    labels: tuple[str, ...],
    *,
    heading_is_authoritative: bool = False,
) -> bool:
    """Require an application scope as a complete token in the local block."""

    if not labels:
        return True
    pattern_matches = lambda text: any(
        re.search(rf"(?<![\w-]){re.escape(label.casefold())}(?![\w-])", text)
        for label in labels
        if label
    )
    if heading_is_authoritative and heading.strip():
        return pattern_matches(heading)
    return pattern_matches(f"{heading} {body}")


def _prefer_document_language(
    documents: list[object], language: str
) -> list[object]:
    """Put the user's indexed language first without discarding fallbacks."""

    requested = language.strip().casefold()
    if requested not in {"en", "es"}:
        return list(documents)

    def rank(document: object) -> int:
        value = str(
            (getattr(document, "metadata", {}) or {}).get("language") or ""
        ).strip().casefold()
        if value == requested:
            return 0
        if not value or value not in {"en", "es"}:
            return 1
        return 2

    return sorted(documents, key=rank)


def _evidence_population_members(
    documents: list[object],
    subject_labels: tuple[str, ...] = (),
    scope_labels: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Derive an enumerable population from the evidence itself.

    Completeness used to be enforced only when ingestion had labelled a source
    ``entity-contract`` or ``registry-table``, which it decides from a fixed row
    count. A page that enumerates fewer rows than that literal was classified
    narrative, carried no ``entity_key``, and so no population formed: the answer
    listed whatever chunks happened to arrive and nothing reported the omissions.
    Reading the members out of the retrieved rows makes the guarantee depend on
    the evidence being enumerable rather than on an ingestion-time label.

    Members are taken from a single source -- the highest ranked one that
    enumerates -- so the contract stays one coherent registry instead of a union
    of unrelated lists.
    """

    if not _subject_is_evidenced(documents, subject_labels):
        return ()
    block_fields = [
        _block_subject_fields(document, heading, rows)
        for document in documents
        for heading, rows in _enumerable_blocks(document)
    ]
    local_frequencies = {
        label.casefold(): sum(
            1
            for heading, body in block_fields
            if label.casefold() in heading or label.casefold() in body
        )
        for label in subject_labels
        if label
    }
    local_total = len(block_fields)
    weights = {
        label: math.log(local_total / frequency) if frequency and local_total else 0.0
        for label, frequency in local_frequencies.items()
    }
    required = _required_subject_labels(local_frequencies, subject_labels)
    selection_weights = {
        label: weights.get(label, 0.0) or 1.0 for label in required
    }
    ranked = list(documents)
    if not required and not scope_labels:
        # With no discriminating labels, retrieval rank remains authoritative as
        # before; do not union unrelated registries merely because they enumerate.
        ranked = ranked[:1]

    qualifying: list[tuple[float, int, int, list[str]]] = []
    for document_index, document in enumerate(ranked):
        for block_index, (heading, rows) in enumerate(_enumerable_blocks(document)):
            local_heading, local_body = _block_subject_fields(document, heading, rows)
            if required and not any(
                label in local_heading or label in local_body for label in required
            ):
                continue
            if not _scope_is_evidenced(
                local_heading,
                local_body,
                scope_labels,
                heading_is_authoritative=True,
            ):
                continue
            qualifying.append(
                (
                    _subject_score(local_heading, local_body, selection_weights),
                    document_index,
                    block_index,
                    rows,
                )
            )
    if qualifying:
        best = max(score for score, _, _, _ in qualifying)
        # A registry may span multiple ingestion chunks. Keep every equally best
        # local block, in retrieval order, so the population is not silently
        # reduced to whichever chunk happened to rank first.
        selected = [entry for entry in qualifying if entry[0] == best]
        selected.sort(key=lambda entry: (entry[1], entry[2]))
        labels: list[str] = []
        for _, _, _, rows in selected:
            for row in rows:
                label = _member_label(row)
                if label:
                    labels.append(label)
        unique = tuple(dict.fromkeys(labels))
        # Every member the source enumerates, however many that is. No floor and
        # no ceiling: a two-row registry is still a registry, and a 158-row one
        # is still the population that was asked for.
        if unique:
            return unique
    return ()


def _population_source_ids(
    documents: list[object],
    subject_labels: tuple[str, ...],
    scope_labels: tuple[str, ...],
) -> tuple[str, ...]:
    """Return sources whose retrieved chunks locally expose the asked registry."""

    source_ids: list[str] = []
    required = _subject_label_groups(subject_labels)
    primary_subject = required[0] if required else set()
    for document in documents:
        enumerable_match = bool(
            _evidence_population_members(
                [document], subject_labels, scope_labels
            )
        )
        if not enumerable_match:
            metadata = getattr(document, "metadata", {}) or {}
            structure_path = metadata.get("structure_path") or []
            if isinstance(structure_path, str):
                structure_path = [structure_path]
            local_heading = " ".join(str(value) for value in structure_path).casefold()
            local_body = str(getattr(document, "page_content", "") or "").casefold()
            # A reranker may surface a troubleshooting paragraph from the right
            # source while none of that source's registry chunks fits in top-N.
            # That locally scoped mention may discover the authorized source,
            # but only enumerable sibling chunks pass the stricter gate later.
            if not (
                any(
                    label in local_heading or label in local_body
                    for label in primary_subject
                )
                and _scope_is_evidenced(
                    local_heading, local_body, scope_labels
                )
            ):
                continue
        source_id = str(
            (getattr(document, "metadata", {}) or {}).get("source_id") or ""
        ).strip()
        if source_id:
            source_ids.append(source_id)
    return tuple(dict.fromkeys(source_ids))


def _publisher_population_requested(question: str) -> bool:
    """Return whether the inventory asks for members published by an entity."""

    return bool(
        re.search(
            r"(?i)\b(?:send|sends|sending|sent|publish|publishes|publishing|"
            r"published|produce|produces|producing|emit|emits|emitting)\b",
            question,
        )
    )


def _publisher_destination_population_requested(question: str) -> bool:
    """Return whether an exhaustive publisher list is partitioned by destination."""

    return _publisher_population_requested(question) and bool(
        re.search(
            r"(?i)\b(?:destination|destinations|destino|destinos|route|routes|"
            r"group|grouped|grouping|only|both|solo|solamente|ambos|ambas)\b",
            question,
        )
    )


def _mentioned_destination_entities(
    question: str, entities: tuple[str, ...], publisher: str
) -> tuple[str, ...]:
    """Return explicitly named destination entities in their question order."""

    found: list[tuple[int, str]] = []
    for raw_entity in entities:
        entity = _normalized_entity(raw_entity)
        if not entity or entity == publisher:
            continue
        match = re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(entity)}(?![A-Za-z0-9_])",
            question,
            flags=re.IGNORECASE,
        )
        if match:
            found.append((match.start(), entity))
    found.sort()
    return tuple(dict.fromkeys(entity for _, entity in found))


def _table_cells(value: str) -> list[str]:
    return [cell.strip().strip("`*_ ") for cell in value.strip().strip("|").split("|")]


def _published_population_members(
    documents: list[object], scope_labels: tuple[str, ...]
) -> tuple[str, ...]:
    """Read members whose application column explicitly says it publishes.

    This is relation-aware: belonging to an application's event family is not
    the same as being sent by that application. Consume-only and declared-only
    rows must not be included, while a differently named family can still carry
    a row that the application publishes.
    """

    scopes = {label.casefold() for label in scope_labels if label}
    if not scopes:
        return ()
    members: list[str] = []
    for document in documents:
        header: list[str] = []
        for line in classify_answer_lines(
            str(getattr(document, "page_content", "") or "")
        ):
            if line.kind is AnswerLineKind.TABLE_HEADER:
                header = _table_cells(line.text)
                continue
            if line.kind is not AnswerLineKind.TABLE_ROW or not header:
                continue
            cells = _table_cells(line.text)
            if len(cells) < len(header):
                continue
            normalized_header = [cell.casefold() for cell in header]
            scope_indexes = [
                index
                for index, name in enumerate(normalized_header)
                if name in scopes
            ]
            if not scope_indexes:
                continue
            status = " ".join(cells[index].casefold() for index in scope_indexes)
            if not re.search(r"\b(?:publishes|both|publica|publica y consume)\b", status):
                continue
            identifier_index = next(
                (
                    index
                    for index, name in enumerate(normalized_header)
                    if name in {"constant", "kotlin constant", "constante"}
                ),
                0,
            )
            member = _member_label(cells[identifier_index])
            if member:
                members.append(member)
    return tuple(dict.fromkeys(members))


def _publisher_destination_rows(
    documents: list[object],
    publisher: str,
    destination_labels: tuple[str, ...],
) -> dict[str, list[tuple[str, int]]]:
    """Read a publisher matrix and partition its events by explicit destination.

    Registry family and consumer columns cannot answer a direction question. This
    parser accepts only tables with publisher and destination columns, requires
    the requested publisher in the publisher cell, and derives the buckets from
    the destination cell. It therefore cannot accidentally include inbound rows.
    """

    if not publisher or len(destination_labels) < 2:
        return {}
    destinations = tuple(dict.fromkeys(label.casefold() for label in destination_labels))
    groups: dict[str, list[tuple[str, int]]] = {
        destinations[0]: [],
        destinations[1]: [],
        "both": [],
    }
    seen: set[str] = set()
    for source_number, document in enumerate(documents, start=1):
        header: list[str] = []
        for line in classify_answer_lines(
            str(getattr(document, "page_content", "") or "")
        ):
            if line.kind is AnswerLineKind.TABLE_HEADER:
                header = _table_cells(line.text)
                continue
            if line.kind is not AnswerLineKind.TABLE_ROW or not header:
                continue
            cells = _table_cells(line.text)
            if len(cells) < len(header):
                continue
            normalized_header = [cell.casefold() for cell in header]
            publisher_index = next(
                (
                    index
                    for index, name in enumerate(normalized_header)
                    if name in {"publisher", "publicador"}
                ),
                -1,
            )
            destination_index = next(
                (
                    index
                    for index, name in enumerate(normalized_header)
                    if name in {"destination", "destinations", "destino", "destinos"}
                ),
                -1,
            )
            event_index = next(
                (
                    index
                    for index, name in enumerate(normalized_header)
                    if name in {"event", "event (wire name)", "evento", "evento (nombre wire)"}
                ),
                0,
            )
            if publisher_index < 0 or destination_index < 0:
                continue
            publisher_cell = cells[publisher_index].casefold()
            if not re.search(
                rf"(?<![\w-]){re.escape(publisher)}(?![\w-])", publisher_cell
            ):
                continue
            destination_cell = cells[destination_index].casefold()
            matched = [
                label
                for label in destinations[:2]
                if re.search(
                    rf"(?<![\w-]){re.escape(label)}(?![\w-])", destination_cell
                )
            ]
            event_cell = cells[event_index]
            identifiers = re.findall(r"`([^`]+)`", event_cell)
            if not identifiers:
                identifiers = [
                    value.strip().strip("`*_ ")
                    for value in re.split(r"\s*,\s*", event_cell)
                    if value.strip().strip("`*_ ")
                ]
            if len(matched) == 2:
                group = "both"
            elif len(matched) == 1:
                group = matched[0]
            elif re.search(r"\bmulticast\b", destination_cell):
                # A multicast row may name its route rather than its destination.
                # Its wire-family prefix provides the explicit destination label.
                prefixed = [
                    label
                    for label in destinations[:2]
                    if any(
                        re.match(rf"(?i)^{re.escape(label)}(?:_|-)", identifier)
                        for identifier in identifiers
                    )
                ]
                if len(prefixed) != 1:
                    continue
                group = prefixed[0]
            else:
                continue
            for identifier in identifiers:
                member = _member_label(identifier)
                if member and member not in seen:
                    groups[group].append((member, source_number))
                    seen.add(member)
    return groups


def _publisher_destination_members(
    documents: list[object], publisher: str, destination_labels: tuple[str, ...]
) -> tuple[str, ...]:
    groups = _publisher_destination_rows(documents, publisher, destination_labels)
    return tuple(
        member
        for group in (*destination_labels[:2], "both")
        for member, _ in groups.get(group, [])
    )


def _coverage_expected_identifiers(
    question: str,
    population_documents: list[object],
    evidence_documents: list[object] | None = None,
    subject_labels: tuple[str, ...] = (),
    scope_labels: tuple[str, ...] = (),
    destination_labels: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return the population contract implied by the resolved question."""

    if not is_inventory_question(question):
        return ()
    if (
        evidence_documents
        and scope_labels
        and _publisher_destination_population_requested(question)
    ):
        destination_members = _publisher_destination_members(
            evidence_documents, scope_labels[0], destination_labels
        )
        if destination_members:
            return destination_members
    if evidence_documents and _publisher_population_requested(question):
        published = _published_population_members(
            evidence_documents, scope_labels
        )
        if published:
            return published
    # The metadata population is loaded by a filter that admits a chunk when
    # *any* subject label matches it (retrieval.py). One weak label is therefore
    # enough to admit an entire unrelated registry -- "key" matches every event
    # chunk -- and because this path returned before any subject test, the
    # contract was built from those chunks and the answer enumerated them. The
    # same subject test the evidence path uses is applied here first.
    candidates = [*population_documents, *(evidence_documents or [])]
    subject_evidenced = _subject_is_evidenced(candidates, subject_labels)
    metadata_population = ()
    if subject_evidenced:
        frequencies = _subject_label_frequencies(candidates, subject_labels)
        required = _required_subject_labels(frequencies, subject_labels)
        qualifying = [
            document
            for document in population_documents
            if not required
            or any(
                label in " ".join(_subject_fields(document))
                for label in required
            )
        ]
        if scope_labels:
            qualifying = [
                document
                for document in qualifying
                if _scope_is_evidenced(
                    *_block_subject_fields(document, "", []),
                    scope_labels,
                    heading_is_authoritative=True,
                )
            ]
        metadata_population = tuple(
            dict.fromkeys(
                str(getattr(document, "metadata", {}).get("entity_key") or "").strip()
                for document in qualifying
                if str(
                    getattr(document, "metadata", {}).get("entity_key") or ""
                ).strip()
            )
        )
    if metadata_population:
        return metadata_population
    if not evidence_documents:
        return ()
    return _evidence_population_members(
        evidence_documents, subject_labels, scope_labels
    )


def _row_text(value: str) -> str:
    """Render one registry row as a sentence keeping every cell it carries."""

    text = value.strip().strip("|").strip()
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text)
    cells = [cell.strip().strip("`*_ ") for cell in text.split("|")]
    return " \u2014 ".join(cell for cell in cells if cell)


def _population_rows_from_evidence(
    expected: tuple[str, ...], documents: list[object]
) -> dict[str, tuple[str, int]]:
    """Locate each expected member's own row and the source that carries it.

    A population derived from the evidence has no ``entity_key`` on any chunk, so
    the identifier-keyed lookup finds nothing and the answer falls back to the
    generator -- where the output token limit, not the evidence, decides how many
    members get printed. Rows are located here instead so the full list is
    emitted by code and no ceiling can silently shorten it. The row is rendered
    whole, so the attribute columns survive alongside the identifier.
    """

    expected_set = set(expected)
    remaining = set(expected)
    located: dict[str, tuple[str, int]] = {}
    for source_number, document in enumerate(documents, start=1):
        if not remaining:
            break
        for line in classify_answer_lines(
            str(getattr(document, "page_content", "") or "")
        ):
            if line.kind not in {AnswerLineKind.TABLE_ROW, AnswerLineKind.LIST_ITEM}:
                continue
            label = _member_label(line.text)
            if label in expected_set:
                rendered = _row_text(line.text)
                if rendered and label not in located:
                    located[label] = (rendered, source_number)
                    remaining.discard(label)
                elif rendered and located[label][1] == source_number:
                    # One shortcut can have multiple condition-dependent rows
                    # (for example F11 closes an open shift and logs out when no
                    # shift is open). Preserve every distinct row from the first
                    # source that established the member instead of silently
                    # dropping the later behavior.
                    existing, existing_source = located[label]
                    if rendered not in existing:
                        located[label] = (
                            f"{existing}; {rendered}",
                            existing_source,
                        )
    return located


def _deterministic_population_inventory_answer(
    expected: tuple[str, ...], documents: list[object]
) -> GroundedAnswer | None:
    """Render an exhaustive population as directly cited bullets.

    Deterministic rendering is what makes "every member" enforceable: the list
    is built from the evidence rows themselves, so its length is bounded by the
    population and not by any generation limit.
    """

    if not expected:
        return None
    sources: dict[str, int] = {}
    for source_number, document in enumerate(documents, start=1):
        identifier = str(
            getattr(document, "metadata", {}).get("entity_key") or ""
        ).strip()
        if identifier in expected:
            sources.setdefault(identifier, source_number)
    if all(identifier in sources for identifier in expected):
        return GroundedAnswer(
            answer="\n".join(
                f"- {identifier} [SOURCE {sources[identifier]}]."
                for identifier in expected
            ),
            citations=list(
                dict.fromkeys(sources[identifier] for identifier in expected)
            ),
            missing_information=[],
        )
    located = _population_rows_from_evidence(expected, documents)
    if any(identifier not in located for identifier in expected):
        return None
    return GroundedAnswer(
        answer="\n".join(
            f"- {located[identifier][0]} [SOURCE {located[identifier][1]}]."
            for identifier in expected
        ),
        citations=list(
            dict.fromkeys(located[identifier][1] for identifier in expected)
        ),
        missing_information=[],
    )


def _deterministic_publisher_destination_answer(
    question: str,
    documents: list[object],
    publisher: str,
    destination_labels: tuple[str, ...],
    language: str,
) -> GroundedAnswer | None:
    """Render destination-partitioned publisher rows without model regrouping."""

    if not _publisher_destination_population_requested(question):
        return None
    groups = _publisher_destination_rows(documents, publisher, destination_labels)
    ordered_groups = (*destination_labels[:2], "both")
    if not groups or not all(groups.get(group) for group in ordered_groups):
        return None
    spanish = language.casefold() == "es"
    headings = {
        destination_labels[0]: (
            f"Solo {destination_labels[0].upper()}"
            if spanish
            else f"{destination_labels[0].upper()} only"
        ),
        destination_labels[1]: (
            f"Solo {destination_labels[1].upper()}"
            if spanish
            else f"{destination_labels[1].upper()} only"
        ),
        "both": (
            f"Ambos {destination_labels[0].upper()} e {destination_labels[1].upper()}"
            if spanish
            else f"Both {destination_labels[0].upper()} and {destination_labels[1].upper()}"
        ),
    }
    sections: list[str] = []
    citations: list[int] = []
    for group in ordered_groups:
        rows = groups[group]
        sections.append(f"### {headings[group]} ({len(rows)})")
        for member, source_number in rows:
            sections.append(f"- {member} [SOURCE {source_number}].")
            citations.append(source_number)
    return GroundedAnswer(
        answer="\n".join(sections),
        citations=list(dict.fromkeys(citations)),
        missing_information=[],
    )


def _entity_from_structural_label(value: object) -> set[str]:
    text = str(value or "")
    entities = {
        _normalized_entity(match.group(1))
        for match in re.finditer(
            r"(?:^|[\[\]\"'/>|])\s*([A-Za-z][A-Za-z0-9_-]{1,40})(?:3b)?\s+(?:application|app)\b",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    }
    return {entity for entity in entities if entity and entity not in _ENTITY_STOP_WORDS}


def _document_entities(document: object) -> set[str]:
    """Return only strong entity markers; unmarked documents remain shareable."""

    metadata = getattr(document, "metadata", {})
    explicit = {
        _normalized_entity(metadata.get(key, ""))
        for key in ("entity", "application", "application_id", "app_id")
        if metadata.get(key)
    }
    if explicit:
        return {entity for entity in explicit if entity}

    # Older chunks used entity_key for the application; entity-contract chunks
    # use it for the contract identifier (for example ORDER_CREATED). Treat it
    # as application scope only when it does not have identifier shape.
    entity_key = str(metadata.get("entity_key") or "")
    if entity_key and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", entity_key):
        normalized = _normalized_entity(entity_key)
        if normalized:
            return {normalized}

    repository = str(metadata.get("repository", ""))
    repository_match = re.match(
        r"^([A-Za-z][A-Za-z0-9_-]*?)(?:3b)?[-_]app(?:[-_]|$)",
        repository,
        flags=re.IGNORECASE,
    )
    if repository_match:
        return {_normalized_entity(repository_match.group(1))}

    structural = _entity_from_structural_label(metadata.get("structure_path", ""))
    if structural:
        return structural

    content = str(getattr(document, "page_content", ""))[:1600]
    heading_entities = _entity_from_structural_label(content)
    if heading_entities:
        return heading_entities

    # A title naming several applications is intentionally not treated as a
    # single entity. Its section/body structure must decide the scope instead.
    title = str(metadata.get("title", ""))
    combined = re.search(
        r"\b([A-Za-z][A-Za-z0-9_-]{1,40})\s+(?:and|&|y)\s+"
        r"([A-Za-z][A-Za-z0-9_-]{1,40})\s+(?:applications?|apps?)\b",
        title,
        flags=re.IGNORECASE,
    )
    if combined:
        return {
            _normalized_entity(combined.group(1)),
            _normalized_entity(combined.group(2)),
        }
    return _entity_from_structural_label(title)


def _scope_documents_to_entity(
    documents: list[object], requested_entity: str
) -> tuple[list[object], int, list[dict[str, object]], bool]:
    if not requested_entity:
        return documents, 0, [], False
    scoped = []
    excluded = 0
    entity_excluded_titles: list[dict[str, object]] = []
    for document in documents:
        entities = _document_entities(document)
        if entities and requested_entity not in entities:
            excluded += 1
            metadata = getattr(document, "metadata", {})
            entity_excluded_titles.append(
                {
                    "title": str(metadata.get("title") or ""),
                    "resolved_entities": sorted(entities),
                    "exclusion_reason": "not_in_entities",
                }
            )
            continue
        scoped.append(document)
    scoped, scope_bypassed = preserve_non_empty(documents, scoped)
    return (
        scoped,
        excluded,
        entity_excluded_titles,
        scope_bypassed,
    )


def _expand_standalone_identifier_question(
    question: str, documents: list[object]
) -> str:
    identifiers = member_identifiers(question)
    if len(identifiers) != 1:
        return question
    identifier = identifiers[0]
    bare_identifier = question.strip().strip("` ") == identifier
    member_question = bool(
        re.search(
            r"\b(?:field|fields|parameter|parameters|payload|attribute|attributes|"
            r"property|properties|schema|contract|structure|details|explain)\b",
            question,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"\bwhat\s+does\s+{re.escape(identifier)}\s+do\b",
            question,
            flags=re.IGNORECASE,
        )
    )
    if not bare_identifier and not member_question:
        return question
    if not any(
        getattr(document, "metadata", {}).get("identifier_anchor")
        for document in documents
    ):
        return question
    return (
        f"Give the complete contract details for {identifier}: its code constant, wire name, "
        "numeric id, version, publisher, destinations or consumers, purpose, and every "
        "declared payload field. Include both code property names and serialized field names "
        "when the evidence provides them."
    )

class AnswerNodesMixin:
    """AnswerNodes responsibilities."""

    async def _generate(self, state: RagState) -> RagState:
        began = started()
        overview_style_repaired = False
        answer_question = state.get("resolved_question") or self._request.question
        list_response_requested = _list_response_requested(answer_question)
        retrieved_documents = list(state.get("documents", []))
        sibling_expanded_count = 0
        requested_entity = _normalized_entity(state.get("overview_entity", ""))
        if not requested_entity:
            requested_entity = _explicit_entity_scope(
                answer_question, self._vocabulary.entities
            )
        inventory_question = is_inventory_question(answer_question)
        if inventory_question or state.get("query_intent") in {
            "STRUCTURED_INVENTORY",
            "PROJECT_OVERVIEW",
        }:
            # Inventory evidence is commonly stored in shared registry/index chunks whose
            # document title is broader than the requested entity. Keep those candidates
            # and enforce the entity boundary in the grounded answer instead of dropping
            # valid evidence solely because of document-level naming. A project overview
            # likewise spans its applications: interpreting the project id as an entity
            # used to discard application sources before citation validation.
            documents = retrieved_documents
            entity_excluded_count = 0
            entity_excluded_titles: list[dict[str, object]] = []
            scope_bypassed = False
        else:
            (
                documents,
                entity_excluded_count,
                entity_excluded_titles,
                scope_bypassed,
            ) = _scope_documents_to_entity(retrieved_documents, requested_entity)
        coverage_expected_keys: tuple[str, ...] = ()
        population_retrieval_miss = False
        if inventory_question:
            population_loader = getattr(self._retriever, "ainvoke_population", None)
            subject_labels = _population_labels(
                answer_question, self._vocabulary.entities
            )
            scope_labels = (requested_entity,) if requested_entity else ()
            destination_labels = _mentioned_destination_entities(
                answer_question,
                self._vocabulary.entities,
                requested_entity,
            )
            sibling_loader = getattr(
                self._retriever, "ainvoke_source_siblings", None
            )
            source_ids = _population_source_ids(
                documents, subject_labels, scope_labels
            )
            if (
                requested_entity
                and _publisher_destination_population_requested(answer_question)
            ):
                destination_source_ids = [
                    str((getattr(document, "metadata", {}) or {}).get("source_id") or "")
                    for document in documents
                    if _publisher_destination_members(
                        [document], requested_entity, destination_labels
                    )
                ]
                source_ids = tuple(
                    dict.fromkeys(
                        [*source_ids, *(value for value in destination_source_ids if value)]
                    )
                )
            if sibling_loader is not None and source_ids:
                sibling_documents = await sibling_loader(
                    source_ids, state.get("source_types", ())
                )
                population_siblings = [
                    document
                    for document in sibling_documents
                    if (
                        _publisher_destination_members(
                            [document], requested_entity, destination_labels
                        )
                        if _publisher_destination_population_requested(answer_question)
                        else _published_population_members([document], scope_labels)
                        if _publisher_population_requested(answer_question)
                        else _evidence_population_members(
                            [document], subject_labels, scope_labels
                        )
                    )
                ]
                sibling_expanded_count = len(population_siblings)
                documents = _merge_ranked_documents(
                    documents,
                    population_siblings,
                    top_n=len(documents) + len(population_siblings),
                )
                documents = _prefer_document_language(
                    documents, state.get("language", "mixed")
                )
            population_documents = (
                await population_loader(
                    requested_entity,
                    subject_labels,
                    state.get("source_types", ()),
                )
                if population_loader is not None
                else []
            )
            # No truncation of the population or of the contract built from it.
            # A request to enumerate a registry is a request for all of its
            # members; capping the contract turns a complete answer into a
            # silently partial one that nothing downstream can detect.
            coverage_expected_keys = _coverage_expected_identifiers(
                answer_question,
                population_documents,
                documents,
                subject_labels,
                scope_labels,
                destination_labels,
            )
            initially_retrieved = {
                str(document.metadata.get("entity_key") or "").strip()
                for document in documents
            }
            population_retrieval_miss = bool(coverage_expected_keys) and not bool(
                initially_retrieved.intersection(coverage_expected_keys)
            )
            documents = _merge_ranked_documents(
                documents,
                population_documents,
                top_n=len(documents) + len(coverage_expected_keys),
            )
        structured_tabular_evidence = _structured_tabular_evidence(documents)
        comparison_subjects = _comparison_subjects(
            answer_question, self._vocabulary.entities
        )
        comparison_table_selected = bool(
            state.get("query_intent") == "CROSS_SOURCE"
            and len(comparison_subjects) >= 2
        )
        structured_tabular_selected = bool(
            structured_tabular_evidence and _attribute_table_requested(answer_question)
        )
        if comparison_table_selected:
            answer_shape_selected = "comparison_table"
            answer_shape_reason = "CROSS_SOURCE_MULTI_SUBJECT"
        elif structured_tabular_selected:
            answer_shape_selected = "structured_tabular"
            answer_shape_reason = "ATTRIBUTE_OR_MEMBER_QUESTION_WITH_TABULAR_EVIDENCE"
        else:
            answer_shape_selected = "prose"
            answer_shape_reason = (
                "PROCEDURAL_OR_CAUSAL_QUESTION"
                if re.search(
                    r"\b(?:how|why|procedure|process|steps?|flow)\b",
                    answer_question,
                    flags=re.IGNORECASE,
                )
                else "NO_TABULAR_REQUEST"
            )
        if answer_shape_selected in {"structured_tabular", "comparison_table"}:
            list_response_requested = False
        list_style_repaired = False
        generation_question = answer_question
        if requested_entity:
            generation_question = (
                f"{answer_question}\n\nRequested entity scope: {requested_entity}. "
                "Answer only for this entity. Do not include features or behavior from other "
                "applications, repositories, services, or libraries unless the evidence explicitly "
                "shows that shared component is used by the requested entity."
            )
        if list_response_requested:
            generation_question = (
                f"{generation_question}\n\nRequired response shape: return a complete Markdown "
                "bullet list with exactly one distinct evidenced item per bullet. Do not compress "
                "multiple items into prose, use phrases such as 'such as' or 'additional items', "
                "or include items from outside the requested scope."
            )
        if coverage_expected_keys:
            generation_question = (
                f"{generation_question}\n\nExhaustive population contract: exactly "
                f"{len(coverage_expected_keys)} identifiers are evidenced for this scope. "
                "Include every identifier exactly once and state the total. The expected "
                f"identifiers are: {', '.join(coverage_expected_keys)}. Never summarize "
                "this population with 'such as'."
            )
        answer_question = _expand_standalone_identifier_question(
            generation_question, documents
        )
        generated = _deterministic_identifier_answer(
            answer_question,
            documents,
            state.get("language", "mixed"),
        )
        destination_labels = _mentioned_destination_entities(
            answer_question,
            self._vocabulary.entities,
            requested_entity,
        )
        destination_answer = _deterministic_publisher_destination_answer(
            answer_question,
            documents,
            requested_entity,
            destination_labels,
            state.get("language", "mixed"),
        )
        if destination_answer is not None:
            generated = destination_answer
        if state.get("query_intent") == "STRUCTURED_INVENTORY":
            if destination_answer is None:
                generated = _deterministic_structured_inventory_answer(
                    answer_question,
                    documents,
                    state.get("language", "mixed"),
                )
        elif state.get("query_intent") == "FEATURE_INVENTORY":
            generated = _deterministic_feature_inventory_answer(
                documents,
                state.get("language", "mixed"),
                state.get("overview_entity", ""),
            )
        elif state.get("query_intent") == "CODE_INVENTORY":
            generated = _deterministic_code_inventory_answer(
                documents, state.get("language", "mixed")
            )
        elif state.get("query_intent") == "IMPLEMENTATION":
            generated = _deterministic_code_location_answer(
                answer_question,
                documents,
                state.get("language", "mixed"),
                self._vocabulary.code_extensions,
            )
        elif state.get("query_intent") == "DELIVERY":
            generated = _deterministic_delivery_answer(
                answer_question,
                documents,
                state.get("language", "mixed"),
            )
        if generated is None and coverage_expected_keys:
            generated = _deterministic_population_inventory_answer(
                coverage_expected_keys, documents
            )
        deterministic = generated is not None
        generation_temperature = 0.0
        answer_style = "concise"

        async def generate_model_answer(answer_style: str) -> GroundedAnswer:
            if not (
                self._settings.incremental_verified_streaming_enabled
                and getattr(self, "_incremental_stream_active", False)
            ):
                return await self._generator.answer(
                    answer_question,
                    documents,
                    state.get("language", "mixed"),
                    answer_style=answer_style,
                )

            writer = get_stream_writer()

            async def publish_delta(delta: str) -> None:
                writer(
                    {
                        "type": "answer_delta",
                        "delta": delta,
                        "verification": "pending",
                    }
                )

            async def verify_and_publish(sentence: str, index: int) -> bool:
                citations = [
                    int(value)
                    for value in re.findall(r"\[SOURCE (\d+)\]", sentence)
                ]
                verdict = await self._grounding_verifier.verify(
                    self._request.question,
                    documents,
                    GroundedAnswer(answer=sentence, citations=citations),
                    answer_language=state.get("language", ""),
                )
                if verdict.supported:
                    clean = re.sub(r"\s*\[SOURCE \d+\]", "", sentence).strip()
                    writer(
                        {
                            "type": "answer_sentence_verified",
                            "claimIndex": index,
                            "sentence": clean,
                            "provisionalText": sentence,
                        }
                    )
                    return True
                else:
                    clean = re.sub(r"\s*\[SOURCE \d+\]", "", sentence).strip()
                    writer(
                        {
                            "type": "answer_sentence_rejected",
                            "claimIndex": index,
                            "sentence": clean,
                            "provisionalText": sentence,
                            "reason": verdict.reason_code,
                        }
                    )
                    return False

            try:
                streamed_answer = await self._generator.answer(
                    answer_question,
                    documents,
                    state.get("language", "mixed"),
                    answer_style=answer_style,
                    sentence_callback=verify_and_publish,
                    delta_callback=publish_delta,
                )
                if self._generator.last_stream_truncated:
                    writer(
                        {
                            "type": "answer_snapshot",
                            "answer": re.sub(
                                r"\s*\[SOURCE \d+\]", "", streamed_answer.answer
                            ).strip(),
                            "truncated": True,
                            "timeoutReason": self._generator.last_stream_timeout_kind,
                        }
                    )
                return streamed_answer
            except Exception as failure:
                stage_complete(
                    "generate",
                    self._request.project_id,
                    began,
                    input_count=len(documents),
                    reason_code=(
                        "GENERATION_TIMEOUT"
                        if isinstance(failure, TimeoutError)
                        else "GENERATION_ERROR"
                    ),
                    model_provider=self._settings.llm_provider,
                    model_name=self._generator.model_name,
                    model_profile=self._request.model_profile,
                    language=state.get("language", "und"),
                    extra={
                        "prose_stream_seconds": round(
                            self._generator.last_prose_stream_seconds, 3
                        ),
                        "answer_metadata_seconds": round(
                            self._generator.last_answer_metadata_seconds, 3
                        ),
                        "time_to_first_chunk_seconds": round(
                            self._generator.last_time_to_first_chunk_seconds, 3
                        ),
                    },
                )
                raise

        if generated is None:
            if state.get("query_intent") in {
                "ENTITY_OVERVIEW",
                "PROJECT_OVERVIEW",
                "FEATURE_INVENTORY",
                "IMPLEMENTATION",
                "DELIVERY",
                "CODE_ASSISTED",
                "CROSS_SOURCE",
                "IMPLEMENTATION_FLOW",
                "STRUCTURED_INVENTORY",
            }:
                intent = state.get("query_intent")
                answer_style = (
                    "project_overview"
                    if intent == "PROJECT_OVERVIEW"
                    else "feature_inventory"
                    if intent == "FEATURE_INVENTORY"
                    else "implementation"
                    if intent == "IMPLEMENTATION"
                    else "delivery"
                    if intent == "DELIVERY"
                    else "code_assisted"
                    if intent == "CODE_ASSISTED"
                    else "code_assisted"
                    if intent == "IMPLEMENTATION_FLOW"
                    else "cross_source"
                    if intent == "CROSS_SOURCE"
                    else "structured_inventory"
                    if intent == "STRUCTURED_INVENTORY"
                    else "entity_overview"
                )
                if list_response_requested and intent not in {
                    "ENTITY_OVERVIEW",
                    "PROJECT_OVERVIEW",
                }:
                    answer_style = "requested_list"
                if answer_shape_selected in {
                    "structured_tabular",
                    "comparison_table",
                }:
                    answer_style = answer_shape_selected
                try:
                    generated = await generate_model_answer(answer_style)
                except TypeError as error:
                    if (
                        "answer_style" not in str(error)
                        and "sentence_callback" not in str(error)
                        and "delta_callback" not in str(error)
                    ):
                        raise
                    generated = await self._generator.answer(
                        answer_question,
                        documents,
                        state.get("language", "mixed"),
                    )
            else:
                generated = await generate_model_answer(
                    answer_shape_selected
                    if answer_shape_selected in {
                        "structured_tabular",
                        "comparison_table",
                    }
                    else "requested_list"
                    if list_response_requested
                    else "concise"
                )
            generation_temperature = float(
                getattr(self._generator, "last_temperature", 0.0)
            )
        generation_usage = TokenUsage() if deterministic else self._generator.last_usage
        if (
            not deterministic
            and list_response_requested
            and not re.search(r"(?m)^\s*(?:[-*]|\d+\.)\s+\S", generated.answer)
        ):
            initial_usage = generation_usage
            generated = await self._generator.repair(
                answer_question,
                documents,
                state.get("language", "mixed"),
                generated,
                answer_style="requested_list",
            )
            generation_usage = _add_usage(initial_usage, self._generator.last_usage)
            list_style_repaired = True
        table_style_repaired = False
        if (
            not deterministic
            and answer_style in {"structured_tabular", "comparison_table"}
            and (
                answer_shape_metrics(generated.answer)["answer_table_count"] == 0
                or not generated.answer.lstrip().startswith("|")
            )
        ):
            initial_usage = generation_usage
            generated = await self._generator.repair(
                answer_question,
                documents,
                state.get("language", "mixed"),
                generated,
                answer_style=answer_style,
            )
            generation_usage = _add_usage(initial_usage, self._generator.last_usage)
            table_style_repaired = True
        if (
            not deterministic
            and state.get("query_intent") in {"ENTITY_OVERVIEW", "PROJECT_OVERVIEW"}
            and (
                state.get("query_intent") == "PROJECT_OVERVIEW"
                or _overview_style_repair_needed(self._request.question, generated.answer)
            )
        ):
            initial_usage = generation_usage
            generated = await self._generator.repair(
                self._request.question,
                documents,
                state.get("language", "mixed"),
                generated,
                answer_style=(
                    "project_overview"
                    if state.get("query_intent") == "PROJECT_OVERVIEW"
                    else "entity_overview"
                ),
            )
            generation_usage = _add_usage(initial_usage, self._generator.last_usage)
            overview_style_repaired = True
        generated = _normalize_citations(generated)
        if not (
            self._settings.incremental_verified_streaming_enabled
            and getattr(self, "_incremental_stream_active", False)
        ):
            generated = await self._grounding_verifier.attach_missing_citations(
                documents, generated
            )
        # The live path has already checked every citation-complete sentence
        # before publishing it. Mutating that prose afterward both repeats the
        # expensive cross-encoder pass and makes the final answer diverge from
        # what the client saw. The unchanged citation validator below rejects an
        # uncited sentence instead.
        generated = _normalize_citations(generated)
        generated, answer_shape_claims_removed = _enforce_table_claim_shape(
            generated, answer_style
        )
        coverage_missing = _coverage(coverage_expected_keys, generated.answer)
        stage_complete(
            "generate",
            self._request.project_id,
            began,
            input_count=len(documents),
            output_count=1,
            reason_code=(
                f"{getattr(self._generator, 'last_stream_timeout_kind', '').upper()}_PARTIAL"
                if getattr(self._generator, "last_stream_truncated", False)
                else "FEATURE_INVENTORY_EXTRACTION"
                if state.get("query_intent") == "FEATURE_INVENTORY"
                else "CODE_INVENTORY_EXTRACTION"
                if state.get("query_intent") == "CODE_INVENTORY"
                else "DELIVERY_METADATA_EXTRACTION"
                if state.get("query_intent") == "DELIVERY" and deterministic
                else "CODE_LOCATION_EXTRACTION"
                if state.get("query_intent") == "IMPLEMENTATION" and deterministic
                else "POPULATION_INVENTORY_EXTRACTION"
                if deterministic and coverage_expected_keys
                else "EXACT_IDENTIFIER_EXTRACTION"
                if deterministic
                else "OVERVIEW_STYLE_REPAIRED"
                if overview_style_repaired
                else "LIST_STYLE_REPAIRED"
                if list_style_repaired
                else "TABLE_STYLE_REPAIRED"
                if table_style_repaired
                else "OK"
            ),
            model_provider="deterministic" if deterministic else self._settings.llm_provider,
            model_name=(
                "jira-metadata-extractor"
                if state.get("query_intent") == "DELIVERY" and deterministic
                else "code-location-extractor"
                if state.get("query_intent") == "IMPLEMENTATION" and deterministic
                else "population-inventory-extractor"
                if deterministic and coverage_expected_keys
                else "exact-identifier-extractor"
                if deterministic
                else self._generator.model_name
            ),
            model_profile="extraction" if deterministic else self._request.model_profile,
            language=state.get("language", "und"),
            extra={
                "query_intent": state.get("query_intent", "DIRECT"),
                "temperature": generation_temperature,
                "requested_entity": requested_entity,
                "entity_excluded_count": entity_excluded_count,
                "entity_excluded_titles": entity_excluded_titles,
                "scope_bypassed": scope_bypassed,
                "sibling_expanded_count": sibling_expanded_count,
                "list_response_requested": list_response_requested,
                "list_style_repaired": list_style_repaired,
                "table_style_repaired": table_style_repaired,
                "answer_shape_selected": answer_shape_selected,
                "answer_shape_reason": answer_shape_reason,
                "answer_shape_claims_removed": answer_shape_claims_removed,
                "coverage_expected": len(coverage_expected_keys),
                "coverage_covered": len(coverage_expected_keys) - len(coverage_missing),
                "coverage_missing": list(coverage_missing),
                "population_retrieval_miss": population_retrieval_miss,
                "documents_dropped": int(
                    getattr(self._generator, "last_documents_dropped", 0)
                ),
                "documents_truncated": int(
                    getattr(self._generator, "last_documents_truncated", 0)
                ),
                "prose_stream_seconds": round(
                    getattr(self._generator, "last_prose_stream_seconds", 0.0), 3
                ),
                "answer_metadata_seconds": round(
                    getattr(self._generator, "last_answer_metadata_seconds", 0.0), 3
                ),
                "time_to_first_chunk_seconds": round(
                    getattr(
                        self._generator, "last_time_to_first_chunk_seconds", 0.0
                    ),
                    3,
                ),
                "stream_timeout_kind": getattr(
                    self._generator, "last_stream_timeout_kind", ""
                ),
                "stream_truncated": int(
                    getattr(self._generator, "last_stream_truncated", False)
                ),
                **answer_shape_metrics(generated.answer),
            },
            **generation_usage.model_dump(),
        )
        return {
            "generated": generated,
            "documents": documents,
            "answer_style": answer_style,
            "coverage_expected": len(coverage_expected_keys),
            "coverage_expected_identifiers": coverage_expected_keys,
            "coverage_covered": len(coverage_expected_keys) - len(coverage_missing),
            "coverage_missing": coverage_missing,
            "population_retrieval_miss": population_retrieval_miss,
            "stream_truncated": bool(
                getattr(self._generator, "last_stream_truncated", False)
            ),
        }

    async def _validate_completeness(self, state: RagState) -> RagState:
        began = started()
        if state.get("grounded") is False:
            return {"missing_requirements": ()}
        answer_question = state.get("resolved_question") or self._request.question
        missing = _missing_answer_requirements(
            answer_question,
            state["generated"].answer,
            self._vocabulary.entities,
        )
        if state.get("query_intent") in {
            "FEATURE_INVENTORY",
            "CODE_INVENTORY",
        } and set(
            state["generated"].citations
        ) != set(range(1, len(state.get("documents", [])) + 1)):
            missing = (*missing, "inventory:all_sources")
        exhausted = bool(missing) and state.get("retrieval_attempt", 1) >= self._settings.max_retrieval_attempts
        stage_complete(
            "answer_completeness",
            self._request.project_id,
            began,
            input_count=len(
                _answer_requirements(answer_question, self._vocabulary.entities)
            ),
            output_count=0 if missing else 1,
            reason_code=(
                "COMPLETE"
                if not missing
                else "INCOMPLETE_EXHAUSTED"
                if exhausted
                else "INCOMPLETE_REPAIRABLE"
            ),
            retry_count=1 if exhausted else 0,
            language=state.get("language", "und"),
            extra={"missing_requirement_count": len(missing)},
        )
        result: RagState = {"missing_requirements": missing}
        if exhausted:
            result["grounded"] = False
            result["grounding_reason"] = "INCOMPLETE_ANSWER"
        return result

    def _route_after_completeness(self, state: RagState) -> str:
        if state.get("grounded") is False:
            return "end"
        if not state.get("missing_requirements"):
            return "verify_grounding"
        if state.get("retrieval_attempt", 1) < self._settings.max_retrieval_attempts:
            return "repair_completeness"
        return "end"

    async def _repair_completeness(self, state: RagState) -> RagState:
        began = started()
        answer_question = state.get("resolved_question") or self._request.question
        query = _completeness_repair_query(
            answer_question,
            state.get("documents", []),
            state.get("missing_requirements", ()),
        )
        stage_complete(
            "completeness_repair",
            self._request.project_id,
            began,
            input_count=len(state.get("missing_requirements", ())),
            output_count=1,
            reason_code="BOUNDED_RETRIEVAL_REPAIR",
            retry_count=1,
            language=state.get("language", "und"),
        )
        return {
            "queries": (query,),
            "retrieval_attempt": state.get("retrieval_attempt", 1) + 1,
            "preserve_candidates": True,
            "missing_requirements": (),
            "repair_requirements": state.get("missing_requirements", ()),
            "prior_documents": state.get("documents", []),
            "grounded": True,
        }

    async def _validate_citations(self, state: RagState) -> RagState:
        began = started()
        generated = state["generated"]
        if _citations_valid(generated, len(state["documents"])):
            stage_complete("validate_citations", self._request.project_id, began, input_count=len(generated.citations), output_count=len(generated.citations))
            return {"repaired": False}
        stage_complete(
            "validate_citations",
            self._request.project_id,
            began,
            input_count=len(generated.citations),
            output_count=0,
            reason_code=_citation_failure_reason(generated, len(state["documents"])),
        )
        repair_kwargs = (
            {"answer_style": state["answer_style"]}
            if state.get("answer_style")
            in {"structured_tabular", "comparison_table"}
            else _overview_repair_kwargs(state.get("query_intent", "DIRECT"))
        )
        repaired = await self._generator.repair(
            self._request.question,
            state["documents"],
            state.get("language", "mixed"),
            generated,
            **repair_kwargs,
        )
        repaired = _normalize_citations(repaired)
        repaired = await self._grounding_verifier.attach_missing_citations(
            state["documents"], repaired
        )
        repaired = _normalize_citations(repaired)
        if not _citations_valid(repaired, len(state["documents"])):
            # Repair failed. Before discarding the answer, try dropping only the
            # claims that carry no citation: one uncited sentence used to cost
            # every verified sentence beside it. Every survivor still carries a
            # marker and still faces per-claim grounding, so the guarantee is
            # unchanged -- only the blast radius of one bad sentence is.
            salvaged, dropped = drop_uncited_claims(repaired, len(state["documents"]))
            if dropped:
                stage_complete(
                    "citation_repair",
                    self._request.project_id,
                    began,
                    input_count=len(repaired.citations),
                    output_count=len(salvaged.citations),
                    reason_code="UNCITED_CLAIMS_DROPPED",
                    model_provider=self._settings.llm_provider,
                    model_name=self._generator.model_name,
                    model_profile=self._request.model_profile,
                    language=state.get("language", "und"),
                    extra={"uncited_claims_dropped": dropped},
                    **self._generator.last_usage.model_dump(),
                )
                return {
                    "generated": _note_removed_claims(salvaged, dropped),
                    "repaired": True,
                }
            stage_complete(
                "citation_repair",
                self._request.project_id,
                began,
                input_count=len(repaired.citations),
                output_count=0,
                reason_code=_citation_failure_reason(repaired, len(state["documents"])),
            )
            return {"generated": repaired, "repaired": True, "grounded": False}
        stage_complete("validate_citations", self._request.project_id, began, input_count=len(generated.citations), output_count=len(repaired.citations), reason_code="REPAIRED")
        stage_complete(
            "citation_repair",
            self._request.project_id,
            began,
            input_count=len(generated.citations),
            output_count=len(repaired.citations),
            reason_code="REPAIRED",
            model_provider=self._settings.llm_provider,
            model_name=self._generator.model_name,
            model_profile=self._request.model_profile,
            language=state.get("language", "und"),
            **self._generator.last_usage.model_dump(),
        )
        return {"generated": repaired, "repaired": True}

    async def _verify_grounding(self, state: RagState) -> RagState:
        began = started()
        answer_question = state.get("resolved_question") or self._request.question
        if state.get("query_intent") == "IMPLEMENTATION":
            expected = _deterministic_code_location_answer(
                answer_question,
                state["documents"],
                state.get("language", "mixed"),
                self._vocabulary.code_extensions,
            )
            if expected is not None and state["generated"] == expected:
                stage_complete(
                    "verify_grounding",
                    self._request.project_id,
                    began,
                    input_count=len(expected.citations),
                    output_count=1,
                    reason_code="CODE_LOCATION_VERIFIED",
                    model_provider="deterministic",
                    model_name="code-location-verifier",
                    model_profile="grounding",
                    language=state.get("language", "und"),
                    extra={
                        "query_intent": "IMPLEMENTATION",
                        "source_route": state.get("source_route", "CONFLUENCE_GITHUB"),
                    },
                )
                return {
                    "generated": state["generated"],
                    "grounded": True,
                    "grounding_reason": "CODE_LOCATION_VERIFIED",
                    "repaired": state.get("repaired", False),
                }
        if state.get("query_intent") == "DELIVERY":
            expected = _deterministic_delivery_answer(
                answer_question,
                state["documents"],
                state.get("language", "mixed"),
            )
            if expected is not None and state["generated"] == expected:
                stage_complete(
                    "verify_grounding",
                    self._request.project_id,
                    began,
                    input_count=len(expected.citations),
                    output_count=1,
                    reason_code="JIRA_METADATA_VERIFIED",
                    model_provider="deterministic",
                    model_name="jira-metadata-verifier",
                    model_profile="grounding",
                    language=state.get("language", "und"),
                    extra={"query_intent": "DELIVERY", "source_route": "JIRA"},
                )
                return {
                    "generated": state["generated"],
                    "grounded": True,
                    "grounding_reason": "JIRA_METADATA_VERIFIED",
                    "repaired": state.get("repaired", False),
                }
        if state.get("query_intent") == "FEATURE_INVENTORY":
            verified = _feature_inventory_answer_verified(
                state["generated"],
                state["documents"],
                state.get("overview_entity", ""),
            )
            stage_complete(
                "verify_grounding",
                self._request.project_id,
                began,
                input_count=len(state["generated"].citations),
                output_count=1 if verified else 0,
                reason_code=(
                    "TITLE_INVENTORY_VERIFIED"
                    if verified
                    else "TITLE_INVENTORY_MISMATCH"
                ),
                model_provider="deterministic",
                model_name="indexed-title-verifier",
                model_profile="grounding",
                language=state.get("language", "und"),
            )
            return {
                "generated": state["generated"],
                "grounded": verified,
                "grounding_reason": (
                    "TITLE_INVENTORY_VERIFIED"
                    if verified
                    else "TITLE_INVENTORY_MISMATCH"
                ),
                "repaired": state.get("repaired", False),
            }
        if state.get("query_intent") == "CODE_INVENTORY":
            verified = _code_inventory_answer_verified(
                state["generated"], state["documents"]
            )
            stage_complete(
                "verify_grounding",
                self._request.project_id,
                began,
                input_count=len(state["generated"].citations),
                output_count=1 if verified else 0,
                reason_code="CODE_INVENTORY_VERIFIED" if verified else "CODE_INVENTORY_MISMATCH",
                model_provider="deterministic",
                model_name="code-metadata-verifier",
                model_profile="grounding",
                language=state.get("language", "und"),
                extra={"query_intent": "CODE_INVENTORY", "source_route": "GITHUB"},
            )
            return {
                "generated": state["generated"],
                "grounded": verified,
                "grounding_reason": "CODE_INVENTORY_VERIFIED" if verified else "CODE_INVENTORY_MISMATCH",
                "repaired": state.get("repaired", False),
            }
        authority_valid, authority_reason = _source_authority_valid(
            state.get("query_intent", "DIRECT"),
            state["generated"],
            state["documents"],
        )
        if not authority_valid:
            stage_complete(
                "verify_grounding",
                self._request.project_id,
                began,
                input_count=len(state["generated"].citations),
                output_count=0,
                reason_code=authority_reason,
                model_provider="deterministic",
                model_name="source-authority-verifier",
                model_profile="grounding",
                language=state.get("language", "und"),
                extra={
                    "query_intent": state.get("query_intent", "DIRECT"),
                    "source_route": state.get("source_route", "MIXED"),
                },
            )
            return {"grounded": False, "grounding_reason": authority_reason}
        if not self._settings.grounding_verification_enabled:
            stage_complete(
                "verify_grounding",
                self._request.project_id,
                began,
                reason_code="DISABLED",
            )
            return {"grounded": True, "grounding_reason": "DISABLED"}
        verdict = await self._grounding_verifier.verify(
            self._request.question,
            state["documents"],
            state["generated"],
            answer_language=state.get("language", ""),
        )
        usage = self._grounding_verifier.last_usage
        grounded = verdict.supported
        reason_code = verdict.reason_code
        claim_fallback_removed_count = 0
        post_prune_regenerated = 0
        post_prune_below_floor = 0
        claim_pruning_bypassed = 0
        overview_intent = state.get("query_intent")
        # Grounding used to be all-or-nothing outside the two overview intents: one
        # unsupported sentence in a five-sentence answer discarded the four that
        # verified, and the user got a refusal for a question the corpus answers.
        # Dropping the sentence the verifier named is strictly safer than keeping
        # it and strictly more useful than refusing, so it is now tried for every
        # intent, before the more expensive regeneration path.
        if not grounded:
            pruned, claim_fallback_removed_count = _remove_unsupported_claims(
                state["generated"], verdict.unsupported_claims
            )
            minimum_claims = 2 if overview_intent == "PROJECT_OVERVIEW" else 1
            claim_pruning_bypassed = int(
                bool(claim_fallback_removed_count)
                and _material_sentence_count(pruned.answer) < minimum_claims
            )
            if (
                claim_fallback_removed_count
                and _material_sentence_count(pruned.answer) >= minimum_claims
                and _citations_valid(pruned, len(state["documents"]))
            ):
                fallback_verdict = await self._grounding_verifier.verify(
                    self._request.question,
                    state["documents"],
                    pruned,
                    answer_language=state.get("language", ""),
                )
                usage = _add_usage(usage, self._grounding_verifier.last_usage)
                grounded = fallback_verdict.supported
                if grounded and _missing_answer_requirements(
                    self._request.question,
                    pruned.answer,
                    self._vocabulary.entities,
                ):
                    grounded = False
                    fallback_verdict = fallback_verdict.model_copy(
                        update={"supported": False, "reason_code": "INSUFFICIENT_EVIDENCE"}
                    )
                if grounded:
                    reason_code = "CLAIMS_REMOVED_SUPPORTED"
                    floor = answer_sentence_floor(
                        self._settings, state.get("answer_style", "concise")
                    )
                    below_floor = _material_sentence_count(pruned.answer) < floor
                    unused_evidence = set(range(1, len(state["documents"]) + 1)) - set(
                        pruned.citations
                    )
                    if below_floor and unused_evidence:
                        post_prune_regenerated = 1
                        try:
                            regenerated = await self._generator.answer(
                                answer_question,
                                state["documents"],
                                state.get("language", "mixed"),
                                answer_style=state.get("answer_style", "concise"),
                            )
                        except TypeError as error:
                            if "answer_style" not in str(error):
                                raise
                            regenerated = await self._generator.answer(
                                answer_question,
                                state["documents"],
                                state.get("language", "mixed"),
                            )
                        usage = _add_usage(usage, self._generator.last_usage)
                        regenerated = _normalize_citations(regenerated)
                        regenerated = await self._grounding_verifier.attach_missing_citations(
                            state["documents"], regenerated
                        )
                        regenerated = _normalize_citations(regenerated)
                        if _citations_valid(regenerated, len(state["documents"])):
                            regenerated_verdict = await self._grounding_verifier.verify(
                                self._request.question,
                                state["documents"],
                                regenerated,
                                answer_language=state.get("language", ""),
                            )
                            usage = _add_usage(usage, self._grounding_verifier.last_usage)
                            if regenerated_verdict.supported:
                                pruned = regenerated
                                post_prune_below_floor = int(
                                    _material_sentence_count(pruned.answer) < floor
                                )
                                reason_code = (
                                    "AFTER_PRUNE_REGENERATED_THIN"
                                    if post_prune_below_floor
                                    else "AFTER_PRUNE_REGENERATED_SUPPORTED"
                                )
                            else:
                                reason_code = "CLAIMS_REMOVED_REGENERATION_REJECTED"
                        else:
                            reason_code = "CLAIMS_REMOVED_REGENERATION_REJECTED"
                    elif below_floor:
                        post_prune_below_floor = 1
                        reason_code = "CLAIMS_REMOVED_THIN_NO_UNUSED_EVIDENCE"
                    # Say so in the response. An answer that quietly lost a
                    # claim looks complete, and the reader cannot tell what was omitted.
                    state = {**state, "generated": _note_removed_claims(
                        pruned, claim_fallback_removed_count
                    )}
                else:
                    reason_code = fallback_verdict.reason_code
        if not grounded and not state.get("repaired", False):
            repair_kwargs = (
                {"answer_style": state["answer_style"]}
                if state.get("answer_style")
                in {"structured_tabular", "comparison_table"}
                else _overview_repair_kwargs(state.get("query_intent", "DIRECT"))
            )
            repaired = await self._generator.repair(
                self._request.question,
                state["documents"],
                state.get("language", "mixed"),
                state["generated"],
                **repair_kwargs,
            )
            repaired = _normalize_citations(repaired)
            repaired = await self._grounding_verifier.attach_missing_citations(
                state["documents"], repaired
            )
            repaired = _normalize_citations(repaired)
            if _citations_valid(repaired, len(state["documents"])):
                verdict = await self._grounding_verifier.verify(
                    self._request.question,
                    state["documents"],
                    repaired,
                    answer_language=state.get("language", ""),
                )
                usage = _add_usage(usage, self._grounding_verifier.last_usage)
                grounded = verdict.supported
                if grounded and _missing_answer_requirements(
                    self._request.question,
                    repaired.answer,
                    self._vocabulary.entities,
                ):
                    grounded = False
                    verdict = verdict.model_copy(
                        update={"supported": False, "reason_code": "INSUFFICIENT_EVIDENCE"}
                    )
                reason_code = "REPAIRED_SUPPORTED" if grounded else verdict.reason_code
                state = {**state, "generated": repaired}
        population_expected = tuple(state.get("coverage_expected_identifiers", ()))
        population_missing = _coverage(
            population_expected, state["generated"].answer
        )
        population_summary_violation = bool(population_expected) and bool(
            re.search(r"\bsuch as\b", state["generated"].answer, flags=re.IGNORECASE)
        )
        generated = _note_coverage_shortfall(
            state["generated"], population_expected, population_missing
        )
        if grounded and population_summary_violation:
            grounded = False
            reason_code = "INSUFFICIENT_EVIDENCE"
        stage_complete(
            "verify_grounding",
            self._request.project_id,
            began,
            input_count=len(state["generated"].citations),
            output_count=1 if grounded else 0,
            reason_code=reason_code,
            model_provider="local",
            model_name=self._grounding_verifier.model_name,
            model_profile="grounding",
            language=state.get("language", "und"),
            extra={
                "claim_fallback_removed_count": claim_fallback_removed_count,
                "post_prune_regenerated": post_prune_regenerated,
                "post_prune_below_floor": post_prune_below_floor,
                "claim_pruning_bypassed": claim_pruning_bypassed,
                "coverage_expected": len(population_expected),
                "coverage_covered": len(population_expected) - len(population_missing),
                "coverage_missing": list(population_missing),
                "population_summary_violation": population_summary_violation,
                "query_intent": state.get("query_intent", "DIRECT"),
                "source_route": state.get("source_route", "MIXED"),
                # Content-free per-claim diagnostics. A NO_ANSWER used to say only
                # UNSUPPORTED_CLAIM; these fields say which check rejected it and
                # by how much, which is the difference between reading a log and
                # reproducing the request by hand.
                **_rejection_telemetry(
                    getattr(self._grounding_verifier, "last_rejections", [])
                ),
                **_accepted_score_telemetry(
                    getattr(self._grounding_verifier, "last_accepted_scores", [])
                ),
                **answer_shape_metrics(
                    state["generated"].answer,
                    claims_removed=claim_fallback_removed_count,
                ),
            },
            **usage.model_dump(),
        )
        return {
            "generated": generated,
            "grounded": grounded,
            "grounding_reason": reason_code,
            "coverage_expected": len(population_expected),
            "coverage_covered": len(population_expected) - len(population_missing),
            "coverage_missing": population_missing,
            "repaired": state.get("repaired", False)
            or reason_code in {"REPAIRED_SUPPORTED", "CLAIMS_REMOVED_SUPPORTED"},
        }


def _note_removed_claims(value, removed: int):
    """Record in missing_information that a claim was dropped, not answered."""

    if removed < 1:
        return value
    note = (
        "One statement drafted from the sources could not be verified against them "
        "and was removed."
        if removed == 1
        else f"{removed} statements drafted from the sources could not be verified "
        "against them and were removed."
    )
    if note in value.missing_information:
        return value
    return value.model_copy(
        update={"missing_information": [*value.missing_information, note]}
    )


def _note_coverage_shortfall(value, expected: tuple[str, ...], missing: tuple[str, ...]):
    """Report incomplete inventory coverage without rejecting grounded claims."""

    if not missing:
        return value
    note = (
        f"{len(expected) - len(missing)} of {len(expected)} identifiers confirmed; "
        f"not confirmed: {', '.join(missing)}."
    )
    if note in value.missing_information:
        return value
    return value.model_copy(
        update={"missing_information": [*value.missing_information, note]}
    )


def _accepted_score_telemetry(scores: list) -> dict[str, object]:
    """Report the accepted-claim score distribution alongside the rejections.

    Without this only the closest miss is visible, so a threshold can only be
    nudged by guesswork. Reporting both sides shows whether accepted and rejected
    claims are actually separable at any threshold, or overlap -- in which case
    moving the number trades false refusals for unsupported claims rather than
    fixing anything. Content-free: scores only, no claim text.
    """

    if not scores:
        return {}
    ordered = sorted(scores)
    return {
        "grounding_accepted_claim_count": len(ordered),
        "grounding_accepted_score_min": ordered[0],
        "grounding_accepted_score_median": ordered[len(ordered) // 2],
        "grounding_accepted_score_max": ordered[-1],
    }


def _rejection_telemetry(rejections: list) -> dict[str, object]:
    """Summarise per-claim grounding rejections as flat, content-free fields."""

    if not rejections:
        return {}
    reasons: dict[str, int] = {}
    for rejection in rejections:
        reasons[rejection.reason] = reasons.get(rejection.reason, 0) + 1
    scored = [rejection for rejection in rejections if rejection.score is not None]
    summary: dict[str, object] = {
        "grounding_rejected_claim_count": len(rejections),
        "grounding_rejection_reasons": ",".join(
            f"{reason}={count}" for reason, count in sorted(reasons.items())
        ),
        "grounding_rejected_table_evidence_count": sum(
            1 for rejection in rejections if rejection.table_evidence
        ),
    }
    if scored:
        # The closest miss is the number that says whether the threshold is the
        # problem or the evidence is.
        best = max(scored, key=lambda rejection: rejection.score or 0.0)
        summary["grounding_best_rejected_score"] = best.score
        summary["grounding_applied_threshold"] = best.threshold
    return summary

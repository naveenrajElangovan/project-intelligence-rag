"""Generic inventory-intent detection without domain or provider allowlists."""

from __future__ import annotations

import re

from app.workflow_support.identifiers import member_identifiers


_EXPLICIT_INVENTORY = re.compile(
    r"\b(?:list|enumerate|show|give|tell|"
    r"lista|listar|enumera|enumerar|muestra|muestrame|dame|dime|indica)\b"
    r".{0,40}\b(?:all|every|available|supported|existing|configured|defined|"
    r"todos|todas|cada|disponibles|soportados|existentes|configurados|"
    r"definidos)\b",
    re.IGNORECASE,
)
_ALL_ITEMS = re.compile(
    r"\b(?:all|every|todos|todas|cada)\b.{0,60}\b[a-z][a-z0-9_-]*s\b",
    re.IGNORECASE,
)
_PLURAL_QUESTION = re.compile(
    r"\b(?:(?:what|which)\s+are|(?:cu[aá]les|qu[eé])\s+son)\b"
    r".{0,60}\b[a-z][a-z0-9_-]*s\b",
    re.IGNORECASE,
)
_PLURAL_SUBJECT_QUESTION = re.compile(
    r"\b(?:what|which|cu[aá]les|qu[eé])\s+[a-z][a-z0-9_-]*s\s+"
    r"(?:are|exist|remain|apply|son|existen|quedan|aplican)\b",
    re.IGNORECASE,
)
_PLURAL_AUXILIARY_QUESTION = re.compile(
    r"\b(?:what|which|cu[aá]les|qu[eé])\s+"
    r"(?:[a-z][a-z0-9_-]*\s+){0,2}[a-z][a-z0-9_-]*s\s+"
    r"(?:does|do|did|can|could|will|would|should|"
    r"hace|hacen|usa|usan|utiliza|utilizan|puede|pueden|debe|deben)\b",
    re.IGNORECASE,
)
_PLURAL_EXISTENCE = re.compile(
    r"\b[a-z][a-z0-9_-]*s\s+"
    r"(?:exist|are\s+there|are\s+available|are\s+supported|are\s+defined|"
    r"existen|hay|est[aá]n\s+disponibles|son\s+soportados|"
    r"est[aá]n\s+definidos)\b",
    re.IGNORECASE,
)
_INVENTORY_NOUN = re.compile(
    r"\b(?:inventory|catalog|registry|matrix|available options|supported values|"
    r"inventario|cat[aá]logo|registro(?!\s+(?:un|una|el|la|los|las)\b)|matriz|opciones\s+disponibles|"
    r"valores\s+soportados)\b",
    re.IGNORECASE,
)

_EXHAUSTIVE_DETAIL = re.compile(
    r"\b(?:all|every|full|complete|entire|"
    r"todo|toda|todos|todas|completo|completa|entero|entera)\b",
    re.IGNORECASE,
)
_ENTITY_DETAIL_NOUN = re.compile(
    r"\b(?:details?|fields?|parameters?|payload|schema|attributes?|properties|contract|"
    r"detalles?|campos?|par[aá]metros?|esquema|atributos?|propiedades|"
    r"contrato)\b",
    re.IGNORECASE,
)


def is_exhaustive_entity_detail_question(question: str) -> bool:
    """Return true for every-field requests about one explicit identifier."""

    normalized = " ".join(question.split())
    plural_field_request = bool(
        re.search(
            r"\b(?:fields|parameters|attributes|properties|campos|par[aá]metros|"
            r"atributos|propiedades)\b",
            normalized,
            re.IGNORECASE,
        )
    )
    return bool(
        member_identifiers(normalized)
        and (_EXHAUSTIVE_DETAIL.search(normalized) or plural_field_request)
        and _ENTITY_DETAIL_NOUN.search(normalized)
    )


def is_inventory_question(question: str) -> bool:
    """Return true when the user requests a collection rather than one fact."""

    normalized = " ".join(question.split())
    # In these Spanish forms ``registro`` is the first-person verb "I record",
    # not the inventory noun "registry".
    if re.search(r"(?i)\bc[oó]mo\s+registro\b", normalized):
        return False
    if member_identifiers(normalized):
        return False
    return any(
        pattern.search(normalized)
        for pattern in (
            _EXPLICIT_INVENTORY,
            _ALL_ITEMS,
            _PLURAL_QUESTION,
            _PLURAL_SUBJECT_QUESTION,
            _PLURAL_AUXILIARY_QUESTION,
            _PLURAL_EXISTENCE,
            _INVENTORY_NOUN,
        )
    )

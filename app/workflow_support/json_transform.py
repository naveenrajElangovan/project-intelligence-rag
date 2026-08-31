"""Deterministic JSON parsing and formatting for the chat surface.

A JSON conversion has no evidence, so it must not travel through retrieval,
reranking, citation validation, completeness validation, or grounding
verification: every one of those gates would correctly reject an answer with no
cited source. This module answers such a request entirely in Python, with no
model call, so the result is exact, instant, free, and reproducible.

The behaviour is bilingual because the surrounding service is: detection accepts
English and Spanish phrasing, and failures are reported in the language of the
request.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from app.llm import TokenUsage
from app.models import MAX_PAYLOAD_QUESTION_CHARACTERS, RagRequest, RagResponse
from app.telemetry import request_complete, stage_complete
from app.workflow_support.query_analysis import detect_query_language


# Bounds. A chat message is not a file-upload channel, and an unbounded nesting
# depth is a denial-of-service surface in any recursive formatter.
# One ceiling, defined with the contract that enforces it. A payload the request
# model accepts must not then be rejected by the transformer, and vice versa.
MAX_PAYLOAD_CHARACTERS = MAX_PAYLOAD_QUESTION_CHARACTERS
MAX_NESTING_DEPTH = 64
MAX_UNWRAP_ROUNDS = 5

# A message that is essentially nothing but a payload is a conversion request on
# its own: there is no question in it to answer any other way. The allowance is
# what may surround the payload -- a colon, a "here:", a stray quote -- before it
# stops being a bare paste and starts being prose with a snippet in it.
MAX_BARE_PAYLOAD_PROSE_CHARACTERS = 24

_INDENT = 2

# Indent-only pretty printing puts every scalar on its own line, so a document
# with a few hundred keys becomes a few hundred lines: hard to read, hard to
# select with a mouse, and slow to render one Text node per line in the client.
# Filling to a width instead keeps anything that fits on one line and only breaks
# what does not, which is how a formatter is normally expected to behave.
LINE_WIDTH = 100

_ENGLISH_TRIGGERS = (
    "convert to json",
    "convert this to json",
    "to json object",
    "json object",
    "parse this json",
    "parse json",
    "format json",
    "format this json",
    "pretty print",
    "prettify json",
    "beautify json",
    "json converter",
    "convert json",
    "fix this json",
    "fix json",
    "valid json",
    "unescape json",
    "decode json",
    "json string to object",
)
_SPANISH_TRIGGERS = (
    "convertir a json",
    "convertir en json",
    "convierte a json",
    "convierte esto a json",
    "objeto json",
    "formatear json",
    "formatea json",
    "formatear el json",
    "analizar json",
    "parsear json",
    "arreglar json",
    "corregir json",
    "json valido",
    "validar json",
    "decodificar json",
    "convertidor json",
    "cadena json a objeto",
)

_FENCE = re.compile(
    r"```[ \t]*(?:json|jsonc|json5)?[ \t]*\r?\n(?P<body>.*?)```",
    flags=re.DOTALL | re.IGNORECASE,
)


class _NonFiniteConstant(Exception):
    """Raised for NaN or Infinity, which Python's parser accepts but JSON forbids."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


def _reject_non_finite(token: str) -> object:
    raise _NonFiniteConstant(token)


@dataclass(frozen=True, slots=True)
class JsonTransformRequest:
    """A detected request to reformat a payload the user supplied inline."""

    payload: str
    language: str


@dataclass(slots=True)
class JsonTransformResult:
    """The outcome of a conversion, successful or not."""

    ok: bool
    text: str
    repairs: list[str] = field(default_factory=list)
    unwrap_rounds: int = 0
    error_message: str = ""
    error_line: int = 0
    error_column: int = 0


def detect_json_transform_request(
    question: str, language: str
) -> JsonTransformRequest | None:
    """Return a conversion request only when the message asks for one and carries JSON.

    Two independent paths qualify. Either the message asks for a conversion in so
    many words and carries a payload, or it is a bare paste with no real question
    in it. Both still require an actual payload, so a project question such as
    "how does the application build its JSON catalog?" is never hijacked, and prose that
    merely contains braces is not a conversion request.
    """

    if not question or len(question) > MAX_PAYLOAD_CHARACTERS:
        return None
    if _requests_json_transform(question):
        candidates = _payload_candidates(question)
    else:
        bare = _bare_payload(question)
        candidates = [bare] if bare else []
    if not candidates:
        return None
    # Let the parser choose between candidates rather than trusting the pattern
    # that matched. A quoted run inside a valid object can look like an escaped
    # document, so the only reliable test is whether it actually decodes.
    for candidate in candidates:
        if transform_json(candidate).ok:
            return JsonTransformRequest(payload=candidate, language=language)
    # Nothing decoded. Report the most structural candidate so the user gets a
    # precise parse error instead of silence.
    return JsonTransformRequest(payload=candidates[0], language=language)


def transform_json(payload: str) -> JsonTransformResult:
    """Parse, repair if needed, and pretty-print. Never guess silently."""

    if len(payload) > MAX_PAYLOAD_CHARACTERS:
        return JsonTransformResult(
            ok=False,
            text=payload,
            error_message=(
                f"the payload is {len(payload)} characters, above the "
                f"{MAX_PAYLOAD_CHARACTERS} character limit"
            ),
        )
    value, unwrap_rounds, repairs, error = _decode(payload)
    if error is not None:
        return JsonTransformResult(
            ok=False,
            text=payload,
            repairs=repairs,
            unwrap_rounds=unwrap_rounds,
            error_message=error.msg,
            error_line=error.lineno,
            error_column=error.colno,
        )
    depth = _depth(value)
    if depth > MAX_NESTING_DEPTH:
        return JsonTransformResult(
            ok=False,
            text=payload,
            repairs=repairs,
            unwrap_rounds=unwrap_rounds,
            error_message=(
                f"the payload nests {depth} levels deep, above the "
                f"{MAX_NESTING_DEPTH} level limit"
            ),
        )
    return JsonTransformResult(
        ok=True,
        text=format_json(value),
        repairs=repairs,
        unwrap_rounds=unwrap_rounds,
    )



def _inline(value: object) -> str:
    """Compact single-line form. ensure_ascii=False keeps accented Spanish readable."""

    return json.dumps(
        value, ensure_ascii=False, separators=(", ", ": "), allow_nan=False
    )


def format_json(value: object, width: int = LINE_WIDTH, indent: int = _INDENT) -> str:
    """Serialize filling the available width rather than one value per line."""

    lines: list[str] = []
    _write(value, 0, width, indent, lines)
    return "\n".join(lines)


def _write(
    value: object,
    depth: int,
    width: int,
    indent: int,
    lines: list[str],
    prefix: str = "",
) -> None:
    pad = " " * (depth * indent)
    head = f"{pad}{prefix}"
    if not isinstance(value, (dict, list)) or not value:
        lines.append(head + _inline(value))
        return
    flat = _inline(value)
    if len(head) + len(flat) <= width:
        # The whole subtree fits, so there is nothing to gain by breaking it.
        lines.append(head + flat)
        return
    if isinstance(value, dict):
        lines.append(head + "{")
        items = list(value.items())
        child_pad = " " * ((depth + 1) * indent)
        # Runs of scalar-valued pairs are packed across the width for the same
        # reason scalar arrays are: a flat object of 200 numbers was 200 lines.
        # A pair whose value is a container ends the run and is written expanded,
        # so key order is preserved either way.
        row = ""
        for index, (key, item) in enumerate(items):
            separator = "," if index < len(items) - 1 else ""
            if isinstance(item, (dict, list)) and item:
                if row:
                    lines.append(row)
                    row = ""
                _write(
                    item,
                    depth + 1,
                    width,
                    indent,
                    lines,
                    prefix=f"{json.dumps(key, ensure_ascii=False)}: ",
                )
                lines[-1] += separator
                continue
            piece = f"{json.dumps(key, ensure_ascii=False)}: {_inline(item)}{separator}"
            if not row:
                row = child_pad + piece
            elif len(row) + 1 + len(piece) <= width:
                row += " " + piece
            else:
                lines.append(row)
                row = child_pad + piece
        if row:
            lines.append(row)
        lines.append(pad + "}")
        return
    lines.append(head + "[")
    child_pad = " " * ((depth + 1) * indent)
    if all(not isinstance(item, (dict, list)) for item in value):
        # A run of scalars is the worst case for indent-only output: a list of 200
        # shortcut names became 200 lines. Pack them across the width instead.
        row = ""
        for index, item in enumerate(value):
            piece = _inline(item) + ("," if index < len(value) - 1 else "")
            if not row:
                row = child_pad + piece
            elif len(row) + 1 + len(piece) <= width:
                row += " " + piece
            else:
                lines.append(row)
                row = child_pad + piece
        if row:
            lines.append(row)
    else:
        for index, item in enumerate(value):
            _write(item, depth + 1, width, indent, lines)
            if index < len(value) - 1:
                lines[-1] += ","
    lines.append(pad + "]")


def json_transform_answer(result: JsonTransformResult, language: str) -> str:
    """Render the user-visible answer for a conversion, in the request's language."""

    spanish = language == "es"
    if not result.ok:
        position = (
            f" (línea {result.error_line}, columna {result.error_column})"
            if spanish
            else f" (line {result.error_line}, column {result.error_column})"
        ) if result.error_line else ""
        heading = (
            "No pude convertir esto en JSON válido"
            if spanish
            else "I could not convert this into valid JSON"
        )
        reason = (
            f"{heading}{position}: {result.error_message}."
            if result.error_message
            else f"{heading}{position}."
        )
        tail = (
            "\n\nDevuelvo la entrada sin cambios para que no se pierda nada."
            if spanish
            else "\n\nI have left the input unchanged so nothing is lost."
        )
        return reason + tail + "\n\n```\n" + result.text + "\n```"
    notes: list[str] = []
    if result.unwrap_rounds:
        notes.append(
            f"Decodifiqué {result.unwrap_rounds} nivel(es) de cadena JSON escapada."
            if spanish
            else f"Decoded {result.unwrap_rounds} level(s) of escaped JSON string."
        )
    if result.repairs:
        joined = ", ".join(_repair_label(name, spanish) for name in result.repairs)
        notes.append(
            f"El JSON no era estrictamente válido; apliqué: {joined}."
            if spanish
            else f"The JSON was not strictly valid; I applied: {joined}."
        )
    prefix = ("\n".join(notes) + "\n\n") if notes else ""
    return prefix + "```json\n" + result.text + "\n```"


def json_transform_response(request: RagRequest, began: float) -> RagResponse | None:
    """Answer an inline JSON conversion deterministically, or return None.

    Called before the graph, so a conversion performs no retrieval, spends no
    provider embedding quota, and makes no model call. It also bypasses the
    citation, completeness, and grojj∆unding gates, which is correct rather than
    convenient: a conversion has no evidence and would fail all three by
    construction.
    """

    language = detect_query_language(request.question)
    detected = detect_json_transform_request(request.question, language)
    if detected is None:
        return None
    result = transform_json(detected.payload)
    stage_complete(
        "json_transform",
        request.project_id,
        began,
        input_count=1,
        output_count=1,
        reason_code="JSON_TRANSFORMED" if result.ok else "JSON_INVALID",
        model_provider="none",
        model_name="none",
        model_profile=request.model_profile,
        language=language,
        **TokenUsage().model_dump(),
    )
    response = RagResponse(
        answer=json_transform_answer(result, language),
        confidence="HIGH" if result.ok else "NONE",
        project_id=request.project_id,
        sources=[],
        missing_information=[],
        # Distinct statuses so a client can tell a deterministic transformation
        # apart from a grounded, cited project answer.
        evidence_status="NOT_APPLICABLE",
        context_quality="NOT_APPLICABLE",
        context_relevance=0.0,
        context_completeness=0.0,
        conversation_context_update=None,
    )
    request_complete(
        began=began,
        outcome="JSON_TRANSFORM" if result.ok else "JSON_TRANSFORM_FAILED",
        confidence=response.confidence,
        model_profile=request.model_profile,
        language=language,
    )
    return response


def _bare_payload(question: str) -> str | None:
    """Return the payload when the message is a paste with no real question in it.

    Requiring a trigger phrase kept "how does the application build its JSON catalog?"
    from being hijacked, but it also meant pasting a document on its own did
    nothing. Prose is what creates the ambiguity, so the test is how much prose
    surrounds the payload rather than which words appear in it.
    """

    stripped = question.strip()
    if not stripped:
        return None
    fenced = _FENCE.search(stripped)
    if fenced:
        # A fence with nothing outside it is as explicit as a trigger phrase.
        if not _FENCE.sub("", stripped).strip():
            body = fenced.group("body").strip()
            return body or None
        return None
    for candidate in (_widest_structural_span(stripped), _widest_quoted_span(stripped)):
        if not candidate:
            continue
        remainder = stripped.replace(candidate, "", 1)
        remainder = "".join(
            character for character in remainder if not character.isspace()
        ).strip(":=-\u2014\u2013.\u00bf?\u00a1!\"'")
        if len(remainder) <= MAX_BARE_PAYLOAD_PROSE_CHARACTERS:
            return candidate
    return None


def _requests_json_transform(question: str) -> bool:
    folded = _fold(question)
    return any(trigger in folded for trigger in _ENGLISH_TRIGGERS + _SPANISH_TRIGGERS)


def _fold(value: str) -> str:
    """Casefold and strip accents so "válido" and "valido" both match."""

    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )


def _payload_candidates(question: str) -> list[str]:
    """Return every plausible JSON body in the message, best structural guess first.

    An explicit fence is authoritative. Otherwise both a balanced object/array span
    and a quoted escaped-document span are offered, and the caller decides by
    parsing.
    """

    fenced = _FENCE.search(question)
    if fenced:
        body = fenced.group("body").strip()
        return [body] if body else []
    candidates: list[str] = []
    for candidate in (_widest_structural_span(question), _widest_quoted_span(question)):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _widest_structural_span(value: str) -> str | None:
    """Return the outermost balanced object or array, ignoring braces in strings."""

    # Try whichever delimiter opens first, so an object nested inside an array is
    # not mistaken for the whole payload.
    candidates = sorted(
        (
            (value.find(opener), opener, closer)
            for opener, closer in (("{", "}"), ("[", "]"))
            if value.find(opener) >= 0
        )
    )
    for start, opener, closer in candidates:
        depth = 0
        end = -1
        in_string = False
        escaped = False
        for index in range(start, len(value)):
            character = value[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == opener:
                depth += 1
            elif character == closer:
                depth -= 1
                if depth == 0:
                    end = index
                    # Keep going only across a run of sibling top-level values,
                    # so `{...}{...}` is captured whole and can be repaired into
                    # an array. Anything else ends the span here.
                    remainder = value[index + 1 :].lstrip()
                    if not remainder.startswith(opener):
                        break
        if end >= 0:
            return value[start : end + 1]
        # Unbalanced: the payload was cut before its closing bracket. Returning
        # None here meant a truncated paste was never even recognised as JSON --
        # the repair that completes it existed, and detection could not reach it,
        # so the fragment fell through to retrieval and was answered as a project
        # question. The span runs to the end of the text and _repair closes it.
        if start == 0 or not value[:start].strip():
            return value[start:]
    return None


def _widest_quoted_span(value: str) -> str | None:
    """Return a double-quoted run that itself looks like escaped JSON."""

    match = re.search(
        r'"\s*\\*"?\s*[\{\[].*[\}\]]\s*\\*"?\s*"', value, flags=re.DOTALL
    )
    return match.group(0) if match else None


def _decode(
    payload: str,
) -> tuple[object, int, list[str], json.JSONDecodeError | None]:
    """Strict parse first; unwrap escaped strings; only then attempt bounded repair."""

    repairs: list[str] = []
    current = payload.strip().lstrip("﻿")
    unwrap_rounds = 0
    last_error: json.JSONDecodeError | None = None
    for _ in range(MAX_UNWRAP_ROUNDS):
        try:
            # parse_constant rejects NaN and Infinity, which Python accepts by
            # default but JSON does not. Without this the value round-trips into
            # output that no strict JSON parser will read back.
            value = json.loads(current, parse_constant=_reject_non_finite)
        except (json.JSONDecodeError, _NonFiniteConstant) as error:
            last_error = (
                error
                if isinstance(error, json.JSONDecodeError)
                else json.JSONDecodeError(
                    f"{error.token} is not valid JSON", current, 0
                )
            )
            repaired, applied = _repair(current)
            if not applied:
                return None, unwrap_rounds, repairs, last_error
            repairs.extend(applied)
            current = repaired
            continue
        # A JSON document whose whole content is a string may itself hold JSON —
        # this is the doubly-encoded case, and unwrapping it is the point.
        if isinstance(value, str) and _is_json_document(value.strip()):
            current = value.strip()
            unwrap_rounds += 1
            continue
        return value, unwrap_rounds, repairs, None
    return None, unwrap_rounds, repairs, last_error


def _is_json_document(value: str) -> bool:
    """True when a decoded string is itself JSON, so it is worth unwrapping again.

    Testing by parsing rather than by first character means a doubly *or* triply
    encoded payload unwraps, while an ordinary string value such as "hello" is
    left exactly as the user wrote it.
    """

    if value[:1] not in ("{", "[", '"'):
        return False
    try:
        json.loads(value)
    except (json.JSONDecodeError, _NonFiniteConstant):
        return False
    return True


def _repair(value: str) -> tuple[str, list[str]]:
    """Apply conservative, individually named fixes for common malformed JSON.

    Each transformation is recorded so the answer can state exactly what was
    changed. Nothing here invents data: no key is added, no value is guessed, and
    a payload that still will not parse is reported as a failure.
    """

    applied: list[str] = []
    result = value

    def step(name: str, candidate: str) -> None:
        nonlocal result
        if candidate != result:
            result = candidate
            applied.append(name)

    step("bom", result.lstrip("﻿"))
    step(
        "smart_quotes",
        result.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})),
    )
    step("comments", _strip_comments(result))
    step("python_literals", re.sub(r"\b(None|True|False)\b", _python_literal, result))
    step("non_finite_numbers", re.sub(r"\b(NaN|-?Infinity)\b", "null", result))
    step("single_quotes", _single_to_double_quotes(result))
    step(
        "unquoted_keys",
        re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*:)", r'\1"\2"\3', result),
    )
    step("trailing_commas", re.sub(r",(\s*[}\]])", r"\1", result))
    step("concatenated_objects", _wrap_concatenated_objects(result))
    # Completion runs last, and only on what the earlier repairs produced: closing
    # brackets before quotes are normalised would balance the wrong structure.
    step("completed_truncation", _complete_truncated(result))
    return result, applied


def _complete_truncated(value: str) -> str:
    """Close a payload that simply stops, whatever it stops in the middle of.

    Truncation is the most common way JSON arrives broken -- a log line cut at a
    column limit, a console pane that scrolled, a half-selected block -- and the
    most mechanically fixable, because the open structure is known exactly rather
    than guessed.

    Every open container remembers its own fallback point: the end of the last
    element completed inside it, or the position just after its opening bracket
    when nothing inside completed. So a cut anywhere unwinds to the nearest
    salvageable boundary and closes outward, which is why
    `{"a": {"b": "part` becomes `{"a": {}}` rather than failing.

    Content is never invented. A dangling key, a partial value or a comma left by
    the cut is dropped, not filled with null: a fabricated field in a payload
    someone is about to paste into code is worse than a shorter payload. The only
    character ever added is a closing bracket or, for a bare top-level string, its
    closing quote.

    Returns the input unchanged when nothing is open, so a payload that was
    already complete records no repair.
    """

    # (opening character, index just after it, index of the last safe cut inside)
    stack: list[tuple[str, int, int]] = []
    in_string = False
    escaped = False

    def mark_safe(index: int) -> None:
        if stack:
            opener, after, _previous = stack[-1]
            stack[-1] = (opener, after, index)

    for index, character in enumerate(value):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
                # In an array a finished string is a finished element. In an
                # object it may be a key still waiting for its value, so the
                # boundary only moves on a comma or a closing brace.
                if stack and stack[-1][0] == "[":
                    mark_safe(index + 1)
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append((character, index + 1, index + 1))
        elif character in "}]":
            if stack:
                stack.pop()
            mark_safe(index + 1)
        elif character == ",":
            mark_safe(index)

    if not stack:
        if in_string:
            # A bare top-level string: closing the quote adds no content and
            # loses none, so it is the one completion worth making.
            return value + '"'
        return value

    if in_string:
        # The tail is a partial key or value, so unwind to the innermost
        # container's fallback point and discard the fragment.
        _opener, _after, safe = stack[-1]
        head = value[:safe].rstrip()
    else:
        # The payload ended on a boundary -- a finished value, or nothing at all
        # after an opening bracket. Everything present is complete, so only the
        # closers are missing. Unwinding here would throw away a whole pair that
        # simply had no trailing comma to mark it safe.
        head = value.rstrip()
    # A trailing comma, or a key whose value never arrived, cannot be closed.
    while head.endswith((",", ":")):
        head = head[:-1].rstrip()
        if head.endswith('"'):
            opening = head.rfind('"', 0, len(head) - 1)
            if opening > 0:
                head = head[:opening].rstrip().rstrip(",").rstrip()
    closers = {"{": "}", "[": "]"}
    return head + "".join(closers[opener] for opener, _after, _safe in reversed(stack))

def _python_literal(match: re.Match[str]) -> str:
    return {"None": "null", "True": "true", "False": "false"}[match.group(1)]


def _strip_comments(value: str) -> str:
    """Remove // and /* */ comments that appear outside string literals."""

    out: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(value):
        character = value[index]
        if in_string:
            out.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            out.append(character)
            index += 1
            continue
        if value.startswith("//", index):
            end = value.find("\n", index)
            index = len(value) if end < 0 else end
            continue
        if value.startswith("/*", index):
            end = value.find("*/", index + 2)
            index = len(value) if end < 0 else end + 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


def _single_to_double_quotes(value: str) -> str:
    """Convert single-quoted strings to double-quoted ones outside real strings."""

    if "'" not in value:
        return value
    out: list[str] = []
    index = 0
    in_double = False
    escaped = False
    while index < len(value):
        character = value[index]
        if in_double:
            out.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_double = False
            index += 1
            continue
        if character == '"':
            in_double = True
            out.append(character)
            index += 1
            continue
        if character == "'":
            end = index + 1
            body: list[str] = []
            while end < len(value):
                if value[end] == "\\" and end + 1 < len(value):
                    body.append(value[end : end + 2])
                    end += 2
                    continue
                if value[end] == "'":
                    break
                body.append(value[end])
                end += 1
            if end >= len(value):
                out.append(character)
                index += 1
                continue
            inner = "".join(body).replace('"', '\\"')
            out.append('"' + inner + '"')
            index = end + 1
            continue
        out.append(character)
        index += 1
    return "".join(out)


def _wrap_concatenated_objects(value: str) -> str:
    """Turn `{...}{...}` or `{...}\\n{...}` into a JSON array of those objects."""

    if not re.search(r"\}\s*\{", value):
        return value
    separated = re.sub(r"\}\s*\{", "},{", value)
    return "[" + separated + "]"


def _depth(value: object, current: int = 1) -> int:
    if isinstance(value, dict):
        return max(
            (_depth(item, current + 1) for item in value.values()), default=current
        )
    if isinstance(value, list):
        return max((_depth(item, current + 1) for item in value), default=current)
    return current


def _repair_label(name: str, spanish: bool) -> str:
    labels = {
        "bom": ("removed a byte-order mark", "quité una marca BOM"),
        "smart_quotes": ("replaced typographic quotes", "reemplacé comillas tipográficas"),
        "comments": ("removed comments", "quité comentarios"),
        "python_literals": (
            "converted None/True/False",
            "convertí None/True/False",
        ),
        "non_finite_numbers": (
            "replaced NaN and Infinity with null",
            "reemplacé NaN e Infinity por null",
        ),
        "single_quotes": ("converted single quotes", "convertí comillas simples"),
        "unquoted_keys": ("quoted bare keys", "puse comillas en las claves"),
        "trailing_commas": ("removed trailing commas", "quité comas finales"),
        "concatenated_objects": (
            "wrapped concatenated objects in an array",
            "envolví objetos concatenados en un arreglo",
        ),
    }
    english, spanish_label = labels.get(name, (name, name))
    return spanish_label if spanish else english

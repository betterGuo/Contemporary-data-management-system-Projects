"""Public answer-normalization entry points; no HTTP or database dependency."""

from __future__ import annotations

from typing import Any

from app.services.question_types import get_question_type_handler, validate_question
from app.services.storage_adapters import (
    DomainError,
    decimal_to_canonical,
    normalize_number,
    normalize_text,
    parse_decimal128,
)


# A descriptive alias for callers producing normalized idempotency payloads.
canonical_decimal = decimal_to_canonical


def normalize_answer(question: dict[str, Any], value: Any) -> Any:
    """Return a plain JSON answer or None, enforcing all reached constraints.

    In particular, required=False does not disable positive text/multiple lower
    bounds.  The number type accepts strings, never Python/JSON binary floats.
    """
    normalized_question = validate_question(question)
    handler = get_question_type_handler(normalized_question["type"])
    return handler.normalize_answer(normalized_question, value)


__all__ = [
    "DomainError", "normalize_answer", "normalize_number", "canonical_decimal",
    "decimal_to_canonical", "normalize_text", "parse_decimal128",
]

"""Small storage boundaries shared by the pure questionnaire domain.

API values remain JSON values.  Decimal128 objects are introduced only when an
already validated answer is prepared for MongoDB.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, DecimalException
import re
import unicodedata
from typing import Any, Mapping

from bson.decimal128 import Decimal128


MAX_NUMERIC_INPUT_LENGTH = 8192
MAX_INPUT_EXPONENT = 16384
MAX_BSON_INT64 = (1 << 63) - 1
# All list APIs permit at most 100 items per page. Keep MongoDB's skip
# argument within its signed 64-bit range even at that largest page size.
MAX_PAGE = MAX_BSON_INT64 // 100 + 1
_NUMBER_PATTERN = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE]([+-]?[0-9]+))?\Z",
    re.ASCII,
)


class DomainError(ValueError):
    """A safe, structured validation error for the HTTP boundary to translate."""

    def __init__(
        self,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else []
        self.status_code = status_code


def normalize_text(value: str) -> str:
    """Trim outer whitespace and count/compare NFC-normalized Unicode text."""
    return unicodedata.normalize("NFC", value.strip())


def validate_pagination(page: int, page_size: int) -> None:
    if (type(page) is not int or type(page_size) is not int
            or not 1 <= page <= MAX_PAGE or not 1 <= page_size <= 100):
        raise DomainError("INVALID_PAGE", "分页参数超出支持范围。")


def _number_error(message: str, question_id: str | None, field: str) -> DomainError:
    detail: dict[str, Any] = {"field": field, "message": message}
    if question_id is not None:
        detail["questionId"] = question_id
    return DomainError("INVALID_NUMBER", message, [detail])


def parse_decimal128(
    value: Any,
    *,
    question_id: str | None = None,
    field: str = "value",
) -> Decimal:
    """Accept only finite decimal strings that Decimal128 can store exactly.

    Decimal construction and Decimal128 conversion do not use Python's default
    28-digit arithmetic precision to normalize the input.  The lexical limits
    also bound the work needed by the browser's matching BigInt implementation.
    """
    if not isinstance(value, str):
        raise _number_error("数字必须以十进制字符串传输", question_id, field)
    if len(value) > MAX_NUMERIC_INPUT_LENGTH:
        raise _number_error("数字输入过长", question_id, field)
    raw = value.strip()
    match = _NUMBER_PATTERN.fullmatch(raw)
    if match is None:
        raise _number_error("请输入合法的有限十进制数", question_id, field)
    exponent = match.group(1)
    if exponent is not None:
        # Checking digit count before int() avoids arbitrarily large exponents.
        exponent_digits = exponent.lstrip("+-").lstrip("0") or "0"
        if len(exponent_digits) > 5 or int(exponent_digits) > MAX_INPUT_EXPONENT:
            raise _number_error("数字指数超出支持范围", question_id, field)
    try:
        number = Decimal(raw)
        if not number.is_finite():
            raise _number_error("数字必须有限", question_id, field)
        stored = Decimal128(number).to_decimal()
        if stored != number:
            raise _number_error("数字无法被 Decimal128 精确保存", question_id, field)
    except (DecimalException, ValueError, OverflowError) as exc:
        if isinstance(exc, DomainError):
            raise
        raise _number_error("数字超出 Decimal128 的精确表示范围", question_id, field) from exc
    return number


def decimal_to_canonical(value: Decimal | Decimal128) -> str:
    """Canonical plain decimal notation without arithmetic or context rounding."""
    number = value.to_decimal() if isinstance(value, Decimal128) else value
    if not isinstance(number, Decimal) or not number.is_finite():
        raise DomainError("INVALID_NUMBER", "无法规范化非有限数字")
    sign, digits, exponent = number.as_tuple()
    coefficient = "".join(str(digit) for digit in digits).lstrip("0")
    if not coefficient:
        return "0"
    trailing = len(coefficient) - len(coefficient.rstrip("0"))
    if trailing:
        coefficient = coefficient[:-trailing]
        exponent += trailing
    if exponent >= 0:
        result = coefficient + "0" * exponent
    else:
        point = len(coefficient) + exponent
        if point > 0:
            result = coefficient[:point] + "." + coefficient[point:]
        else:
            result = "0." + "0" * (-point) + coefficient
    return "-" + result if sign else result


def normalize_number(value: Any, *, question_id: str | None = None, field: str = "value") -> str:
    return decimal_to_canonical(parse_decimal128(value, question_id=question_id, field=field))


def to_storage_answer(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a normalized answer, changing only number values to BSON Decimal128."""
    result = deepcopy(dict(answer))
    if result.get("type") == "number":
        result["value"] = Decimal128(
            parse_decimal128(result["value"], question_id=result.get("questionId"))
        )
    return result


def from_storage_answer(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Project a stored answer back to JSON without introducing binary floats."""
    result = deepcopy(dict(answer))
    if result.get("type") == "number":
        value = result.get("value")
        if isinstance(value, (Decimal, Decimal128)):
            result["value"] = decimal_to_canonical(value)
        else:
            result["value"] = normalize_number(value, question_id=result.get("questionId"))
    return result


def with_storage_defaults(
    document: Mapping[str, Any], defaults: Mapping[str, Any]
) -> dict[str, Any]:
    """Read missing optional legacy fields without mutating or rewriting BSON.

    Explicit nulls are preserved.  A migration can separately persist the same
    agreed defaults; request models should not be used to reinterpret old BSON.
    """
    result = deepcopy(dict(document))
    for key, value in defaults.items():
        if key not in result:
            result[key] = deepcopy(value)
    return result


SURVEY_OPTIONAL_DEFAULTS = {
    "description": "",
    "allowAnonymous": False,
    "allowMultipleSubmissions": False,
    "closesAt": None,
}


def from_storage_survey(document: Mapping[str, Any]) -> dict[str, Any]:
    """Apply known optional-field defaults on real reads, without rewriting BSON.

    Future fields need an explicit agreed default here or a versioned migration;
    this does not guess how unknown future business fields should behave.
    """
    return with_storage_defaults(document, SURVEY_OPTIONAL_DEFAULTS)

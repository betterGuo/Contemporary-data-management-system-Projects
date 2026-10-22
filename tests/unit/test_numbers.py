from decimal import Decimal, localcontext

from bson.decimal128 import Decimal128
import pytest

from app.services.answer_validator import DomainError, normalize_answer, normalize_number
from app.services.question_types import validate_question
from app.services.storage_adapters import (
    MAX_NUMERIC_INPUT_LENGTH,
    decimal_to_canonical,
    from_storage_answer,
    to_storage_answer,
)


def numeric(validation=None, required=False):
    return {"id": "number", "type": "number", "title": "数字", "required": required,
            "validation": validation or {}}


@pytest.mark.case("T33", "T34", "T35", "T36", "T88")
@pytest.mark.parametrize(
    "value,expected",
    [
        ("18", "18"), ("18.0", "18"), ("+18.000", "18"),
        ("-0", "0"), ("-0.000e+100", "0"),
        ("1e3", "1000"), ("1e-7", "0.0000001"),
        (".5", "0.5"), ("-12.500", "-12.5"),
        (" 18 ", "18"), ("0018", "18"),
        ("9007199254740992", "9007199254740992"),
        ("9007199254740993", "9007199254740993"),
        ("1234567890123456789012345678901234", "1234567890123456789012345678901234"),
    ],
)
def test_exact_number_canonicalization(value, expected):
    assert normalize_number(value) == expected
    assert normalize_answer(numeric(), value) == expected


@pytest.mark.case("T35", "T36", "T88")
@pytest.mark.parametrize(
    "value",
    [
        True, False, 18, 18.0, Decimal("18"), None,
        "NaN", "Infinity", "-Infinity", "sNaN", "", " ", "abc", ".", "1e", "1e--3",
        "1_000", "０", "1,000", "12345678901234567890123456789012345",
        "1e6145", "1e-6177", "1e99999999999999999999999999999999999999999",
    ],
)
def test_invalid_or_inexact_numbers_rejected_without_binary_float_coercion(value):
    with pytest.raises(DomainError) as error:
        normalize_number(value)
    assert error.value.code == "INVALID_NUMBER"


@pytest.mark.case("T88")
def test_decimal128_extremes_and_subnormal_are_preserved_exactly():
    for text in ("1e6144", "9.999999999999999999999999999999999e6144", "1e-6176"):
        canonical = normalize_number(text)
        assert Decimal(canonical) == Decimal(text)
        assert Decimal128(Decimal(canonical)).to_decimal() == Decimal(text)
    assert len(normalize_number("1e-6176")) == 6178


@pytest.mark.case("T88")
def test_input_length_and_exponent_are_bounded_before_expansion():
    with pytest.raises(DomainError):
        normalize_number("0" * (MAX_NUMERIC_INPUT_LENGTH + 1))
    with pytest.raises(DomainError):
        normalize_number("1e16385")
    # Leading zeroes must not make int() hit Python's decimal digit guard.
    assert normalize_number("1e" + "0" * 5000 + "1") == "10"


@pytest.mark.case("T33", "T88")
def test_normalization_is_independent_of_default_decimal_precision():
    text = "1234567890123456789012345678901234"
    with localcontext() as context:
        context.prec = 2
        assert normalize_number(text) == text
        assert decimal_to_canonical(Decimal(text + ".0000")) == text
        assert normalize_answer(numeric({"integerOnly": True}), text + ".0") == text


@pytest.mark.case("T32", "T33")
@pytest.mark.parametrize("value,expected", [("0", "0"), ("120", "120"), ("18.0", "18"), ("-0", "0")])
def test_age_integer_bounds_include_endpoints(value, expected):
    assert normalize_answer(numeric({"minValue": "0", "maxValue": "120", "integerOnly": True}), value) == expected


@pytest.mark.case("T32", "T33")
@pytest.mark.parametrize("value", ["-1", "121", "18.5"])
def test_age_integer_bounds_reject_outside_values(value):
    with pytest.raises(DomainError):
        normalize_answer(numeric({"minValue": "0", "maxValue": "120", "integerOnly": True}), value)


@pytest.mark.case("T34", "T85")
def test_one_sided_bounds_and_unrestricted_fractional_answers():
    assert normalize_answer(numeric({"minValue": "-1.5"}), "-1.5") == "-1.5"
    assert normalize_answer(numeric({"maxValue": "-1.5"}), "-2") == "-2"
    assert normalize_answer(numeric(), "0.0000001") == "0.0000001"
    with pytest.raises(DomainError):
        normalize_answer(numeric({"minValue": "0"}), "-0.0000001")
    with pytest.raises(DomainError):
        normalize_answer(numeric({"maxValue": "0"}), "0.0000001")


@pytest.mark.case("T31", "T32", "T85")
def test_numeric_minimum_does_not_turn_optional_number_into_required_text():
    assert normalize_answer(numeric({"minValue": "10"}), "") is None
    assert normalize_answer(numeric({"minValue": "10"}), None) is None
    assert normalize_answer(numeric(), "0") == "0"
    with pytest.raises(DomainError):
        normalize_answer(numeric(required=True), " ")


@pytest.mark.case("T23", "T85", "T88")
def test_numeric_definition_bounds_are_also_canonical_and_exact():
    q = validate_question(numeric({"minValue": "18.0", "maxValue": "2e1", "integerOnly": True}))
    assert q["validation"] == {"minValue": "18", "maxValue": "20", "integerOnly": True}
    with pytest.raises(DomainError):
        validate_question(numeric({"maxValue": "NaN"}))


@pytest.mark.case("T36", "T88")
def test_storage_boundary_uses_decimal128_and_never_changes_json_input():
    original = {"questionId": "number", "type": "number", "value": "9007199254740993"}
    stored = to_storage_answer(original)
    assert isinstance(stored["value"], Decimal128)
    assert stored["value"].to_decimal() == Decimal("9007199254740993")
    assert original["value"] == "9007199254740993"
    assert from_storage_answer(stored) == original

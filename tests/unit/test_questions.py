from copy import deepcopy

import pytest

from app.services.answer_validator import DomainError, normalize_answer
from app.services.question_types import validate_definition, validate_question
from app.services.storage_adapters import with_storage_defaults


def question(kind="single", *, qid="q1", validation=None, required=False, **overrides):
    result = {
        "id": qid, "type": kind, "title": "题目", "required": required,
        "options": [{"id": item, "label": item.upper()} for item in ("a", "b", "c")]
        if kind in ("single", "multiple") else [],
        "validation": validation or {}, "jumpRules": [],
    }
    result.update(overrides)
    return result


@pytest.mark.case("T19", "T85")
@pytest.mark.parametrize("kind", ["single", "multiple", "text", "number"])
def test_question_definitions_have_explicit_defaults_and_do_not_mutate(kind):
    original = question(kind)
    snapshot = deepcopy(original)
    normalized = validate_question(original)
    assert normalized["type"] == kind
    assert normalized["required"] is False
    assert normalized["jumpRules"] == []
    assert original == snapshot
    if kind == "multiple":
        assert normalized["validation"] == {"minSelections": 0, "maxSelections": 3}
    elif kind == "text":
        assert normalized["validation"] == {"minLength": 0, "maxLength": 2000}
    elif kind == "number":
        assert normalized["validation"] == {"minValue": None, "maxValue": None, "integerOnly": False}


@pytest.mark.case("T19", "T24")
def test_single_option_is_valid_and_required_single_requires_selection():
    q = question(options=[{"id": "a", "label": "唯一选项"}], required=True)
    assert normalize_answer(q, "a") == "a"
    for value in (None, "", "unknown", ["a"], False):
        with pytest.raises(DomainError):
            normalize_answer(q, value)


@pytest.mark.case("T20")
def test_duplicate_question_ids_and_duplicate_option_ids_are_rejected():
    with pytest.raises(DomainError, match="题目 ID"):
        validate_definition([question(), question()])
    with pytest.raises(DomainError, match="选项 ID"):
        validate_question(question(options=[{"id": "a", "label": "甲"}, {"id": "a", "label": "乙"}]))


@pytest.mark.case("T23")
@pytest.mark.parametrize(
    "q",
    [
        question("multiple", validation={"minSelections": 3, "maxSelections": 2}),
        question("multiple", validation={"maxSelections": 4}),
        question("multiple", required=True, validation={"maxSelections": 0}),
        question("text", validation={"minLength": -1}),
        question("text", validation={"minLength": 3, "maxLength": 2}),
        question("text", validation={"maxLength": 2001}),
        question("text", required=True, validation={"maxLength": 0}),
        question("number", validation={"minValue": "2", "maxValue": "1"}),
        question("number", validation={"minValue": "0.1", "maxValue": "0.9", "integerOnly": True}),
        question("number", validation={"integerOnly": 1}),
        question("multiple", validation={"minSelections": True}),
        question("single", validation={"minLength": 1}),
        question("text", options=[{"id": "a", "label": "无效"}]),
        question("unknown"),
        question(required="false"),
        question(id="END"),
    ],
)
def test_invalid_definition_constraints(q):
    with pytest.raises(DomainError) as error:
        validate_question(q)
    assert error.value.status_code == 422


@pytest.mark.case("T25", "T26", "T27", "T37", "T85")
@pytest.mark.parametrize(
    "validation,value,expected",
    [
        ({"minSelections": 2}, ["b", "a"], ["a", "b"]),
        ({"maxSelections": 1}, ["a"], ["a"]),
        ({"minSelections": 2, "maxSelections": 2}, ["c", "a"], ["a", "c"]),
        ({"maxSelections": 2}, [], None),
        ({}, None, None),
    ],
)
def test_independent_and_exact_multiple_bounds(validation, value, expected):
    assert normalize_answer(question("multiple", validation=validation), value) == expected


@pytest.mark.case("T25", "T26", "T27", "T28", "T37")
@pytest.mark.parametrize(
    "validation,value",
    [
        ({"minSelections": 2}, None),
        ({"minSelections": 2}, []),
        ({"minSelections": 2}, ["a"]),
        ({"maxSelections": 1}, ["a", "b"]),
        ({"minSelections": 2, "maxSelections": 2}, ["a", "b", "c"]),
        ({}, ["a", "a"]),
        ({}, ["a", "unknown"]),
        ({}, "a"),
        ({}, [True]),
    ],
)
def test_multiple_limits_also_apply_when_required_is_false(validation, value):
    with pytest.raises(DomainError):
        normalize_answer(question("multiple", validation=validation, required=False), value)


@pytest.mark.case("T29", "T30", "T31", "T85")
@pytest.mark.parametrize(
    "validation,value,expected",
    [
        ({"minLength": 2}, "甲乙", "甲乙"),
        ({"maxLength": 2}, "  甲乙  ", "甲乙"),
        ({"minLength": 1, "maxLength": 1}, " e\u0301 ", "é"),
        ({"minLength": 3, "maxLength": 3}, "👩\u200d💻", "👩\u200d💻"),
        ({}, "  ", None),
        ({}, None, None),
    ],
)
def test_text_nfc_trimming_and_codepoint_boundaries(validation, value, expected):
    assert normalize_answer(question("text", validation=validation), value) == expected


@pytest.mark.case("T29", "T31")
@pytest.mark.parametrize("value", [None, "", "  ", "甲"])
def test_positive_text_minimum_cannot_be_disabled_by_required_false(value):
    with pytest.raises(DomainError):
        normalize_answer(question("text", validation={"minLength": 2}, required=False), value)


@pytest.mark.case("T31")
def test_required_text_rejects_blank_and_text_rejects_wrong_types():
    with pytest.raises(DomainError):
        normalize_answer(question("text", required=True), "  ")
    with pytest.raises(DomainError):
        normalize_answer(question("text"), 0)


@pytest.mark.case("T12", "T19")
def test_empty_draft_and_empty_published_definition_have_different_rules():
    assert validate_definition([]) == []
    with pytest.raises(DomainError):
        validate_definition([], publishing=True)


@pytest.mark.case("T23")
def test_resource_limits_are_explicit():
    with pytest.raises(DomainError):
        validate_definition([question(qid=f"q{i}") for i in range(101)])
    with pytest.raises(DomainError):
        validate_question(question(options=[{"id": str(i), "label": str(i)} for i in range(21)]))


def test_storage_defaults_are_read_only_and_preserve_explicit_nulls():
    legacy = {"title": "旧问卷", "description": None}
    result = with_storage_defaults(legacy, {"description": "", "schemaVersion": 1, "newOptional": []})
    assert result == {"title": "旧问卷", "description": None, "schemaVersion": 1, "newOptional": []}
    result["newOptional"].append("changed")
    assert legacy == {"title": "旧问卷", "description": None}


def test_domain_error_exposes_safe_http_contract():
    error = DomainError("CONFLICT", "冲突", [{"field": "revision"}], status_code=409)
    assert str(error) == error.message == "冲突"
    assert error.code == "CONFLICT" and error.status_code == 409
    assert error.details == [{"field": "revision"}]

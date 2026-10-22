from copy import deepcopy
from decimal import Decimal

import pytest

from app.services.answer_validator import DomainError
from app.services.jump_engine import evaluate_path, validate_answers_path
from app.services.question_types import validate_definition
from app.services.rule_operators import RULE_OPERATORS, evaluate_rule, register_rule_operator


def q(qid, kind="single", *, required=False, rules=None, validation=None):
    return {"id": qid, "type": kind, "title": qid, "required": required,
            "options": [{"id": item, "label": item} for item in ("a", "b", "c")]
            if kind in ("single", "multiple") else [],
            "validation": validation or {}, "jumpRules": rules or []}


def rule(operator, value, target="END", rid="r1"):
    return {"id": rid, "operator": operator, "value": value, "targetQuestionId": target}


def answers(**values):
    return [{"questionId": question_id, "value": value} for question_id, value in values.items()]


@pytest.mark.case("T39", "T46", "T48")
def test_single_branch_skips_required_question_and_reaches_explicit_end():
    questions = [q("q1", required=True, rules=[rule("eq", "b", "q3")]),
                 q("q2", "text", required=True), q("q3", required=True)]
    result = validate_answers_path(questions, answers(q1="b", q3="a"))
    assert result["visitedQuestionIds"] == ["q1", "q3"]
    assert result["answers"] == [{"questionId": "q1", "type": "single", "value": "b"},
                                  {"questionId": "q3", "type": "single", "value": "a"}]


@pytest.mark.case("T40", "T41", "T42")
@pytest.mark.parametrize(
    "operator,condition,value,expected",
    [("containsAny", ["a", "b"], ["c", "b"], True),
     ("containsAny", ["a", "b"], ["c"], False),
     ("containsAll", ["b", "a"], ["a", "b", "c"], True),
     ("containsAll", ["b", "a"], ["a", "c"], False),
     ("equalsSet", ["b", "a"], ["a", "b"], True),
     ("equalsSet", ["b", "a"], ["a", "b", "c"], False)],
)
def test_multiple_rule_set_semantics(operator, condition, value, expected):
    assert evaluate_rule(q("q1", "multiple"), rule(operator, condition), value) is expected


@pytest.mark.case("T43", "T88")
@pytest.mark.parametrize(
    "operator,condition,value,expected",
    [("eq", "18.0", "18", True), ("lt", "18", "18", False),
     ("lte", "18", "18", True), ("gt", "18", "19", True),
     ("gte", "18", "18", True), ("between", ["-1.5", "2.5"], "-1.5", True),
     ("between", ["-1.5", "2.5"], "2.5", True),
     ("between", ["-1.5", "2.5"], "2.5000001", False),
     ("eq", "9007199254740992", "9007199254740993", False),
     ("gt", "9007199254740992", "9007199254740993", True),
     ("eq", "1e-7", "0.0000001", True)],
)
def test_decimal_comparisons_and_inclusive_between(operator, condition, value, expected):
    assert evaluate_rule(q("q1", "number"), rule(operator, condition), value) is expected


@pytest.mark.case("T44")
def test_first_matching_rule_wins_over_later_matching_rule():
    questions = [q("q1", "number", rules=[rule("gte", "18", "q3", "first"),
                                            rule("gte", "10", "q2", "second")]),
                 q("q2", "text", required=True), q("q3")]
    assert evaluate_path(questions, answers(q1="20"))["visitedQuestionIds"] == ["q1", "q3"]


@pytest.mark.case("T45", "T46")
def test_default_next_question_and_optional_empty_do_not_trigger_rules():
    questions = [q("q1", rules=[rule("eq", "b", "END")]), q("q2", "number")]
    result = evaluate_path(questions, [])
    assert result == {"visitedQuestionIds": ["q1", "q2"], "answers": []}
    assert evaluate_path(questions, answers(q1="b"))["visitedQuestionIds"] == ["q1"]


@pytest.mark.case("T20", "T21", "T22", "T47", "T52")
@pytest.mark.parametrize("target", ["q1", "unknown", "other_survey_q1"])
def test_invalid_jump_targets_are_rejected_at_save(target):
    with pytest.raises(DomainError):
        validate_definition([q("q1", rules=[rule("eq", "a", target)]), q("q2")])


@pytest.mark.case("T21", "T22", "T47", "T52")
def test_reordering_or_deleting_a_referenced_question_cannot_damage_definition():
    questions = [q("q1", rules=[rule("eq", "a", "q2")]), q("q2")]
    assert len(validate_definition(questions)) == 2
    with pytest.raises(DomainError):
        validate_definition(list(reversed(questions)))
    with pytest.raises(DomainError):
        validate_definition(questions[:1])
    questions[1]["jumpRules"] = [rule("eq", "a", "q1")]
    with pytest.raises(DomainError):
        evaluate_path(questions, answers(q1="a", q2="a"))


@pytest.mark.case("T20", "T21", "T23", "T47")
@pytest.mark.parametrize(
    "kind,rules",
    [("single", [rule("eq", "unknown")]),
     ("single", [rule("eq", "a"), rule("eq", "b")]),
     ("single", [rule("containsAll", ["a"])]),
     ("multiple", [rule("containsAny", [])]),
     ("multiple", [rule("containsAll", ["a", "a"])]),
     ("multiple", [rule("equalsSet", ["unknown"])]),
     ("number", [rule("between", ["2", "1"])]),
     ("number", [rule("between", {"min": "1", "max": "2"})]),
     ("number", [rule("eq", True)]),
     ("text", [rule("eq", "text")])],
)
def test_invalid_or_duplicate_rules(kind, rules):
    with pytest.raises(DomainError):
        validate_definition([q("q1", kind, rules=rules)])


@pytest.mark.case("T49", "T50")
def test_upstream_change_requires_client_to_remove_old_branch_answers():
    questions = [q("q1", rules=[rule("eq", "b", "q3")]), q("q2", "text", required=True), q("q3")]
    assert evaluate_path(questions, answers(q1="a", q2="原分支", q3="a"))["visitedQuestionIds"] == ["q1", "q2", "q3"]
    with pytest.raises(DomainError) as error:
        evaluate_path(questions, answers(q1="b", q2="原分支", q3="a"))
    assert error.value.code == "PATH_ANSWER_NOT_REACHABLE"
    assert evaluate_path(questions, answers(q1="b", q3="a"))["visitedQuestionIds"] == ["q1", "q3"]


@pytest.mark.case("T50", "T51")
@pytest.mark.parametrize(
    "payload,code",
    [([{"questionId": "unknown", "value": "a"}], "UNKNOWN_QUESTION"),
     ([{"questionId": "q1", "value": "a"}, {"questionId": "q1", "value": "b"}], "DUPLICATE_QUESTION"),
     ([{"questionId": "q1", "type": "single", "value": "a"}], "INVALID_ANSWER"),
     ([], "INVALID_ANSWER")],
)
def test_complete_replay_rejects_unknown_duplicate_fields_or_missing_required(payload, code):
    with pytest.raises(DomainError) as error:
        validate_answers_path([q("q1", required=True)], payload)
    assert error.value.code == code


@pytest.mark.case("T50")
def test_even_an_empty_answer_outside_actual_path_is_rejected():
    questions = [q("q1", rules=[rule("eq", "a")]), q("q2", "text")]
    with pytest.raises(DomainError, match="路径以外"):
        evaluate_path(questions, answers(q1="a", q2=None))


@pytest.mark.case("E01", "T39", "T43")
def test_draft_configuration_changes_path_without_changing_engine_or_old_definition():
    first = [q("q1", "number", rules=[rule("gte", "18", "END")]), q("q2", "text")]
    published_snapshot = deepcopy(first)
    changed = deepcopy(first)
    changed[0]["jumpRules"][0]["value"] = "21"
    assert evaluate_path(first, answers(q1="20"))["visitedQuestionIds"] == ["q1"]
    assert evaluate_path(changed, answers(q1="20"))["visitedQuestionIds"] == ["q1", "q2"]
    assert first == published_snapshot


@pytest.mark.case("E02")
def test_registration_can_add_operator_without_changing_traversal(monkeypatch):
    def condition(question, value):
        if value is not None:
            raise DomainError("INVALID_JUMP_RULE", "演示偶数规则不接收条件参数")
        return None

    key = ("number", "demoEven")
    monkeypatch.setitem(RULE_OPERATORS, key, None)
    register_rule_operator("number", "demoEven", condition,
                           lambda answer, unused: Decimal(answer) % 2 == 0, replace=True)
    questions = [q("q1", "number", rules=[rule("demoEven", None, "END")]), q("q2", "text")]
    assert evaluate_path(questions, answers(q1="2"))["visitedQuestionIds"] == ["q1"]
    assert evaluate_path(questions, answers(q1="3"))["visitedQuestionIds"] == ["q1", "q2"]
    with pytest.raises(DomainError):
        validate_definition([q("q1", "number", rules=[rule("demoEven", "unexpected")])])


@pytest.mark.case("T43")
def test_registry_rejects_accidental_override_of_existing_operator():
    with pytest.raises(ValueError):
        register_rule_operator("number", "eq", lambda question, value: value, lambda a, b: True)

"""Data-driven jump operators, independent of traversal and the database."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from app.services.storage_adapters import DomainError, normalize_number


@dataclass(frozen=True)
class RuleOperator:
    normalize_condition: Callable[[dict[str, Any], Any], Any]
    matches: Callable[[Any, Any], bool]


RULE_OPERATORS: dict[tuple[str, str], RuleOperator] = {}


def register_rule_operator(
    question_type: str,
    operator: str,
    condition_validator: Callable[[dict[str, Any], Any], Any],
    matcher: Callable[[Any, Any], bool],
    *,
    replace: bool = False,
) -> None:
    key = (question_type, operator)
    if key in RULE_OPERATORS and not replace:
        raise ValueError(f"运算符已经注册: {question_type}/{operator}")
    if not question_type or not operator or not callable(condition_validator) or not callable(matcher):
        raise ValueError("运算符注册参数无效")
    RULE_OPERATORS[key] = RuleOperator(condition_validator, matcher)


def _fail(question: dict[str, Any], message: str, field: str = "jumpRules") -> None:
    raise DomainError(
        "INVALID_JUMP_RULE", message,
        [{"questionId": question.get("id"), "field": field, "message": message}],
    )


def get_rule_operator(question_type: str, operator: str) -> RuleOperator:
    try:
        return RULE_OPERATORS[(question_type, operator)]
    except (KeyError, TypeError) as exc:
        raise DomainError("UNKNOWN_RULE_OPERATOR", "该题型不支持此跳转运算符") from exc


def _single_condition(question: dict[str, Any], value: Any) -> str:
    option_ids = {option["id"] for option in question.get("options", [])}
    if not isinstance(value, str) or value not in option_ids:
        _fail(question, "单选条件必须引用本题的有效选项")
    return value


def _multiple_condition(question: dict[str, Any], value: Any) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        _fail(question, "多选条件必须是非空选项 ID 数组")
    if len(set(value)) != len(value):
        _fail(question, "多选条件不能含重复选项")
    option_ids = {option["id"] for option in question.get("options", [])}
    if not set(value) <= option_ids:
        _fail(question, "多选条件引用了其他题或不存在的选项")
    return sorted(value)


def _number_condition(question: dict[str, Any], value: Any) -> str:
    return normalize_number(value, question_id=question.get("id"), field="jumpRules.value")


def _between_condition(question: dict[str, Any], value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != 2:
        _fail(question, "between 条件必须是含两个十进制字符串的数组")
    result = [_number_condition(question, item) for item in value]
    if Decimal(result[0]) > Decimal(result[1]):
        _fail(question, "between 下界不能大于上界")
    return result


def normalize_rule(question: dict[str, Any], rule: Any) -> dict[str, Any]:
    if not isinstance(rule, dict):
        _fail(question, "跳转规则必须是对象")
    extra = set(rule) - {"id", "operator", "value", "targetQuestionId"}
    if extra:
        _fail(question, "跳转规则包含未知字段")
    rule_id = rule.get("id")
    target = rule.get("targetQuestionId")
    operator = rule.get("operator")
    if not isinstance(rule_id, str) or not rule_id or len(rule_id) > 128:
        _fail(question, "跳转规则 ID 必须是非空字符串")
    if not isinstance(target, str) or not target or len(target) > 128:
        _fail(question, "跳转目标必须是题目 ID 或 END")
    if not isinstance(operator, str):
        _fail(question, "跳转运算符必须是字符串")
    try:
        handler = get_rule_operator(question["type"], operator)
    except DomainError as exc:
        _fail(question, exc.message, "jumpRules.operator")
    return {
        "id": rule_id,
        "operator": operator,
        "value": handler.normalize_condition(question, rule.get("value")),
        "targetQuestionId": target,
    }


def evaluate_rule(question: dict[str, Any], rule: dict[str, Any], answer: Any) -> bool:
    if answer is None:
        return False
    normalized = normalize_rule(question, rule)
    handler = get_rule_operator(question["type"], normalized["operator"])
    return bool(handler.matches(answer, normalized["value"]))


register_rule_operator("single", "eq", _single_condition, lambda answer, value: answer == value)
register_rule_operator("multiple", "containsAny", _multiple_condition,
                       lambda answer, value: bool(set(answer) & set(value)))
register_rule_operator("multiple", "containsAll", _multiple_condition,
                       lambda answer, value: set(value) <= set(answer))
register_rule_operator("multiple", "equalsSet", _multiple_condition,
                       lambda answer, value: set(answer) == set(value))

_NUMBER_COMPARISONS = {
    "eq": lambda a, b: a == b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
}
for _operator, _comparison in _NUMBER_COMPARISONS.items():
    register_rule_operator(
        "number", _operator, _number_condition,
        lambda answer, value, compare=_comparison: compare(Decimal(answer), Decimal(value)),
    )
register_rule_operator(
    "number", "between", _between_condition,
    lambda answer, value: Decimal(value[0]) <= Decimal(answer) <= Decimal(value[1]),
)

"""The four question handlers and validation of editable definitions."""

from __future__ import annotations

from copy import deepcopy
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Callable

from app.services.rule_operators import normalize_rule
from app.services.storage_adapters import DomainError, normalize_number, normalize_text, parse_decimal128


MAX_QUESTIONS = 100
MAX_OPTIONS = 20
MAX_TEXT_LENGTH = 2000
MAX_QUESTION_TITLE_LENGTH = 2000
MAX_RULES_PER_QUESTION = 100


@dataclass(frozen=True)
class QuestionTypeHandler:
    validate_definition: Callable[[dict[str, Any]], dict[str, Any]]
    normalize_answer: Callable[[dict[str, Any], Any], Any]


QUESTION_TYPES: dict[str, QuestionTypeHandler] = {}


def register_question_type(
    type_name: str,
    definition_validator: Callable[[dict[str, Any]], dict[str, Any]],
    answer_normalizer: Callable[[dict[str, Any], Any], Any],
    *,
    replace: bool = False,
) -> None:
    if type_name in QUESTION_TYPES and not replace:
        raise ValueError(f"题型已经注册: {type_name}")
    if not type_name or not callable(definition_validator) or not callable(answer_normalizer):
        raise ValueError("题型注册参数无效")
    QUESTION_TYPES[type_name] = QuestionTypeHandler(definition_validator, answer_normalizer)


def get_question_type_handler(type_name: str) -> QuestionTypeHandler:
    try:
        return QUESTION_TYPES[type_name]
    except (KeyError, TypeError) as exc:
        raise DomainError("UNKNOWN_QUESTION_TYPE", "不支持的题型") from exc


def _fail(question: dict[str, Any], message: str, field: str, *, answer: bool = False) -> None:
    raise DomainError(
        "INVALID_ANSWER" if answer else "INVALID_DEFINITION", message,
        [{"questionId": question.get("id"), "field": field, "message": message}],
    )


def _validation(question: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    value = question.get("validation", {})
    if not isinstance(value, dict) or set(value) - allowed:
        _fail(question, "校验配置包含未知字段或类型错误", "validation")
    return value


def _integer_limit(question: dict[str, Any], raw: Any, default: int, field: str) -> int:
    if raw is None:
        return default
    if type(raw) is not int or raw < 0:
        _fail(question, "数量和字数限制必须是非负整数", field)
    return raw


def _choice_definition(question: dict[str, Any]) -> dict[str, Any]:
    options = question.get("options", [])
    if not isinstance(options, list) or not 1 <= len(options) <= MAX_OPTIONS:
        _fail(question, f"选择题需有 1 至 {MAX_OPTIONS} 个选项", "options")
    normalized_options = []
    seen: set[str] = set()
    for option in options:
        if not isinstance(option, dict) or set(option) - {"id", "label"}:
            _fail(question, "选项必须只包含 id 和 label", "options")
        option_id = option.get("id")
        label = option.get("label")
        if not isinstance(option_id, str) or not option_id or len(option_id) > 128:
            _fail(question, "选项 ID 必须是非空字符串", "options.id")
        if option_id in seen:
            _fail(question, "同一题内的选项 ID 不能重复", "options.id")
        if not isinstance(label, str) or not normalize_text(label):
            _fail(question, "选项文字不能为空", "options.label")
        label = normalize_text(label)
        if len(label) > MAX_TEXT_LENGTH:
            _fail(question, "选项文字过长", "options.label")
        seen.add(option_id)
        normalized_options.append({"id": option_id, "label": label})
    question["options"] = normalized_options
    return question


def _single_definition(question: dict[str, Any]) -> dict[str, Any]:
    _choice_definition(question)
    _validation(question, set())
    question["validation"] = {}
    return question


def _multiple_definition(question: dict[str, Any]) -> dict[str, Any]:
    _choice_definition(question)
    value = _validation(question, {"minSelections", "maxSelections"})
    minimum = _integer_limit(question, value.get("minSelections"), 0, "validation.minSelections")
    maximum = _integer_limit(
        question, value.get("maxSelections"), len(question["options"]), "validation.maxSelections"
    )
    effective_minimum = max(minimum, 1 if question["required"] else 0)
    if effective_minimum > maximum or maximum > len(question["options"]):
        _fail(question, "多选上下限、必答与选项数量不兼容", "validation")
    question["validation"] = {"minSelections": minimum, "maxSelections": maximum}
    return question


def _no_options(question: dict[str, Any]) -> None:
    if question.get("options", []) != []:
        _fail(question, "填空题不能配置选项", "options")
    question["options"] = []


def _text_definition(question: dict[str, Any]) -> dict[str, Any]:
    _no_options(question)
    value = _validation(question, {"minLength", "maxLength"})
    minimum = _integer_limit(question, value.get("minLength"), 0, "validation.minLength")
    maximum = _integer_limit(question, value.get("maxLength"), MAX_TEXT_LENGTH, "validation.maxLength")
    if max(minimum, 1 if question["required"] else 0) > maximum or maximum > MAX_TEXT_LENGTH:
        _fail(question, "文本上下限、必答与资源上限不兼容", "validation")
    question["validation"] = {"minLength": minimum, "maxLength": maximum}
    return question


def _number_definition(question: dict[str, Any]) -> dict[str, Any]:
    _no_options(question)
    value = _validation(question, {"minValue", "maxValue", "integerOnly"})
    integer_only = value.get("integerOnly", False)
    if type(integer_only) is not bool:
        _fail(question, "integerOnly 必须是布尔值", "validation.integerOnly")
    result: dict[str, Any] = {"minValue": None, "maxValue": None, "integerOnly": integer_only}
    for field in ("minValue", "maxValue"):
        if value.get(field) is not None:
            result[field] = normalize_number(
                value[field], question_id=question.get("id"), field=f"validation.{field}"
            )
    minimum = Decimal(result["minValue"]) if result["minValue"] is not None else None
    maximum = Decimal(result["maxValue"]) if result["maxValue"] is not None else None
    if minimum is not None and maximum is not None:
        if minimum > maximum:
            _fail(question, "数字最小值不能大于最大值", "validation")
        if integer_only and minimum.to_integral_value(rounding=ROUND_CEILING) > maximum.to_integral_value(rounding=ROUND_FLOOR):
            _fail(question, "数字范围内不存在可填写的整数", "validation")
    question["validation"] = result
    return question


def _single_answer(question: dict[str, Any], value: Any) -> str | None:
    if value is None or value == "":
        if question["required"]:
            _fail(question, "请选择一个选项", "value", answer=True)
        return None
    if not isinstance(value, str) or value not in {item["id"] for item in question["options"]}:
        _fail(question, "单选答案必须是本题的一个有效选项 ID", "value", answer=True)
    return value


def _multiple_answer(question: dict[str, Any], value: Any) -> list[str] | None:
    if value is None:
        value = []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail(question, "多选答案必须是选项 ID 数组", "value", answer=True)
    if len(set(value)) != len(value):
        _fail(question, "多选答案不能有重复选项", "value", answer=True)
    if not set(value) <= {item["id"] for item in question["options"]}:
        _fail(question, "多选答案包含未知选项", "value", answer=True)
    config = question["validation"]
    minimum = max(config["minSelections"], 1 if question["required"] else 0)
    if not minimum <= len(value) <= config["maxSelections"]:
        _fail(question, f"请选择 {minimum} 至 {config['maxSelections']} 个选项", "value", answer=True)
    return sorted(value) if value else None


def _text_answer(question: dict[str, Any], value: Any) -> str | None:
    if value is None:
        value = ""
    if not isinstance(value, str):
        _fail(question, "文本答案必须是字符串", "value", answer=True)
    normalized = normalize_text(value)
    config = question["validation"]
    minimum = max(config["minLength"], 1 if question["required"] else 0)
    if not minimum <= len(normalized) <= config["maxLength"]:
        _fail(question, f"请输入 {minimum} 至 {config['maxLength']} 个码点", "value", answer=True)
    return normalized or None


def _number_answer(question: dict[str, Any], value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if question["required"]:
            _fail(question, "请输入数字", "value", answer=True)
        return None
    number = parse_decimal128(value, question_id=question.get("id"))
    config = question["validation"]
    minimum = config["minValue"]
    maximum = config["maxValue"]
    if minimum is not None and number < Decimal(minimum):
        _fail(question, f"数字不能小于 {minimum}", "value", answer=True)
    if maximum is not None and number > Decimal(maximum):
        _fail(question, f"数字不能大于 {maximum}", "value", answer=True)
    if config["integerOnly"] and number != number.to_integral_value():
        _fail(question, "请输入整数", "value", answer=True)
    return normalize_number(value, question_id=question.get("id"))


def validate_question(question: Any) -> dict[str, Any]:
    if not isinstance(question, dict):
        raise DomainError("INVALID_DEFINITION", "题目定义必须是对象")
    result = deepcopy(question)
    allowed = {"id", "type", "title", "required", "options", "validation", "jumpRules"}
    if set(result) - allowed:
        _fail(result, "题目包含未知字段", "question")
    question_id = result.get("id")
    if (not isinstance(question_id, str) or not question_id or len(question_id) > 128
            or question_id in {"END", ".", ".."}
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in question_id)):
        # Empty/dot path segments and controls cannot be addressed reliably by
        # browsers/ASGI. Keep all other existing Unicode, slash and percent IDs.
        safe_question = {**result, "id": None}
        _fail(safe_question, "题目 ID 须为 1 至 128 字的字符串，不能是 END、.、.. 或含控制及非法字符", "id")
    title = result.get("title")
    if not isinstance(title, str) or not normalize_text(title):
        _fail(result, "题目标题不能为空", "title")
    result["title"] = normalize_text(title)
    if len(result["title"]) > MAX_QUESTION_TITLE_LENGTH:
        _fail(result, "题目标题过长", "title")
    required = result.get("required", False)
    if type(required) is not bool:
        _fail(result, "required 必须是布尔值", "required")
    result["required"] = required
    handler = get_question_type_handler(result.get("type"))
    result = handler.validate_definition(result)
    rules = result.get("jumpRules", [])
    if not isinstance(rules, list) or len(rules) > MAX_RULES_PER_QUESTION:
        _fail(result, "跳转规则必须是资源上限内的数组", "jumpRules")
    normalized_rules = [normalize_rule(result, rule) for rule in rules]
    if len({rule["id"] for rule in normalized_rules}) != len(normalized_rules):
        _fail(result, "同一题的规则 ID 不能重复", "jumpRules.id")
    result["jumpRules"] = normalized_rules
    return result


def validate_definition(questions: Any, publishing: bool = False) -> list[dict[str, Any]]:
    if not isinstance(questions, list) or len(questions) > MAX_QUESTIONS:
        raise DomainError("INVALID_DEFINITION", f"题目必须是最多 {MAX_QUESTIONS} 项的数组")
    if publishing and not questions:
        raise DomainError("INVALID_DEFINITION", "发布问卷时至少需要一道题")
    result = [validate_question(question) for question in questions]
    positions: dict[str, int] = {}
    for position, question in enumerate(result):
        if question["id"] in positions:
            _fail(question, "同卷题目 ID 不能重复", "id")
        positions[question["id"]] = position
    for position, question in enumerate(result):
        for rule in question["jumpRules"]:
            target = rule["targetQuestionId"]
            if target == "END":
                continue
            if target not in positions:
                _fail(question, "跳转目标不是本卷已有题目", "jumpRules.targetQuestionId")
            if positions[target] <= position:
                _fail(question, "跳转目标必须位于来源题之后", "jumpRules.targetQuestionId")
    return result


register_question_type("single", _single_definition, _single_answer)
register_question_type("multiple", _multiple_definition, _multiple_answer)
register_question_type("text", _text_definition, _text_answer)
register_question_type("number", _number_definition, _number_answer)

"""Forward-only, first-match path replay of a complete response."""

from __future__ import annotations

from typing import Any

from app.services.answer_validator import normalize_answer
from app.services.question_types import validate_definition
from app.services.rule_operators import evaluate_rule
from app.services.storage_adapters import DomainError


def _payload_answers(
    questions: list[dict[str, Any]], answers: Any
) -> dict[str, Any]:
    if not isinstance(answers, list):
        raise DomainError("INVALID_ANSWER", "answers 必须是数组")
    known = {question["id"] for question in questions}
    supplied: dict[str, Any] = {}
    for answer in answers:
        if not isinstance(answer, dict) or set(answer) - {"questionId", "value"}:
            raise DomainError("INVALID_ANSWER", "答案项只能包含 questionId 和 value")
        question_id = answer.get("questionId")
        if not isinstance(question_id, str) or question_id not in known:
            raise DomainError("UNKNOWN_QUESTION", "答案引用未知题目", [{"field": "questionId"}])
        if question_id in supplied:
            raise DomainError(
                "DUPLICATE_QUESTION", "同一题不能重复提交答案",
                [{"questionId": question_id, "field": "questionId"}],
            )
        supplied[question_id] = answer.get("value")
    return supplied


def validate_answers_path(questions: Any, answers: Any) -> dict[str, Any]:
    """Replay the server definition, rejecting unknown, duplicate and stale answers."""
    normalized_questions = validate_definition(questions, publishing=True)
    supplied = _payload_answers(normalized_questions, answers)
    positions = {question["id"]: position for position, question in enumerate(normalized_questions)}
    visited: list[str] = []
    visited_set: set[str] = set()
    normalized_answers: list[dict[str, Any]] = []
    current = normalized_questions[0]["id"]
    while current != "END":
        if current not in positions or current in visited_set or len(visited) >= len(normalized_questions):
            raise DomainError("INVALID_PATH", "问卷路径损坏或形成循环")
        position = positions[current]
        question = normalized_questions[position]
        visited.append(current)
        visited_set.add(current)
        value = normalize_answer(question, supplied.get(current))
        if value is not None:
            normalized_answers.append({"questionId": current, "type": question["type"], "value": value})
        target = normalized_questions[position + 1]["id"] if position + 1 < len(normalized_questions) else "END"
        if value is not None:
            for rule in question["jumpRules"]:
                if evaluate_rule(question, rule, value):
                    target = rule["targetQuestionId"]
                    break
        if target != "END" and (target not in positions or positions[target] <= position):
            raise DomainError("INVALID_PATH", "跳转目标必须位于来源题之后")
        current = target
    unreachable = set(supplied) - visited_set
    if unreachable:
        raise DomainError(
            "PATH_ANSWER_NOT_REACHABLE", "不能提交本次路径以外题目的答案",
            [{"questionId": question_id, "field": "value"} for question_id in sorted(unreachable)],
        )
    return {"visitedQuestionIds": visited, "answers": normalized_answers}


def evaluate_path(questions: Any, answers: Any) -> dict[str, Any]:
    """Strict pure preview of the same completed response replay used on submit."""
    return validate_answers_path(questions, answers)

from bson import BSON
from bson.decimal128 import Decimal128
from decimal import Decimal, localcontext

from app.services.definition_service import load_definition
from app.services.storage_adapters import DomainError, validate_pagination


def totals(db, survey_id, version, response_filter=None):
    match = response_filter if response_filter is not None else {"surveyId": survey_id, "surveyDefinitionVersion": version}
    result = list(db.responses.aggregate([
        {"$match": match},
        {"$group": {"_id": None, "count": {"$sum": 1}, "people": {"$addToSet": "$respondentKey"}}},
    ]))
    return (result[0]["count"], len(result[0]["people"])) if result else (0, 0)


def value_json(value):
    return str(value.to_decimal()) if isinstance(value, Decimal128) else value


def exact_numeric_average(db, survey, question, answer_count, response_filter=None):
    """Guard Decimal128 $avg against intermediate overflow and cancellation.

    Decimal128 finite inputs span exponents -6176 through an adjusted +6144.
    12400 + digits(count) is sufficient for an exact aligned sum of these
    inputs. Only the final division is rounded to 34 significant figures.
    This is streamed; answers are not copied to a separate persistent store.
    """
    if not answer_count:
        return None
    cursor = db.responses.aggregate([
        {"$match": response_filter if response_filter is not None else {"surveyId": survey["_id"], "surveyDefinitionVersion": survey["definitionVersion"]}},
        {"$unwind": "$answers"}, {"$match": {"answers.questionId": question["id"]}},
        {"$project": {"_id": 0, "value": "$answers.value"}},
    ])
    with localcontext() as ctx:
        ctx.prec = 12400 + len(str(answer_count))
        total = Decimal(0)
        seen = 0
        for row in cursor:
            value = row["value"]
            number = value.to_decimal() if isinstance(value, Decimal128) else Decimal(str(value))
            if not number.is_finite():
                raise DomainError("INVALID_STORED_NUMBER", "历史数字答案不是有限数。", [])
            total += number
            seen += 1
    if not seen:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        average = total / Decimal(seen)
    return str(average)


def _standard_statistics(db, survey, question, submission_count, page=1, page_size=20, response_filter=None):
    summary_group = {"_id": None, "answerCount": {"$sum": 1}, "people": {"$addToSet": "$respondentKey"}}
    if question["type"] == "number":
        summary_group["average"] = {"$avg": "$answers.value"}
    facets = {
        "summary": [{"$group": summary_group}],
        "values": [
            {"$sort": {"submittedAt": 1, "_id": 1}},
            {"$skip": (page-1)*page_size}, {"$limit": page_size},
            {"$project": {"_id": 0, "responseId": {"$toString": "$_id"}, "value": "$answers.value", "submittedAt": 1}},
        ],
    }
    if question["type"] in {"single", "multiple"}:
        facets["options"] = ([{"$unwind": "$answers.value"}] if question["type"] == "multiple" else []) + [
            {"$group": {"_id": "$answers.value", "count": {"$sum": 1}, "people": {"$addToSet": "$respondentKey"}}}
        ]
    result = list(db.responses.aggregate([
        {"$match": response_filter if response_filter is not None else {"surveyId": survey["_id"], "surveyDefinitionVersion": survey["definitionVersion"]}},
        {"$unwind": "$answers"}, {"$match": {"answers.questionId": question["id"]}},
        {"$facet": facets},
    ]))[0]
    summary = result["summary"][0] if result["summary"] else {"answerCount": 0, "people": []}
    stats = {"questionId": question["id"], "title": question["title"], "type": question["type"], "answerCount": summary["answerCount"], "respondentCount": len(summary["people"]), "unansweredCount": submission_count-summary["answerCount"], "totalValues": summary["answerCount"], "page": page, "pageSize": page_size, "average": value_json(summary.get("average")), "values": []}
    if question["type"] in {"single", "multiple"}:
        counts = {row["_id"]: row for row in result.get("options", [])}
        stats["options"] = [{"id": option["id"], "label": option["label"], "count": counts.get(option["id"], {}).get("count", 0), "respondentCount": len(counts.get(option["id"], {}).get("people", []))} for option in question["options"]]
    else:
        stats["values"] = [{**row, "value": value_json(row["value"]), "submittedAt": row["submittedAt"].isoformat()} for row in result["values"]]
        if question["type"] == "number":
            stats["average"] = exact_numeric_average(db, survey, question, summary["answerCount"], response_filter)
    return stats


STATISTICS_HANDLERS = {}


def register_statistics_handler(type_name, handler, *, replace=False):
    if type_name in STATISTICS_HANDLERS and not replace:
        raise ValueError("统计处理器已注册")
    if not callable(handler):
        raise ValueError("统计处理器必须可调用")
    STATISTICS_HANDLERS[type_name] = handler


for _type in ("single", "multiple", "text", "number"):
    register_statistics_handler(_type, _standard_statistics)


def question_statistics(db, survey, question, submission_count, page=1, page_size=20, response_filter=None):
    handler = STATISTICS_HANDLERS.get(question["type"])
    if handler is None:
        raise DomainError("UNKNOWN_STATISTICS_TYPE", "题型未注册统计处理器。", [])
    return handler(db, survey, question, submission_count, page, page_size, response_filter)


def statistics(db, survey, question_id=None, page=1, page_size=20):
    validate_pagination(page, page_size)
    definition = load_definition(db, survey["_id"], survey["definitionVersion"])
    # Standalone MongoDB has no multi-query snapshot transaction. Freeze the
    # membership once; successful response documents are immutable. A maximum
    # ObjectId alone would still admit an older id whose insert was delayed.
    response_filter = {"surveyId": survey["_id"], "surveyDefinitionVersion": survey["definitionVersion"]}
    response_ids = [row["_id"] for row in db.responses.find(response_filter, {"_id": 1})]
    response_filter["_id"] = {"$in": response_ids}
    # Leave room for the aggregate command below MongoDB's 16 MiB BSON limit.
    # A replica-set snapshot or batched reducer is the extension for large data.
    if len(BSON.encode(response_filter)) > 15 * 1024 * 1024:
        raise DomainError("STATISTICS_TOO_LARGE", "答卷量超出当前单次统计范围，请联系维护者分批统计。", [], status_code=503)
    count, people = totals(db, survey["_id"], survey["definitionVersion"], response_filter)
    if question_id is not None:
        question = next((q for q in definition["questions"] if q["id"] == question_id), None)
        if not question:
            raise DomainError("NOT_FOUND", "题目不存在。", [], status_code=404)
        return question_statistics(db, survey, question, count, page, page_size, response_filter)
    return {"surveyId": str(survey["_id"]), "title": definition["title"], "definitionVersion": survey["definitionVersion"], "submissionCount": count, "respondentCount": people, "questions": [question_statistics(db, survey, q, count, page, page_size, response_filter) for q in definition["questions"]]}

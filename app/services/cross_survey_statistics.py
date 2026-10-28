"""Exact-version summary statistics over authorized questionnaire instances."""
from decimal import Decimal, localcontext
import json

from bson import BSON, ObjectId
from bson.decimal128 import Decimal128

from app.services import statistics_scope
from app.services.storage_adapters import DomainError, decimal_to_canonical, validate_pagination


MAX_FILTER_BYTES = 15 * 1024 * 1024


def _oid(value):
    if isinstance(value, ObjectId):
        return value
    if not isinstance(value, str) or not ObjectId.is_valid(value):
        raise DomainError("INVALID_ID", "资源标识格式不正确。", status_code=422)
    return ObjectId(value)


def _limited(value):
    if len(BSON.encode(value)) > MAX_FILTER_BYTES:
        raise DomainError("STATISTICS_TOO_LARGE", "本次统计范围超出资源上限，请缩小范围。", status_code=503)
    return value


def _content(question):
    return {k: question.get(k) for k in ("type", "title", "required", "options", "validation")}


def _same_content(left, right):
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def _complete(definition):
    questions = definition.get("questions", [])
    refs = definition.get("questionRefs", [])
    if (not isinstance(questions, list) or not isinstance(refs, list)
            or any(not isinstance(q, dict) or not isinstance(q.get("id"), str) for q in questions)
            or any(not isinstance(r, dict) or not isinstance(r.get("instanceId"), str) for r in refs)):
        return False
    ids = [q.get("id") for q in questions]
    ref_ids = [r.get("instanceId") for r in refs]
    return (len(ids) == len(set(ids)) == len(ref_ids) == len(set(ref_ids))
            and set(ids) == set(ref_ids)
            and all(all(key in r for key in ("questionId", "questionVersionId", "rootQuestionId")) for r in refs))


def _source_readable(db, user, question, version_id):
    if question is None:
        return False
    from app.services.library_service import readable, manageable
    return readable(db, user, question) and (manageable(db, user, question) or
        db.question_version_state.find_one({"versionId": version_id, "selectable": True}) is not None)


def _answer_pipeline(response_filter, tuples):
    conditions = [{"surveyId": sid, "surveyDefinitionVersion": version, "answers.questionId": instance}
                  for sid, version, instance in tuples]
    match = _limited({"$or": conditions}) if conditions else {"_id": {"$exists": False}}
    return [{"$match": response_filter}, {"$unwind": "$answers"}, {"$match": match},
            {"$match": {"answers.value": {"$nin": [None, "", []]}}}]


def _number(value):
    number = value.to_decimal() if isinstance(value, Decimal128) else Decimal(str(value))
    if not number.is_finite():
        raise DomainError("INVALID_STORED_NUMBER", "历史数字答案不是有限数。")
    return number


def cross_statistics(db, user, question_id, version_id, page=1, page_size=20):
    question_id, version_id = _oid(question_id), _oid(version_id)
    validate_pagination(page, page_size)
    version = db.question_versions.find_one({"_id": version_id, "questionId": question_id})
    if version is None:
        raise DomainError("NOT_FOUND", "题目版本不存在。", status_code=404)
    question = db.questions.find_one({"_id": question_id})
    survey_query = statistics_scope.resolve_statistics_scope(db, user)
    surveys = {s["_id"]: s for s in db.surveys.find(survey_query)}
    ids = list(surveys)
    scope_filter = _limited({"surveyId": {"$in": ids}})
    definitions = {(s["_id"], s.get("definitionVersion", 1)): s for s in surveys.values()}
    if ids:
        for old in db.survey_versions.find(scope_filter):
            definitions.setdefault((old["surveyId"], old["definitionVersion"]), old)
    # Freeze membership before running multiple aggregate queries. Responses are
    # immutable, so subsequent inserts enter the next request only.
    frozen = list(db.responses.find(scope_filter, {"_id": 1, "surveyId": 1, "surveyDefinitionVersion": 1}))
    response_filter = _limited({"_id": {"$in": [r["_id"] for r in frozen]}, **scope_filter})
    tuples = []
    snapshot_content = None
    for (survey_id, definition_version), definition in definitions.items():
        by_id = {q["id"]: q for q in definition.get("questions", [])}
        for ref in definition.get("questionRefs", []):
            if ref.get("questionId") != question_id or ref.get("questionVersionId") != version_id:
                continue
            item = by_id.get(ref.get("instanceId"))
            if item is None:
                raise DomainError("MIGRATION_INCOMPLETE", "问卷题目来源与实例不一致。", status_code=409)
            projected = _content(item)
            if not _same_content(projected, version["content"]):
                raise DomainError("MIGRATION_INCOMPLETE", "问卷快照与其声明的题目版本不一致。", status_code=409)
            snapshot_content = projected
            tuples.append((survey_id, definition_version, item["id"]))
    if snapshot_content is None and not _source_readable(db, user, question, version_id):
        raise DomainError("NOT_FOUND", "题目不存在或不可访问。", status_code=404)
    answered_keys = {(r["surveyId"], r["surveyDefinitionVersion"]) for r in frozen}
    for key in answered_keys:
        if key not in definitions or not _complete(definitions[key]):
            raise DomainError("MIGRATION_INCOMPLETE", "本人已答问卷的题目来源尚未完整登记，请先完成迁移。", status_code=409)
    content = snapshot_content or version["content"]
    pipeline = _answer_pipeline(response_filter, tuples)
    result = {
        "questionId": str(question_id), "versionId": str(version_id),
        "versionNumber": version["versionNumber"], "title": content["title"], "type": content["type"],
        "answerCount": 0, "responseCount": 0, "surveyCount": 0,
        "average": None, "min": None, "max": None, "distinctValueCount": 0,
        "options": [], "distribution": [], "bySurvey": [],
        "scope": "my-surveys", "respondentLabel": "本卷去重填写账号数",
        "page": page, "pageSize": page_size,
    }
    # Group per response first so two instances in one response count as two
    # answers but one questionnaire submission and one within-survey account.
    groups = db.responses.aggregate(pipeline + [
        {"$group": {"_id": {"surveyId": "$surveyId", "responseId": "$_id"},
                    "answerCount": {"$sum": 1}, "person": {"$first": {"$ifNull": ["$respondentKey", None]}}}},
        {"$group": {"_id": "$_id.surveyId", "answerCount": {"$sum": "$answerCount"},
                    "responseCount": {"$sum": 1}, "people": {"$addToSet": "$person"}}},
    ])
    for row in groups:
        people = row["people"]
        result["bySurvey"].append({
            "surveyId": str(row["_id"]), "title": surveys[row["_id"]]["title"],
            "answerCount": row["answerCount"], "responseCount": row["responseCount"],
            "respondentCount": None if any(not isinstance(p, str) or not p for p in people) else len(people),
        })
    result["bySurvey"].sort(key=lambda row: row["surveyId"])
    result["answerCount"] = sum(r["answerCount"] for r in result["bySurvey"])
    result["responseCount"] = sum(r["responseCount"] for r in result["bySurvey"])
    result["surveyCount"] = len(result["bySurvey"])
    kind = content["type"]
    if kind in ("single", "multiple"):
        option_pipeline = ([{"$unwind": "$answers.value"}] if kind == "multiple" else [])
        counts = {row["_id"]: row["count"] for row in db.responses.aggregate(pipeline + option_pipeline + [
            {"$group": {"_id": "$answers.value", "count": {"$sum": 1}}},
        ])}
        result["options"] = [{"id": o["id"], "label": o["label"], "count": counts.get(o["id"], 0)} for o in content["options"]]
        result["distinctValueCount"] = len(counts)
    elif kind in ("number", "text"):
        value_groups = pipeline + [{"$group": {"_id": "$answers.value", "count": {"$sum": 1}}}]
        distinct = list(db.responses.aggregate(value_groups + [{"$count": "count"}]))
        result["distinctValueCount"] = distinct[0]["count"] if distinct else 0
        if kind == "number":
            rows = db.responses.aggregate(value_groups + [{"$sort": {"_id": 1}}, {"$skip": (page-1)*page_size}, {"$limit": page_size}])
            result["distribution"] = [{"value": decimal_to_canonical(_number(row["_id"])), "count": row["count"]} for row in rows]
            count = 0
            minimum = maximum = None
            with localcontext() as ctx:
                ctx.prec = 12400 + len(str(result["answerCount"]))
                total = Decimal(0)
                for row in db.responses.aggregate(pipeline + [{"$project": {"_id": 0, "value": "$answers.value"}}]):
                    value = _number(row["value"])
                    total += value
                    count += 1
                    minimum = value if minimum is None or value < minimum else minimum
                    maximum = value if maximum is None or value > maximum else maximum
            if count:
                with localcontext() as ctx:
                    ctx.prec = 34
                    result["average"] = str(total / Decimal(count))
                result["min"], result["max"] = decimal_to_canonical(minimum), decimal_to_canonical(maximum)
    return result

import hashlib
import hmac
import json

from pymongo.errors import DuplicateKeyError

from app.repositories import responses as repository
from app.services.answer_validator import normalize_answer
from app.services.definition_service import load_definition
from app.services.jump_engine import validate_answers_path
from app.services.storage_adapters import DomainError, from_storage_survey, to_storage_answer
from app.services.survey_service import effective_status


def respondent_key(settings, survey_id, user_id):
    message = f"respondent:v{settings.hmac_key_version}|{survey_id}|{user_id}".encode()
    return hmac.new(settings.respondent_hmac_secret.encode(), message, hashlib.sha256).hexdigest()


def normalize_payload(definition, payload):
    questions = {q["id"]: q for q in definition["questions"]}
    values = {}
    for answer in payload["answers"]:
        qid = answer["questionId"]
        if qid not in questions or qid in values:
            raise DomainError("INVALID_ANSWER", "题目不存在或存在重复答案。", [{"questionId": qid}])
        values[qid] = normalize_answer(questions[qid], answer["value"])
    # Missing and explicitly blank optional answers have the same semantic payload.
    ordered = [{"questionId": q["id"], "value": values[q["id"]]} for q in definition["questions"] if q["id"] in values and values[q["id"]] is not None]
    body = {"definitionVersion": payload["definitionVersion"], "isAnonymous": payload["isAnonymous"], "answers": ordered}
    hashed = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ordered, hashed


def receipt(record, replayed):
    return {"response": {"id": str(record["_id"]), "submittedAt": record["submittedAt"].isoformat(timespec="milliseconds"), "definitionVersion": record["surveyDefinitionVersion"]}, "replayed": replayed}


def assert_admissible(survey, version, anonymous, now):
    state = effective_status(survey, now)
    if state == "draft":
        raise DomainError("NOT_FOUND", "问卷尚未发布。", [], status_code=404)
    if state in {"closed", "expired"}:
        raise DomainError("SURVEY_CLOSED", "问卷已关闭或超过截止时间。", [], status_code=410)
    if survey["definitionVersion"] != version:
        raise DomainError("DEFINITION_VERSION_UNAVAILABLE", "该版本已停止接受新提交。", [], status_code=409)
    if anonymous and not survey.get("allowAnonymous", False):
        raise DomainError("ANONYMOUS_NOT_ALLOWED", "此问卷不允许匿名提交。", [])


def submit(db, settings, user, public_id, payload, clock):
    survey = db.surveys.find_one({"publicId": public_id})
    if not survey:
        raise DomainError("NOT_FOUND", "问卷不存在。", [], status_code=404)
    survey = from_storage_survey(survey)
    definition = load_definition(db, survey["_id"], payload["definitionVersion"])
    key = respondent_key(settings, survey["_id"], user["_id"])
    normalized, payload_hash = normalize_payload(definition, payload)
    # Historical-definition validation is also needed on replay: an off-path
    # blank answer must not disappear from the hash and bypass shape checks.
    result = validate_answers_path(definition["questions"], payload["answers"])
    existing = repository.find_submission(db, survey["_id"], key, payload["submissionKey"])
    if existing:
        if existing["payloadHash"] != payload_hash:
            raise DomainError("IDEMPOTENCY_CONFLICT", "同一次提交标识不能用于不同答案或匿名选择。", [], status_code=409)
        return receipt(existing, True), 200
    assert_admissible(survey, payload["definitionVersion"], payload["isAnonymous"], clock())
    fresh = db.surveys.find_one({"_id": survey["_id"]})
    if not fresh:
        raise DomainError("NOT_FOUND", "问卷不存在。", [], status_code=404)
    fresh = from_storage_survey(fresh)
    admitted_at = clock()
    assert_admissible(fresh, payload["definitionVersion"], payload["isAnonymous"], admitted_at)
    record = {
        "surveyId": survey["_id"], "surveyDefinitionVersion": payload["definitionVersion"],
        "respondentKey": key, "hmacKeyVersion": settings.hmac_key_version,
        "respondentUserId": None if payload["isAnonymous"] else user["_id"],
        "isAnonymous": payload["isAnonymous"], "repeatMode": "multiple" if fresh["allowMultipleSubmissions"] else "single",
        "submissionKey": payload["submissionKey"], "payloadHash": payload_hash,
        "visitedQuestionIds": result["visitedQuestionIds"],
        "answers": [to_storage_answer(a) for a in result["answers"]],
        "admittedAt": admitted_at, "submittedAt": clock(), "schemaVersion": 1,
    }
    try:
        record["_id"] = repository.insert_response(db, record).inserted_id
    except DuplicateKeyError:
        existing = repository.find_submission(db, survey["_id"], key, payload["submissionKey"])
        if existing and existing["payloadHash"] == payload_hash:
            return receipt(existing, True), 200
        if existing:
            raise DomainError("IDEMPOTENCY_CONFLICT", "同一次提交标识的内容不同。", [], status_code=409)
        raise DomainError("ALREADY_SUBMITTED", "你已经填写过此问卷。", [], status_code=409)
    return receipt(record, False), 201

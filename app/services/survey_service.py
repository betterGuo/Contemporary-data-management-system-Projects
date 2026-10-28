import copy
import secrets
import uuid
from datetime import datetime, timezone

from bson import BSON, ObjectId

from app.repositories import surveys as repository
from app.services.question_types import validate_definition
from app.services.storage_adapters import DomainError, normalize_text


def object_id(value):
    if not ObjectId.is_valid(value):
        raise DomainError("INVALID_ID", "资源标识格式不正确。", [], status_code=422)
    return ObjectId(value)


def effective_status(survey, now):
    if survey["status"] == "published" and survey.get("closesAt") and now >= survey["closesAt"]:
        return "expired"
    return survey["status"]


def owned(db, survey_id, user_id):
    survey = repository.by_owner(db, object_id(survey_id), user_id)
    if not survey:
        raise DomainError("NOT_FOUND", "问卷不存在。", [], status_code=404)
    return survey


def parse_deadline(value):
    if value is None or value == "":
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise DomainError("INVALID_DEADLINE", "截止时间须包含时区。", [{"field": "closesAt"}])
        return result.astimezone(timezone.utc)
    except DomainError:
        raise
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise DomainError("INVALID_DEADLINE", "截止时间格式不正确。", [{"field": "closesAt"}])


def metadata(data):
    result = {}
    for key in ["title", "description"]:
        if key in data:
            value = data[key]
            if not isinstance(value, str):
                raise DomainError("INVALID_SETTINGS", "标题和说明必须是文字。", [{"field": key}])
            value = normalize_text(value)
            if (key == "title" and not value) or len(value) > (200 if key == "title" else 2000):
                raise DomainError("INVALID_SETTINGS", "标题不能为空且至多 200 字，说明至多 2000 字。", [{"field": key}])
            result[key] = value
    for key in ["allowAnonymous", "allowMultipleSubmissions"]:
        if key in data:
            if type(data[key]) is not bool:
                raise DomainError("INVALID_SETTINGS", "问卷开关必须为布尔值。", [{"field": key}])
            result[key] = data[key]
    if "closesAt" in data:
        result["closesAt"] = parse_deadline(data["closesAt"])
    return result


def prepare_question(raw):
    question = copy.deepcopy(raw)
    question.setdefault("id", str(uuid.uuid4()))
    if "options" in question and isinstance(question["options"], list):
        for option in question["options"]:
            if isinstance(option, dict):
                option.setdefault("id", str(uuid.uuid4()))
    if "jumpRules" in question and isinstance(question["jumpRules"], list):
        for rule in question["jumpRules"]:
            if isinstance(rule, dict):
                rule.setdefault("id", str(uuid.uuid4()))
    return question


def create(db, user_id, data, now):
    record = {**metadata(data), "ownerId": user_id, "publicId": secrets.token_urlsafe(12), "status": "draft", "questions": [], "revision": 1, "definitionVersion": 1, "schemaVersion": 1, "createdAt": now, "updatedAt": now, "publishedAt": None, "closedAt": None}
    record["_id"] = db.surveys.insert_one(record).inserted_id
    return record


def patch(db, user_id, survey_id, data, now, max_bytes=512*1024):
    survey = owned(db, survey_id, user_id)
    if survey["status"] != "draft":
        raise DomainError("SURVEY_FROZEN", "已发布的问卷内容不能修改。", [], status_code=409)
    if survey["revision"] != data["revision"]:
        raise DomainError("REVISION_CONFLICT", "问卷已被修改，请重新加载。", [], status_code=409)
    changes = metadata(data)
    if "questions" in data:
        if not isinstance(data["questions"], list):
            raise DomainError("INVALID_QUESTIONS", "题目必须为数组。", [])
        changes["questions"] = validate_definition([prepare_question(q) for q in data["questions"]], publishing=False)
    changes["updatedAt"] = now
    size_candidate = {key: value for key, value in {**survey, **changes}.items() if key != "questionRefs"}
    if len(BSON.encode(size_candidate)) > max_bytes:
        raise DomainError("DEFINITION_TOO_LARGE", "问卷内容超过项目资源上限。", [])
    if survey.get("questionRefs"):
        from app.services import library_service, question_reference_service as bindings

        def work(session):
            fresh = bindings.own_survey(db, {"_id": user_id}, survey_id, session, revision=data["revision"], draft=True)
            questions = changes.get("questions", fresh["questions"])
            refs = bindings.preserve_references(db, fresh, questions, session)
            extra = {key: value for key, value in changes.items() if key != "questions"}
            return bindings.update_survey(db, fresh, questions, refs, now, session, max_bytes, extra)

        return library_service.transaction(db, work)
    updated = repository.update_draft(db, survey["_id"], user_id, data["revision"], changes)
    if not updated:
        raise DomainError("REVISION_CONFLICT", "问卷状态或内容已变化，请重新加载。", [], status_code=409)
    return updated


def publish(db, user_id, survey_id, revision, now):
    survey = owned(db, survey_id, user_id)
    if survey["status"] != "draft" or survey["revision"] != revision:
        raise DomainError("REVISION_CONFLICT", "问卷已修改或已发布，请重新加载。", [], status_code=409)
    questions = validate_definition(survey["questions"], publishing=True)
    from app.services.statistics_service import STATISTICS_HANDLERS
    if any(q["type"] not in STATISTICS_HANDLERS for q in questions):
        raise DomainError("MISSING_STATISTICS_HANDLER", "题型缺少统计处理器，不能发布。", [])
    if survey.get("closesAt") and survey["closesAt"] <= now:
        raise DomainError("INVALID_DEADLINE", "发布时截止时间必须晚于当前时间。", [{"field": "closesAt"}])
    from app.services import library_service, question_reference_service as bindings

    def work(session):
        fresh = bindings.own_survey(db, {"_id": user_id}, survey_id, session, revision=revision, draft=True)
        fresh["questions"] = questions
        user = db.users.find_one({"_id": user_id}, session=session)
        refs = bindings.register_definition(db, fresh, user, now, session)
        bindings.mark_published(db, refs, now, session)
        return bindings.update_survey(db, fresh, questions, refs, now, session,
            extra={"status": "published", "publishedAt": now})

    return library_service.transaction(db, work)

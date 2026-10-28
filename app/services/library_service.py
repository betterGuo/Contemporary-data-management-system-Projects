"""Independent questions, immutable editions and explicit access decisions.

Question content never depends on the availability of a parent question.  All
multi-document writes run on a real MongoDB transaction; no in-memory lock is
used as a substitute for database atomicity.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re

from bson import BSON, ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern

from app.services.question_types import validate_question
from app.services.storage_adapters import DomainError, normalize_text, validate_pagination


CONTENT_FIELDS = ("type", "title", "required", "options", "validation")
MAX_CONTENT_BYTES = 512 * 1024


def _utf8(value, message="输入包含无法保存的Unicode字符。"):
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise DomainError("INVALID_UNICODE", message) from error
    return value


def oid(value):
    if isinstance(value, ObjectId):
        return value
    if not isinstance(value, str) or not ObjectId.is_valid(value):
        raise DomainError("INVALID_ID", "资源标识格式不正确。")
    return ObjectId(value)


def content(raw):
    if not isinstance(raw, dict) or set(raw) - {*CONTENT_FIELDS, "id", "jumpRules"}:
        raise DomainError("INVALID_DEFINITION", "题目内容包含未知字段。")
    value = {key: deepcopy(raw[key]) for key in CONTENT_FIELDS if key in raw}
    if isinstance(value.get("options", []), list):
        for index, option in enumerate(value.get("options", [])):
            if isinstance(option, dict):
                option.setdefault("id", f"option-{index + 1}")
    normalized = validate_question({**value, "id": "library-content", "jumpRules": []})
    result = {key: normalized[key] for key in CONTENT_FIELDS}
    try:
        encoded_size = len(BSON.encode(result))
    except UnicodeError as error:
        raise DomainError("INVALID_DEFINITION", "题目内容包含无法保存的Unicode字符。") from error
    if encoded_size > MAX_CONTENT_BYTES:
        raise DomainError("DEFINITION_TOO_LARGE", f"单题内容超过{MAX_CONTENT_BYTES // 1024} KiB上限。")
    return result


def content_hash(value):
    return hashlib.sha256(json.dumps(content(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _admin(db, user, session=None):
    current = db.users.find_one({"_id": user["_id"]}, {"role": 1}, session=session)
    return bool(current and current.get("role") == "admin")


def manageable(db, user, question, session=None):
    if not question:
        return False
    if question.get("visibility", "private") == "public":
        return _admin(db, user, session)
    return question["ownerId"] == user["_id"]


def readable(db, user, question, session=None):
    if not question:
        return False
    if manageable(db, user, question, session):
        return True
    if question["status"] != "active" or not question.get("latestVersionNumber"):
        return False
    if question.get("visibility") == "public":
        return True
    return db.question_grants.find_one({"questionId": question["_id"], "granteeId": user["_id"], "active": True}, session=session) is not None


def require_question(db, user, question_id, *, manage=False, session=None):
    question = db.questions.find_one({"_id": oid(question_id)}, session=session)
    if not readable(db, user, question, session):
        raise DomainError("NOT_FOUND", "题目不存在或当前不可访问。", status_code=404)
    if manage and not manageable(db, user, question, session):
        raise DomainError("FORBIDDEN", "你没有修改这道题目的权限。", status_code=403)
    return question


def transaction(db, work):
    hello = db.client.admin.command("hello")
    if not hello.get("setName") and hello.get("msg") != "isdbgrid":
        raise DomainError("TRANSACTIONS_REQUIRED", "题库写操作需要MongoDB副本集，请使用第二阶段启动配置。", status_code=503)
    with db.client.start_session() as session:
        return session.with_transaction(work, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority"), read_preference=ReadPreference.PRIMARY, max_commit_time_ms=10000)


def idempotent(db, user_id, operation, request_key, payload, work):
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
        raise DomainError("INVALID_REQUEST_KEY", "请求标识须为1至128字的字符串。")
    _utf8(request_key)
    identity = {"actorId": user_id, "operation": operation, "requestKey": request_key}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(_utf8(canonical).encode()).hexdigest()

    def replay(row):
        if row["payloadHash"] != digest:
            raise DomainError("IDEMPOTENCY_CONFLICT", "同一请求标识不能用于不同内容。", status_code=409)
        return deepcopy(row["result"])

    old = db.operation_receipts.find_one(identity)
    if old:
        return replay(old)

    def execute(session):
        old = db.operation_receipts.find_one(identity, session=session)
        if old:
            return replay(old)
        result = work(session)
        db.operation_receipts.insert_one({**identity, "payloadHash": digest, "result": result, "createdAt": datetime.now(timezone.utc)}, session=session)
        return result

    try:
        return transaction(db, execute)
    except DuplicateKeyError:
        old = db.operation_receipts.find_one(identity)
        if old:
            return replay(old)
        raise DomainError("REVISION_CONFLICT", "资源已被另一个请求修改，请重新加载后比较。", status_code=409)


def guard_version(db, user, version_id, session):
    version = db.question_versions.find_one({"_id": oid(version_id)}, session=session)
    if not version:
        raise DomainError("SOURCE_UNAVAILABLE", "所选题目版本不存在。", status_code=404)
    question = require_question(db, user, version["questionId"], session=session)
    if question["status"] != "active":
        raise DomainError("SOURCE_UNAVAILABLE", "来源题目已归档，不能新增选用。", status_code=409)
    updated = db.questions.find_one_and_update({"_id": question["_id"], "status": "active"}, {"$inc": {"selectionGuard": 1}}, return_document=ReturnDocument.AFTER, session=session)
    state = db.question_version_state.find_one_and_update({"versionId": version["_id"], "selectable": True}, {"$inc": {"selectionGuard": 1}}, return_document=ReturnDocument.AFTER, session=session)
    if not updated or not state:
        raise DomainError("SOURCE_UNAVAILABLE", "该版本已经停止新增选用。", status_code=409)
    if not manageable(db, user, question, session) and question.get("visibility") != "public":
        grant = db.question_grants.find_one_and_update({"questionId": question["_id"], "granteeId": user["_id"], "active": True}, {"$inc": {"selectionGuard": 1}}, return_document=ReturnDocument.AFTER, session=session)
        if not grant:
            raise DomainError("SOURCE_UNAVAILABLE", "来源共享已撤回。", status_code=403)
    return updated, version


def _insert_version(db, question, value, version_id, number, user, now, session, source=None, reason=""):
    row = {"_id": version_id, "questionId": question["_id"], "versionNumber": number, "content": value, "contentHash": content_hash(value), "derivedFromVersionId": source, "createdBy": user["_id"], "changeReason": reason[:2000], "createdAt": now}
    db.question_versions.insert_one(row, session=session)
    db.question_version_state.insert_one({"versionId": version_id, "selectable": True, "revision": 1, "selectionGuard": 0, "changedBy": user["_id"], "changedAt": now}, session=session)
    return row


def new_question(db, user, raw, now, session, visibility="private", root_id=None, derived_from=None, formal=False, legacy_key=None, published=False):
    if visibility not in {"private", "public"}:
        raise DomainError("INVALID_VISIBILITY", "题目可见性必须为private或public。")
    if visibility == "public" and not _admin(db, user, session):
        raise DomainError("FORBIDDEN", "只有管理员可以创建公共题。", status_code=403)
    value = content(raw)
    derived_from = oid(derived_from) if derived_from is not None else None
    question_id = ObjectId()
    version_id = ObjectId() if formal else None
    record = {"_id": question_id, "ownerId": user["_id"], "createdBy": user["_id"], "visibility": visibility, "status": "active", "rootQuestionId": oid(root_id) if root_id else question_id,
              "title": value["title"], "type": value["type"], "workingContent": value, "workingContentHash": content_hash(value), "workingBaseVersionId": version_id or derived_from,
              "hasPublishedUsage": bool(published), "latestVersionId": version_id, "latestVersionNumber": 1 if formal else 0, "revision": 1, "selectionGuard": 0, "schemaVersion": 2, "createdAt": now, "updatedAt": now}
    if legacy_key is not None:
        record["legacyOriginKey"] = legacy_key
    db.questions.insert_one(record, session=session)
    if formal:
        _insert_version(db, record, value, version_id, 1, user, now, session, derived_from, "迁移登记" if legacy_key else "创建首版")
    db.question_bookmarks.insert_one({"userId": user["_id"], "questionId": question_id, "tags": ["第一阶段导入"] if legacy_key else [], "selectedVersionId": version_id, "revision": 1, "addedAt": now}, session=session)
    return record


def _cas_filter(db, user, question, revision, session):
    if question["status"] != "active":
        raise DomainError("SOURCE_UNAVAILABLE", "题目已归档。", status_code=409)
    if not manageable(db, user, question, session):
        raise DomainError("FORBIDDEN", "你没有修改这道题目的权限。", status_code=403)
    query = {"_id": question["_id"], "status": "active", "revision": revision}
    if question.get("visibility") == "public":
        query["visibility"] = "public"
    else:
        query["ownerId"] = user["_id"]
    return query


def _check_updated(updated):
    if not updated:
        raise DomainError("REVISION_CONFLICT", "题目已被修改，请重新加载后比较，当前输入不会自动覆盖。", status_code=409)
    return updated


def create(db, user, payload, now):
    value = content(payload["content"])
    result = idempotent(db, user["_id"], "create-question", payload["requestKey"], {"content": value, "visibility": payload["visibility"]},
                        lambda session: {"questionId": new_question(db, user, value, now, session, visibility=payload["visibility"])["_id"]})
    return question_dto(db, user, require_question(db, user, result["questionId"]))


def save_working(db, user, question_id, payload, now):
    require_question(db, user, question_id, manage=True)
    value = content(payload["content"])

    def work(session):
        question = require_question(db, user, question_id, manage=True, session=session)
        query = _cas_filter(db, user, question, payload["revision"], session)
        if question.get("hasPublishedUsage"):
            raise DomainError("VERSION_REQUIRED", "此题曾被已发布问卷使用，请保存为新版本。", status_code=409)
        if question["revision"] != payload["revision"]:
            _check_updated(None)
        if question["workingContentHash"] == content_hash(value):
            return question
        query["hasPublishedUsage"] = False
        return _check_updated(db.questions.find_one_and_update(query, {"$set": {"workingContent": value, "workingContentHash": content_hash(value), "title": value["title"], "type": value["type"], "updatedAt": now}, "$inc": {"revision": 1}}, return_document=ReturnDocument.AFTER, session=session))

    question = transaction(db, work)
    return question_dto(db, user, question)


def _save_version(db, user, question_id, payload, now, *, restore=False):
    require_question(db, user, question_id, manage=True)
    raw_payload = deepcopy(payload)

    def work(session):
        question = require_question(db, user, question_id, manage=True, session=session)
        if question["revision"] != payload["revision"]:
            _check_updated(None)
        source_id = payload.get("versionId") if restore else payload.get("sourceVersionId")
        if source_id is not None:
            source = db.question_versions.find_one({"_id": oid(source_id), "questionId": question["_id"]}, session=session)
            if not source:
                raise DomainError("INVALID_SOURCE_VERSION", "来源版本不属于这道题。")
        else:
            source = None
        value = source["content"] if restore else content(payload["content"])
        if question["latestVersionNumber"] and source is None:
            raise DomainError("SOURCE_VERSION_REQUIRED", "修订必须明确选择来源版本。")
        version_id = ObjectId()
        updated = _check_updated(db.questions.find_one_and_update(_cas_filter(db, user, question, payload["revision"], session),
            {"$set": {"latestVersionId": version_id, "workingBaseVersionId": version_id, "workingContent": value, "workingContentHash": content_hash(value), "title": value["title"], "type": value["type"], "updatedAt": now}, "$inc": {"revision": 1, "latestVersionNumber": 1}},
            return_document=ReturnDocument.AFTER, session=session))
        _insert_version(db, updated, value, version_id, updated["latestVersionNumber"], user, now, session, source["_id"] if source else None, "恢复旧版" if restore else payload.get("reason", ""))
        return {"questionId": question["_id"], "versionId": version_id}

    result = idempotent(db, user["_id"], ("restore:" if restore else "save-version:") + str(question_id), payload["requestKey"], raw_payload, work)
    question = require_question(db, user, result["questionId"], manage=True)
    version = db.question_versions.find_one({"_id": result["versionId"]})
    return {"question": question_dto(db, user, question), "version": version_dto(db, version)}


def save_version(db, user, question_id, payload, now):
    return _save_version(db, user, question_id, payload, now)


def restore(db, user, question_id, payload, now):
    return _save_version(db, user, question_id, payload, now, restore=True)


def derive(db, user, question_id, payload, now):
    def work(session):
        question, version = guard_version(db, user, payload["versionId"], session)
        if question["_id"] != oid(question_id):
            raise DomainError("INVALID_SOURCE_VERSION", "版本不属于这道题。")
        value = content(payload["content"]) if payload.get("content") is not None else version["content"]
        own = new_question(db, user, value, now, session, root_id=question["rootQuestionId"], derived_from=version["_id"], formal=True)
        return {"questionId": own["_id"]}

    result = idempotent(db, user["_id"], "derive:" + str(question_id), payload["requestKey"], payload, work)
    return question_dto(db, user, require_question(db, user, result["questionId"]))


def archive(db, user, question_id, revision, now):
    require_question(db, user, question_id, manage=True)

    def work(session):
        question = require_question(db, user, question_id, manage=True, session=session)
        if question["status"] == "archived" and question["revision"] == revision:
            return question
        return _check_updated(db.questions.find_one_and_update(_cas_filter(db, user, question, revision, session), {"$set": {"status": "archived", "updatedAt": now}, "$inc": {"revision": 1}}, return_document=ReturnDocument.AFTER, session=session))

    return question_dto(db, user, transaction(db, work))


def availability(db, user, question_id, version_id, payload, now):
    require_question(db, user, question_id, manage=True)

    def work(session):
        question = require_question(db, user, question_id, manage=True, session=session)
        version = db.question_versions.find_one({"_id": oid(version_id), "questionId": question["_id"]}, session=session)
        if not version:
            raise DomainError("NOT_FOUND", "版本不存在。", status_code=404)
        state = db.question_version_state.find_one_and_update({"versionId": version["_id"], "revision": payload["revision"]},
            {"$set": {"selectable": payload["selectable"], "changedBy": user["_id"], "changedAt": now}, "$inc": {"revision": 1}}, return_document=ReturnDocument.AFTER, session=session)
        _check_updated(state)
        return version

    return version_dto(db, transaction(db, work))


def grants(db, user, question_id):
    question = require_question(db, user, question_id, manage=True)
    result = []
    for row in db.question_grants.find({"questionId": question["_id"]}).sort("createdAt", 1):
        receiver = db.users.find_one({"_id": row["granteeId"]}, {"username": 1})
        result.append({"id": str(row["_id"]), "username": receiver["username"] if receiver else "已不可用账号", "active": row["active"], "revision": row["revision"]})
    return result


def grant(db, user, question_id, payload, now):
    require_question(db, user, question_id, manage=True)
    _utf8(payload["username"])

    def work(session):
        question = require_question(db, user, question_id, manage=True, session=session)
        if question.get("visibility") == "public":
            raise DomainError("PUBLIC_QUESTION", "公共题无需定向共享。")
        name = normalize_text(payload["username"]).casefold()
        receiver = db.users.find_one({"usernameNormalized": name}, session=session)
        if not receiver or receiver["_id"] == user["_id"]:
            raise DomainError("INVALID_RECEIVER", "请输入另一个已注册用户的准确用户名。")
        _check_updated(db.questions.find_one_and_update(_cas_filter(db, user, question, payload["revision"], session), {"$inc": {"revision": 1}, "$set": {"updatedAt": now}}, session=session))
        db.question_grants.update_one({"questionId": question["_id"], "granteeId": receiver["_id"]},
            {"$set": {"active": True, "grantedBy": user["_id"], "updatedAt": now}, "$inc": {"revision": 1}, "$setOnInsert": {"createdAt": now, "selectionGuard": 0}}, upsert=True, session=session)

    transaction(db, work)
    return {"question": question_dto(db, user, require_question(db, user, question_id)), "grants": grants(db, user, question_id)}


def revoke(db, user, question_id, grant_id, revision, now):
    require_question(db, user, question_id, manage=True)

    def work(session):
        question = require_question(db, user, question_id, manage=True, session=session)
        _check_updated(db.questions.find_one_and_update(_cas_filter(db, user, question, revision, session), {"$inc": {"revision": 1}, "$set": {"updatedAt": now}}, session=session))
        result = db.question_grants.update_one({"_id": oid(grant_id), "questionId": question["_id"]}, {"$set": {"active": False, "updatedAt": now}, "$inc": {"revision": 1}}, session=session)
        if not result.matched_count:
            raise DomainError("NOT_FOUND", "共享记录不存在。", status_code=404)

    transaction(db, work)
    return {"question": question_dto(db, user, require_question(db, user, question_id)), "grants": grants(db, user, question_id)}


def _tags(raw):
    if not isinstance(raw, list) or len(raw) > 20 or any(not isinstance(tag, str) for tag in raw):
        raise DomainError("INVALID_TAGS", "每题最多20个文字标签。")
    tags = sorted(set(normalize_text(tag) for tag in raw))
    try:
        for tag in tags:
            tag.encode("utf-8")
    except UnicodeError as error:
        raise DomainError("INVALID_TAGS", "标签包含无法保存的Unicode字符。") from error
    if any(not tag or len(tag) > 50 for tag in tags):
        raise DomainError("INVALID_TAGS", "标签须为1至50字。")
    return tags


def bookmark(db, user, payload, now):
    tags = _tags(payload["tags"])

    def work(session):
        question = require_question(db, user, payload["questionId"], session=session)
        version_id = oid(payload["versionId"]) if payload.get("versionId") else None
        existing = db.question_bookmarks.find_one({"userId": user["_id"], "questionId": question["_id"]}, session=session)
        tags_only = existing is not None and existing.get("selectedVersionId") == version_id
        if not tags_only and question["status"] != "active":
            raise DomainError("SOURCE_UNAVAILABLE", "来源题目已归档，不能新增收藏或更换收藏版本。", status_code=409)
        if version_id and not tags_only:
            _, version = guard_version(db, user, version_id, session)
            if version["questionId"] != question["_id"]:
                raise DomainError("INVALID_SOURCE_VERSION", "收藏版本不属于这道题。")
        db.question_bookmarks.update_one({"userId": user["_id"], "questionId": question["_id"]}, {"$set": {"tags": tags, "selectedVersionId": version_id}, "$inc": {"revision": 1}, "$setOnInsert": {"addedAt": now}}, upsert=True, session=session)
        # Resolve the response in the same snapshot: an unavailable source
        # must roll back the tag write instead of committing and then returning
        # a misleading 404 from a later, independent projection.
        return question_dto(db, user, question, session=session)

    return transaction(db, work)


def remove_bookmark(db, user, question_id):
    db.question_bookmarks.delete_one({"userId": user["_id"], "questionId": oid(question_id)})


def rename_tag(db, user, old_tag, new_tag):
    old = _tags([old_tag])[0]
    new = _tags([new_tag])[0] if new_tag is not None else None

    def work(session):
        count = 0
        for row in db.question_bookmarks.find({"userId": user["_id"], "tags": old}, session=session):
            tags = [tag for tag in row["tags"] if tag != old]
            if new:
                tags.append(new)
            db.question_bookmarks.update_one({"_id": row["_id"], "userId": user["_id"], "revision": row["revision"]}, {"$set": {"tags": sorted(set(tags))}, "$inc": {"revision": 1}}, session=session)
            count += 1
            if count > 500:
                raise DomainError("TOO_MANY_BOOKMARKS", "单次标签操作最多处理500个收藏，请分组整理。")
        return {"modified": count}

    return transaction(db, work)


def version_dto(db, version, state=None):
    state = state or db.question_version_state.find_one({"versionId": version["_id"]}) or {}
    return {"id": str(version["_id"]), "questionId": str(version["questionId"]), "versionNumber": version["versionNumber"], "content": deepcopy(version["content"]),
            "contentHash": version["contentHash"], "derivedFromVersionId": str(version["derivedFromVersionId"]) if version.get("derivedFromVersionId") else None,
            "reason": version.get("changeReason", ""), "createdAt": version["createdAt"].isoformat(), "selectable": bool(state.get("selectable")), "revision": state.get("revision", 1)}


def question_dto(db, user, question, bookmark_record=None, *, session=None):
    can_manage = manageable(db, user, question, session)
    bookmark_record = bookmark_record or db.question_bookmarks.find_one({"userId": user["_id"], "questionId": question["_id"]}, session=session) or {}
    states = {row["versionId"]: row for row in db.question_version_state.find({"versionId": {"$in": [row["_id"] for row in db.question_versions.find({"questionId": question["_id"]}, {"_id": 1}, session=session)]}, "selectable": True}, session=session)}
    versions = list(db.question_versions.find({"questionId": question["_id"], "_id": {"$in": list(states)}}, session=session).sort("versionNumber", -1))
    latest = versions[0] if versions else None
    shown_content = question["workingContent"] if can_manage else latest["content"] if latest else None
    if shown_content is None:
        raise DomainError("NOT_FOUND", "此题尚无可查看的正式版本。", status_code=404)
    selected_id = bookmark_record.get("selectedVersionId")
    selected = db.question_versions.find_one({"_id": selected_id, "questionId": question["_id"]}, session=session) if selected_id else None
    creator = db.users.find_one({"_id": question["createdBy"]}, {"username": 1}, session=session)
    result = {"id": str(question["_id"]), "ownerId": str(question["ownerId"]), "authorName": creator.get("username", "已不可用账号") if creator else "已不可用账号", "title": shown_content["title"], "type": shown_content["type"],
              "latestVersionId": str(question["latestVersionId"]) if question.get("latestVersionId") else None, "latestVersionNumber": question["latestVersionNumber"],
              "latestSelectableVersionId": str(latest["_id"]) if latest else None, "latestSelectableVersionNumber": latest["versionNumber"] if latest else None,
              "revision": question["revision"], "visibility": question["visibility"], "status": question["status"], "rootQuestionId": str(question["rootQuestionId"]), "hasPublishedUsage": question["hasPublishedUsage"],
              "canManage": can_manage, "bookmarkTags": bookmark_record.get("tags", []), "selectedVersionId": str(selected_id) if selected_id else None, "bookmarkRevision": bookmark_record.get("revision"),
              "hasUpdate": bool(latest and selected and latest["versionNumber"] > selected["versionNumber"]), "content": deepcopy(shown_content), "updatedAt": question["updatedAt"].isoformat()}
    if can_manage:
        result["workingContent"] = deepcopy(question["workingContent"])
        result["workingBaseVersionId"] = str(question["workingBaseVersionId"]) if question.get("workingBaseVersionId") else None
    return result


def listing(db, user, scope="mine", query="", tag=None, page=1, page_size=20):
    validate_pagination(page, page_size)
    if scope not in {"mine", "shared", "public", "bookmarks"}:
        raise DomainError("INVALID_SCOPE", "未知题目列表范围。")
    if len(query) > 100:
        raise DomainError("INVALID_SEARCH", "搜索文字最多100字。")
    own = {"ownerId": user["_id"]}
    if scope == "mine":
        predicate = own
    elif scope == "shared":
        ids = db.question_grants.distinct("questionId", {"granteeId": user["_id"], "active": True})
        predicate = {"_id": {"$in": ids}, "status": "active", "latestVersionNumber": {"$gt": 0}}
    elif scope == "public":
        predicate = {"visibility": "public", "status": "active", "latestVersionNumber": {"$gt": 0}}
    else:
        ids = db.question_bookmarks.distinct("questionId", {"userId": user["_id"], **({"tags": tag} if tag else {})})
        grant_ids = db.question_grants.distinct("questionId", {"granteeId": user["_id"], "active": True})
        predicate = {"_id": {"$in": ids}, "$or": [own, {"visibility": "public", "status": "active"}, {"_id": {"$in": grant_ids}, "status": "active"}]}
    if tag and scope != "bookmarks":
        ids = db.question_bookmarks.distinct("questionId", {"userId": user["_id"], "tags": tag})
        predicate = {"$and": [predicate, {"_id": {"$in": ids}}]}
    # Non-maintainers search only immutable, selectable edition content.  The
    # mutable title on the management record must not leak unpublished edits.
    rows = []
    needle = normalize_text(query).casefold()
    for question in db.questions.find(predicate).sort([("updatedAt", -1), ("_id", -1)]):
        if not readable(db, user, question):
            continue
        try:
            dto = question_dto(db, user, question)
        except DomainError as error:
            if error.status_code == 404:
                continue
            raise
        text = json.dumps(dto["content"], ensure_ascii=False).casefold()
        if not needle or needle in text:
            rows.append(dto)
        if len(rows) > 2000:
            raise DomainError("TOO_MANY_QUESTIONS", "搜索范围过大，请缩小标签或关键词。", status_code=503)
    return {"questions": rows[(page-1)*page_size:page*page_size], "total": len(rows), "page": page, "pageSize": page_size}


def versions(db, user, question_id):
    question = require_question(db, user, question_id)
    manager = manageable(db, user, question)
    result = []
    for row in db.question_versions.find({"questionId": question["_id"]}).sort("versionNumber", -1):
        dto = version_dto(db, row)
        if manager or dto["selectable"]:
            result.append(dto)
    return result


def usage(db, user, question_id, version_id=None, scope=None):
    question = require_question(db, user, question_id)
    scope = scope or ("version" if version_id else "question")
    if scope not in {"version", "question", "root"} or (scope == "version" and not version_id):
        raise DomainError("INVALID_USAGE_SCOPE", "使用范围须为version、question或root；version范围需指定版本。")
    if scope == "root":
        family = [row for row in db.questions.find({"rootQuestionId": question["rootQuestionId"]}) if readable(db, user, row)]
    else:
        family = [question]
    visible_ids = [row["_id"] for row in family]
    manageable_ids = [row["_id"] for row in family if manageable(db, user, row)]
    query = {"questionId": {"$in": visible_ids}}
    if scope == "version":
        version = db.question_versions.find_one({"_id": oid(version_id), "questionId": question["_id"]})
        if not version:
            raise DomainError("NOT_FOUND", "版本不存在。", status_code=404)
        query["versionId"] = version["_id"]
    mine_ids = db.question_usage.distinct("surveyId", {**query, "surveyOwnerId": user["_id"]})
    mine = []
    for survey in db.surveys.find({"_id": {"$in": mine_ids}, "ownerId": user["_id"]}).sort("createdAt", -1):
        mine.append({"id": str(survey["_id"]), "title": survey["title"], "status": survey["status"], "responseCount": db.responses.count_documents({"surveyId": survey["_id"]}),
                     "currentInstances": [ref["instanceId"] for ref in survey.get("questionRefs", []) if ref["questionId"] in visible_ids and (scope != "version" or ref["questionVersionId"] == oid(version_id))]})
    result = {"surveys": mine, "scope": scope, "visibleQuestionCount": len(visible_ids), "coverage": "自第一阶段迁移登记起可追溯的累计使用；移除实例不减少历史数。", "canSeeOtherCount": bool(manageable_ids)}
    if result["canSeeOtherCount"]:
        # A readable family member is not necessarily maintainable.  Root
        # lineage never grants its owner usage-count rights over derivatives.
        count_query = {**query, "questionId": {"$in": manageable_ids}, "surveyOwnerId": {"$ne": user["_id"]}}
        others = db.question_usage.distinct("surveyId", count_query)
        result["otherSurveyCount"] = len(others)
        result["deletedOtherSurveyCount"] = len(db.question_usage.distinct("surveyId", {**count_query, "surveyDeleted": True}))
        result["otherCountScope"] = "仅当前有维护权限的题目；同源可见不等于拥有派生题维护权限。"
    return result

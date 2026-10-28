"""Bind immutable library versions to existing survey instances and snapshots."""
from copy import deepcopy
from uuid import uuid4

from bson import BSON
from pymongo import ReturnDocument

from app.services import library_service as library
from app.services.question_types import validate_definition
from app.services.storage_adapters import DomainError


def reference(question, version, instance_id):
    return {"instanceId": instance_id, "questionId": question["_id"], "questionVersionId": version["_id"],
            "rootQuestionId": question["rootQuestionId"], "contentHash": version["contentHash"]}


def register_usage(db, survey, ref, now, session, origin="selection"):
    identity = {"surveyId": survey["_id"], "surveyDefinitionVersion": survey["definitionVersion"],
                "instanceId": ref["instanceId"], "versionId": ref["questionVersionId"]}
    db.question_usage.update_many({"surveyId": survey["_id"], "surveyDefinitionVersion": survey["definitionVersion"],
                                   "instanceId": ref["instanceId"], "versionId": {"$ne": ref["questionVersionId"]}},
                                  {"$set": {"isCurrent": False}}, session=session)
    db.question_usage.update_one(identity, {"$set": {"isCurrent": True}, "$setOnInsert": {
        "questionId": ref["questionId"], "rootQuestionId": ref["rootQuestionId"], "surveyOwnerId": survey["ownerId"],
        "surveyDeleted": False, "observedAt": now, "origin": origin}}, upsert=True, session=session)


def own_survey(db, user, survey_id, session=None, *, revision=None, draft=False):
    row = db.surveys.find_one({"_id": library.oid(survey_id), "ownerId": user["_id"]}, session=session)
    if not row:
        raise DomainError("NOT_FOUND", "问卷不存在。", status_code=404)
    if draft and row["status"] != "draft":
        raise DomainError("SURVEY_FROZEN", "已发布问卷不能替换题目。", status_code=409)
    if revision is not None and row["revision"] != revision:
        raise DomainError("REVISION_CONFLICT", "问卷已更新，请重新加载后比较。", status_code=409)
    return row


def preserve_references(db, survey, questions, session):
    by_id = {q["id"]: q for q in questions}
    kept = []
    for ref in survey.get("questionRefs", []):
        instance_id = ref["instanceId"]
        if instance_id not in by_id:
            db.question_usage.update_many({"surveyId": survey["_id"], "surveyDefinitionVersion": survey["definitionVersion"],
                                           "instanceId": instance_id}, {"$set": {"isCurrent": False}}, session=session)
            continue
        if library.content_hash(by_id[instance_id]) != ref["contentHash"]:
            raise DomainError("VERSION_REQUIRED", "关联题目内容不能覆盖旧版本，请在题库创建新版或派生后显式升级。",
                              [{"questionId": instance_id}], status_code=409)
        kept.append(deepcopy(ref))
    return kept


def update_survey(db, survey, questions, refs, now, session, max_bytes=512*1024, extra=None):
    normalized = validate_definition(questions, publishing=False)
    changes = {"questions": normalized, "questionRefs": refs, "updatedAt": now, **(extra or {})}
    combined = {**survey, **changes}
    # Preserve the original business-definition quota: additive server-only
    # bindings must not make previously valid legacy content uneditable.
    business = {key: value for key, value in combined.items() if key != "questionRefs"}
    if len(BSON.encode(business)) > max_bytes or len(BSON.encode(combined)) > 15*1024*1024:
        raise DomainError("DEFINITION_TOO_LARGE", "问卷内容超过资源上限。")
    updated = db.surveys.find_one_and_update({"_id": survey["_id"], "ownerId": survey["ownerId"], "status": "draft", "revision": survey["revision"]},
        {"$set": changes, "$inc": {"revision": 1}}, return_document=ReturnDocument.AFTER, session=session)
    if not updated:
        raise DomainError("REVISION_CONFLICT", "问卷已被另一个请求修改。", status_code=409)
    return updated


def select(db, user, survey_id, payload, now):
    own_survey(db, user, survey_id)

    def work(session):
        survey = own_survey(db, user, survey_id, session, revision=payload["revision"], draft=True)
        question, version = library.guard_version(db, user, payload["versionId"], session)
        instance_id = str(uuid4())
        snapshot = {"id": instance_id, **deepcopy(version["content"]), "jumpRules": []}
        ref = reference(question, version, instance_id)
        update_survey(db, survey, [*survey["questions"], snapshot], [*survey.get("questionRefs", []), ref], now, session)
        register_usage(db, survey, ref, now, session)
        return {"surveyId": survey["_id"], "instanceId": instance_id}

    library.idempotent(db, user["_id"], "select:"+str(survey_id), payload["requestKey"], payload, work)
    return own_survey(db, user, survey_id)


def save_instance(db, user, survey_id, payload, now):
    own_survey(db, user, survey_id)

    def work(session):
        survey = own_survey(db, user, survey_id, session, revision=payload["revision"], draft=True)
        item = next((q for q in survey["questions"] if q["id"] == payload["instanceId"]), None)
        if item is None:
            raise DomainError("NOT_FOUND", "问卷中的题目不存在。", status_code=404)
        old = next((r for r in survey.get("questionRefs", []) if r["instanceId"] == item["id"]), None)
        if old:
            return {"surveyId": survey["_id"], "questionId": old["questionId"]}
        question = library.new_question(db, user, item, now, session, formal=True)
        version = db.question_versions.find_one({"_id": question["latestVersionId"]}, session=session)
        ref = reference(question, version, item["id"])
        update_survey(db, survey, survey["questions"], [*survey.get("questionRefs", []), ref], now, session)
        register_usage(db, survey, ref, now, session)
        return {"surveyId": survey["_id"], "questionId": question["_id"]}

    library.idempotent(db, user["_id"], "save-instance:"+str(survey_id), payload["requestKey"], payload, work)
    return own_survey(db, user, survey_id)


def upgrade(db, user, survey_id, payload, now):
    own_survey(db, user, survey_id)

    def work(session):
        survey = own_survey(db, user, survey_id, session, revision=payload["revision"], draft=True)
        old_item = next((q for q in survey["questions"] if q["id"] == payload["instanceId"]), None)
        if old_item is None:
            raise DomainError("NOT_FOUND", "题目实例不存在。", status_code=404)
        question, version = library.guard_version(db, user, payload["versionId"], session)
        snapshot = {"id": old_item["id"], **deepcopy(version["content"]), "jumpRules": deepcopy(old_item.get("jumpRules", []))}
        questions = [snapshot if q["id"] == old_item["id"] else q for q in survey["questions"]]
        ref = reference(question, version, old_item["id"])
        refs = [r for r in survey.get("questionRefs", []) if r["instanceId"] != old_item["id"]] + [ref]
        update_survey(db, survey, questions, refs, now, session)
        register_usage(db, survey, ref, now, session)
        return {"surveyId": survey["_id"], "instanceId": old_item["id"]}

    library.idempotent(db, user["_id"], "upgrade:"+str(survey_id), payload["requestKey"], payload, work)
    return own_survey(db, user, survey_id)


def register_definition(db, survey, user, now, session, *, migration=False):
    """Only adds bindings; never normalizes or renumbers historical snapshots."""
    refs = deepcopy(survey.get("questionRefs", []))
    known = {r["instanceId"] for r in refs}
    for item in survey["questions"]:
        if item["id"] in known:
            ref = next(r for r in refs if r["instanceId"] == item["id"])
            if library.content_hash(item) != ref["contentHash"]:
                raise DomainError("VERSION_REQUIRED", "题目快照与其版本引用不一致。", status_code=409)
        else:
            key = f"{survey['_id']}:{survey['definitionVersion']}:{item['id']}"
            question = db.questions.find_one({"legacyOriginKey": key}, session=session)
            if question is None:
                question = library.new_question(db, user, item, now, session, formal=True, legacy_key=key if migration else None,
                                                 published=survey["status"] != "draft")
            # A legacy-origin registration is pinned to its initial edition;
            # later edits to the library item must never reinterpret old data.
            version = db.question_versions.find_one({"questionId": question["_id"], "versionNumber": 1}, session=session)
            if not version or version["contentHash"] != library.content_hash(item):
                raise DomainError("MIGRATION_INCOMPLETE", "旧题登记的初始版本与原快照不一致。", status_code=409)
            ref = reference(question, version, item["id"])
            refs.append(ref)
        register_usage(db, survey, ref, now, session, "migration" if migration else "publication")
    return refs


def mark_published(db, refs, now, session):
    for question_id in sorted({r["questionId"] for r in refs}, key=str):
        result = db.questions.update_one({"_id": question_id}, {"$set": {"hasPublishedUsage": True, "updatedAt": now}, "$inc": {"revision": 1}}, session=session)
        if result.matched_count != 1:
            raise DomainError("SOURCE_UNAVAILABLE", "题目来源记录缺失，无法发布。", status_code=409)


def derive_batch(db, user, payload, now):
    def work(session):
        copies, mappings = {}, []
        for source in payload["instances"]:
            survey_id = library.oid(source["surveyId"])
            survey = own_survey(db, user, survey_id, session)
            if survey["definitionVersion"] != source["definitionVersion"]:
                historical = db.survey_versions.find_one({"surveyId": survey_id, "definitionVersion": source["definitionVersion"]}, session=session)
                if historical is None:
                    raise DomainError("NOT_FOUND", "问卷历史版本不存在。", status_code=404)
                survey = {**historical, "_id": survey_id, "ownerId": user["_id"]}
            item = next((q for q in survey["questions"] if q["id"] == source["instanceId"]), None)
            if item is None:
                raise DomainError("NOT_FOUND", "本人问卷中没有该题目实例。", status_code=404)
            ref = next((r for r in survey.get("questionRefs", []) if r["instanceId"] == item["id"]), None)
            digest = library.content_hash(item)
            identity = (str(ref["questionVersionId"]) if ref else f"{survey_id}:{item['id']}", digest)
            if identity not in copies:
                copies[identity] = library.new_question(db, user, item, now, session, formal=True,
                    root_id=ref["rootQuestionId"] if ref else None, derived_from=ref["questionVersionId"] if ref else None)
            own = copies[identity]
            mappings.append({**source, "questionId": own["_id"], "questionVersionId": own["latestVersionId"]})
        return {"questionIds": [q["_id"] for q in copies.values()], "mappings": mappings}

    result = library.idempotent(db, user["_id"], "derive-snapshots", payload["requestKey"], payload, work)
    return {"questions": [library.question_dto(db, user, library.require_question(db, user, qid)) for qid in result["questionIds"]], "mappings": result["mappings"]}

"""Resumable stage-one binding migration; response BSON is never rewritten."""
from copy import deepcopy

from app.services import library_service as library
from app.services import question_reference_service as refs
from app.services.storage_adapters import DomainError


def migrate(db, now, *, apply=False):
    current = list(db.surveys.find({}).sort("_id", 1))
    owners = {row["_id"]: row["ownerId"] for row in current}
    entries = [("surveys", row["_id"], row) for row in current]
    entries += [("survey_versions", row["_id"], {**row, "_id": row["surveyId"], "ownerId": row.get("ownerId", owners.get(row["surveyId"]))})
                for row in db.survey_versions.find({}).sort("_id", 1)]
    known = {(row["_id"], row["definitionVersion"]) for _, _, row in entries}
    for pair in db.responses.aggregate([{"$group": {"_id": {"surveyId": "$surveyId", "version": "$surveyDefinitionVersion"}}}]):
        value = pair["_id"]
        if (value["surveyId"], value["version"]) not in known:
            raise DomainError("MIGRATION_INCOMPLETE", "存在缺失历史定义的答卷，迁移已停止。", status_code=409)
    missing = 0
    for _, _, row in entries:
        if row.get("ownerId") is None or db.users.find_one({"_id": row["ownerId"]}) is None:
            raise DomainError("MIGRATION_INCOMPLETE", "问卷所有者缺失，不能猜测归属。", status_code=409)
        ids = [q["id"] for q in row["questions"]]
        if len(set(ids)) != len(ids):
            raise DomainError("MIGRATION_INCOMPLETE", "旧问卷存在重复实例标识。", status_code=409)
        mapped = {r["instanceId"]: r for r in row.get("questionRefs", [])}
        for item in row["questions"]:
            digest = library.content_hash(item)
            if item["id"] in mapped:
                ref = mapped[item["id"]]
                version = db.question_versions.find_one({"_id": ref["questionVersionId"]})
                question = db.questions.find_one({"_id": ref["questionId"]})
                if (ref["contentHash"] != digest or not version or version["contentHash"] != digest
                        or version["questionId"] != ref["questionId"] or not question
                        or question["rootQuestionId"] != ref["rootQuestionId"]):
                    raise DomainError("MIGRATION_INCOMPLETE", "已有来源关联与内容不一致。", status_code=409)
            else:
                missing += 1
    report = {"dryRun": not apply, "definitions": len(entries), "instances": sum(len(r["questions"]) for _, _, r in entries),
              "wouldBind": missing, "bound": 0, "completedDefinitions": 0, "responseDocumentsModified": 0,
              "historyCoverage": "existing definitions at migration plus subsequently recorded usage"}
    if not apply:
        return report
    for collection, document_id, row in entries:
        expected = deepcopy(row)

        def work(session):
            stored = db[collection].find_one({"_id": document_id}, session=session)
            if not stored:
                raise DomainError("MIGRATION_INCOMPLETE", "迁移期间问卷被移除。", status_code=409)
            logical = {**stored, "_id": row["_id"], "ownerId": row["ownerId"]}
            if logical.get("questions") != expected["questions"] or logical.get("definitionVersion") != expected["definitionVersion"]:
                raise DomainError("REVISION_CONFLICT", "迁移期间定义发生变化，请停写后重新执行。", status_code=409)
            owner = db.users.find_one({"_id": logical["ownerId"]}, session=session)
            bound = refs.register_definition(db, logical, owner, now, session, migration=True)
            if logical["status"] != "draft":
                # Keep the marker stable on a repeated migration.
                for qid in sorted({r["questionId"] for r in bound}, key=str):
                    db.questions.update_one({"_id": qid, "hasPublishedUsage": False}, {"$set": {"hasPublishedUsage": True}, "$inc": {"revision": 1}}, session=session)
            db[collection].update_one({"_id": document_id}, {"$set": {"questionRefs": bound, "schemaVersion": 2}}, session=session)
            return max(0, len(bound) - len(logical.get("questionRefs", [])))

        report["bound"] += library.transaction(db, work)
        report["completedDefinitions"] += 1
    db.schema_migrations.update_one({"_id": "002_question_library"}, {"$setOnInsert": {"appliedAt": now}, "$set": {
        "status": "complete", "definitions": len(entries), "responseDocumentsModified": 0}}, upsert=True)
    return report

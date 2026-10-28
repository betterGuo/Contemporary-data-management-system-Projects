"""Additive MongoDB schemas for the library. No data migration on startup."""


def initialize_library(db):
    identifier = {"bsonType": "objectId"}
    integer = {"bsonType": ["int", "long"]}
    definitions = {
        "questions": ({"ownerId": identifier, "rootQuestionId": identifier, "workingContent": {"bsonType": "object"},
                       "visibility": {"enum": ["private", "public"]}, "status": {"enum": ["active", "archived"]},
                       "revision": integer, "latestVersionNumber": integer, "hasPublishedUsage": {"bsonType": "bool"}},
                      ["ownerId", "rootQuestionId", "workingContent", "visibility", "status", "revision", "latestVersionNumber", "hasPublishedUsage"]),
        "question_versions": ({"questionId": identifier, "versionNumber": integer, "content": {"bsonType": "object"},
                               "contentHash": {"bsonType": "string"}}, ["questionId", "versionNumber", "content", "contentHash"]),
        "question_version_state": ({"versionId": identifier, "selectable": {"bsonType": "bool"}, "revision": integer}, ["versionId", "selectable", "revision"]),
        "question_bookmarks": ({"userId": identifier, "questionId": identifier, "tags": {"bsonType": "array", "items": {"bsonType": "string"}}}, ["userId", "questionId", "tags"]),
        "question_grants": ({"questionId": identifier, "granteeId": identifier, "active": {"bsonType": "bool"}, "revision": integer}, ["questionId", "granteeId", "active", "revision"]),
        "question_usage": ({"surveyId": identifier, "surveyDefinitionVersion": integer, "instanceId": {"bsonType": "string"},
                            "questionId": identifier, "versionId": identifier, "rootQuestionId": identifier,
                            "surveyOwnerId": identifier, "isCurrent": {"bsonType": "bool"}},
                           ["surveyId", "surveyDefinitionVersion", "instanceId", "questionId", "versionId", "rootQuestionId", "surveyOwnerId", "isCurrent"]),
        "operation_receipts": ({"actorId": identifier, "operation": {"bsonType": "string"}, "requestKey": {"bsonType": "string"},
                                "payloadHash": {"bsonType": "string"}, "result": {"bsonType": "object"}}, ["actorId", "operation", "requestKey", "payloadHash", "result"]),
    }
    existing = set(db.list_collection_names())
    for name, (properties, required) in definitions.items():
        validator = {"$jsonSchema": {"bsonType": "object", "properties": properties, "required": required}}
        if name in existing:
            db.command("collMod", name, validator=validator, validationLevel="strict", validationAction="error")
        else:
            db.create_collection(name, validator=validator, validationLevel="strict", validationAction="error")
    db.questions.create_index([("ownerId", 1), ("status", 1), ("updatedAt", -1), ("_id", -1)], name="owner_library")
    db.questions.create_index([("visibility", 1), ("status", 1), ("updatedAt", -1)], name="public_library")
    db.questions.create_index("rootQuestionId", name="question_lineage")
    db.questions.create_index("legacyOriginKey", unique=True, partialFilterExpression={"legacyOriginKey": {"$type": "string"}}, name="legacy_origin_unique")
    db.questions.create_index("publicCode", unique=True, partialFilterExpression={"publicCode": {"$type": "string"}}, name="public_code_unique")
    db.question_versions.create_index([("questionId", 1), ("versionNumber", 1)], unique=True, name="question_version_unique")
    db.question_versions.create_index("derivedFromVersionId", name="direct_version_source")
    db.question_version_state.create_index("versionId", unique=True, name="version_state_unique")
    db.question_bookmarks.create_index([("userId", 1), ("questionId", 1)], unique=True, name="bookmark_unique")
    db.question_bookmarks.create_index([("userId", 1), ("tags", 1)], name="personal_tags")
    db.question_grants.create_index([("questionId", 1), ("granteeId", 1)], unique=True, name="grant_unique")
    db.question_grants.create_index([("granteeId", 1), ("active", 1)], name="received_grants")
    db.question_usage.create_index([("surveyId", 1), ("surveyDefinitionVersion", 1), ("instanceId", 1), ("versionId", 1)], unique=True, name="usage_unique")
    db.question_usage.create_index([("questionId", 1), ("surveyOwnerId", 1), ("surveyId", 1)], name="question_usage_counts")
    db.question_usage.create_index([("versionId", 1), ("surveyId", 1)], name="version_usage")
    db.surveys.create_index([("ownerId", 1), ("questionRefs.questionVersionId", 1)], name="owner_version_instances")
    db.surveys.create_index([("ownerId", 1), ("questionRefs.questionId", 1)], name="owner_question_instances")
    db.responses.create_index([("surveyId", 1), ("surveyDefinitionVersion", 1), ("submittedAt", 1), ("_id", 1)], name="definition_responses")
    db.operation_receipts.create_index([("actorId", 1), ("operation", 1), ("requestKey", 1)], unique=True, name="operation_idempotency")

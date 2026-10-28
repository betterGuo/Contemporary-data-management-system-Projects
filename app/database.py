from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient


def utcnow():
    return datetime.now(timezone.utc)


def connect(uri):
    return MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=3000)


def initialize_database(db):
    """Idempotent schema and index setup. Never drops collections or existing records."""
    definitions = {
        "users": {
            "required": ["username", "usernameNormalized", "passwordHash", "createdAt", "schemaVersion"],
            "properties": {
                "username": {"bsonType": "string"},
                "usernameNormalized": {"bsonType": "string"},
                "passwordHash": {"bsonType": "string"},
                "createdAt": {"bsonType": "date"},
                "schemaVersion": {"bsonType": "int"},
            },
        },
        "sessions": {
            "required": ["tokenHash", "csrfTokenHash", "userId", "createdAt", "expiresAt"],
            "properties": {
                "tokenHash": {"bsonType": "string"},
                "csrfTokenHash": {"bsonType": "string"},
                "userId": {"bsonType": "objectId"},
                "createdAt": {"bsonType": "date"},
                "expiresAt": {"bsonType": "date"},
            },
        },
        "surveys": {
            "required": ["ownerId", "publicId", "title", "status", "questions", "revision", "definitionVersion", "schemaVersion"],
            "properties": {
                "ownerId": {"bsonType": "objectId"},
                "publicId": {"bsonType": "string"},
                "title": {"bsonType": "string"},
                "status": {"enum": ["draft", "published", "closed"]},
                "questions": {"bsonType": "array"},
                "revision": {"bsonType": "int"},
                "definitionVersion": {"bsonType": "int"},
                "schemaVersion": {"bsonType": "int"},
                "closesAt": {"bsonType": ["date", "null"]},
            },
        },
        "responses": {
            "required": ["surveyId", "surveyDefinitionVersion", "respondentKey", "repeatMode", "submissionKey", "payloadHash", "visitedQuestionIds", "answers", "submittedAt", "admittedAt", "schemaVersion"],
            "properties": {
                "surveyId": {"bsonType": "objectId"},
                "surveyDefinitionVersion": {"bsonType": "int"},
                "respondentKey": {"bsonType": "string"},
                "repeatMode": {"enum": ["single", "multiple"]},
                "submissionKey": {"bsonType": "string"},
                "payloadHash": {"bsonType": "string"},
                "answers": {"bsonType": "array"},
                "visitedQuestionIds": {"bsonType": "array"},
                "submittedAt": {"bsonType": "date"},
                "admittedAt": {"bsonType": "date"},
                "schemaVersion": {"bsonType": "int"},
            },
        },
    }
    existing = set(db.list_collection_names())
    for name, schema in definitions.items():
        validator = {"$jsonSchema": {"bsonType": "object", **schema}}
        if name in existing:
            db.command("collMod", name, validator=validator, validationLevel="strict", validationAction="error")
        else:
            db.create_collection(name, validator=validator, validationLevel="strict", validationAction="error")
    db.users.create_index("usernameNormalized", unique=True, name="username_unique")
    db.sessions.create_index("tokenHash", unique=True, name="session_token_unique")
    db.sessions.create_index("expiresAt", expireAfterSeconds=0, name="session_expiry")
    db.surveys.create_index("publicId", unique=True, name="public_id_unique")
    db.surveys.create_index([("ownerId", ASCENDING), ("createdAt", DESCENDING), ("_id", DESCENDING)], name="owner_recent")
    db.responses.create_index([("surveyId", ASCENDING), ("submittedAt", ASCENDING), ("_id", ASCENDING)], name="survey_responses")
    db.responses.create_index([("surveyId", 1), ("respondentKey", 1), ("submissionKey", 1)], unique=True, name="submission_idempotency")
    db.responses.create_index([("surveyId", 1), ("respondentKey", 1)], unique=True, partialFilterExpression={"repeatMode": "single"}, name="single_response_per_user")
    db.schema_migrations.update_one({"_id": "001_initial"}, {"$setOnInsert": {"appliedAt": utcnow(), "description": "Four business collections, validators and indexes"}}, upsert=True)
    from app.library_database import initialize_library
    initialize_library(db)

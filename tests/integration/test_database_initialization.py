"""Initialization safety checks against generated, disposable MongoDB databases."""

from bson import BSON
from pymongo.errors import OperationFailure
import pytest

from app.database import initialize_database, utcnow


def documents(collection):
    return [BSON.encode(document) for document in collection.find().sort("_id", 1)]


def database_snapshot(db):
    return {
        entry["name"]: {
            "uuid": entry["info"]["uuid"],
            "options": entry["options"],
            "indexes": db[entry["name"]].index_information(),
            "documents": documents(db[entry["name"]]),
        }
        for entry in db.list_collections()
    }


def existing_user():
    return {
        "username": "ExistingUser",
        "usernameNormalized": "existinguser",
        "passwordHash": "test-only-placeholder",
        "createdAt": utcnow(),
        "schemaVersion": 1,
    }


def test_repeated_initialization_preserves_documents_and_metadata(
    api_factory, survey_factory, submit_response, real_db,
):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner)
    assert submit_response(participant, survey).status_code == 201
    # An unrelated collection must survive too. Sessions are still unexpired;
    # normal TTL deletion of expired sessions is not initialization data loss.
    real_db.unrelated_notes.insert_one({"_id": "keep", "message": "preserve"})
    before = database_snapshot(real_db)
    assert all(before[name]["documents"] for name in (
        "users", "sessions", "surveys", "responses", "schema_migrations",
    ))

    for _ in range(2):
        initialize_database(real_db)
        # Includes exact BSON, collection identity, validators, indexes and the
        # migration timestamp; a destructive drop/recreate cannot pass this.
        assert database_snapshot(real_db) == before


def test_existing_duplicate_keys_fail_without_deleting_documents(real_db):
    real_db.users.insert_many([existing_user(), existing_user()])
    before = documents(real_db.users)

    with pytest.raises(OperationFailure) as error:
        initialize_database(real_db)

    assert error.value.code == 11000
    assert documents(real_db.users) == before
    assert real_db.schema_migrations.find_one({"_id": "001_initial"}) is None
    # Earlier collection/validator changes may already have succeeded: this
    # initializer is intentionally not claimed to be an atomic transaction.


def test_conflicting_index_fails_without_replacing_index_or_documents(real_db):
    real_db.users.insert_one(existing_user())
    real_db.users.create_index("usernameNormalized", name="username_unique")
    before_documents = documents(real_db.users)
    before_indexes = real_db.users.index_information()

    with pytest.raises(OperationFailure) as error:
        initialize_database(real_db)

    assert error.value.code in {85, 86}
    assert documents(real_db.users) == before_documents
    assert real_db.users.index_information() == before_indexes
    assert real_db.schema_migrations.find_one({"_id": "001_initial"}) is None

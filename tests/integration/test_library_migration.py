"""Old definitions gain source identities without rewriting old responses."""
from copy import deepcopy
from uuid import uuid4

from bson import BSON, ObjectId
import pytest

from app.database import utcnow
from app.services import library_migration, library_service
from app.services.storage_adapters import DomainError
from scripts.backup_project import manifest


pytestmark = pytest.mark.integration
LIBRARY_COLLECTIONS = ("questions", "question_versions", "question_version_state", "question_bookmarks", "question_grants", "question_usage", "operation_receipts")


def legacy_fixture(real_db, api_factory, survey_factory, submit_response, *, surveys=1):
    owner = api_factory()
    records = []
    for _ in range(surveys):
        survey = survey_factory(owner)
        assert submit_response(owner, survey).status_code == 201
        records.append(survey)
    assert real_db.name.startswith("survey_project1_test_")
    real_db.surveys.update_many({}, {"$unset": {"questionRefs": ""}, "$set": {"schemaVersion": 1}})
    for name in LIBRARY_COLLECTIONS:
        real_db[name].delete_many({})
    real_db.schema_migrations.delete_one({"_id": "002_question_library"})
    return owner, records


@pytest.mark.case("S2-37", "S2-38", "S2-39", "S2-40", "S2-43")
def test_dry_run_then_repeat_apply_preserves_answers_and_content(real_db, api_factory, survey_factory, submit_response):
    owner, records = legacy_fixture(real_db, api_factory, survey_factory, submit_response)
    before = manifest(real_db)
    response_bytes = [BSON.encode(row) for row in real_db.responses.find().sort("_id", 1)]
    old = real_db.surveys.find_one({"_id": ObjectId(records[0]["id"])})
    original_submission = real_db.responses.find_one({"surveyId": old["_id"]})
    original_request = {
        "definitionVersion": original_submission["surveyDefinitionVersion"],
        "submissionKey": original_submission["submissionKey"], "isAnonymous": original_submission["isAnonymous"],
        "answers": [{"questionId": answer["questionId"], "value": answer["value"]} for answer in original_submission["answers"]],
    }
    preview = library_migration.migrate(real_db, utcnow())
    assert preview["dryRun"] and preview["wouldBind"] == 1
    assert manifest(real_db) == before
    first = library_migration.migrate(real_db, utcnow(), apply=True)
    assert first["bound"] == 1 and first["responseDocumentsModified"] == 0
    current = real_db.surveys.find_one({"_id": old["_id"]})
    preserved = {key: value for key, value in current.items() if key not in {"questionRefs", "schemaVersion"}}
    assert preserved == {key: value for key, value in old.items() if key != "schemaVersion"}
    assert current["questionRefs"][0]["instanceId"] == old["questions"][0]["id"]
    assert [BSON.encode(row) for row in real_db.responses.find().sort("_id", 1)] == response_bytes
    q = real_db.questions.find_one({"_id": current["questionRefs"][0]["questionId"]})
    assert q["hasPublishedUsage"]
    replay = owner.write("POST", f"/api/participation/{old['publicId']}/responses", original_request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] and replay.json()["response"]["id"] == str(original_submission["_id"])
    assert real_db.responses.count_documents({"surveyId": old["_id"]}) == 1
    assert [BSON.encode(row) for row in real_db.responses.find().sort("_id", 1)] == response_bytes
    after = manifest(real_db)
    second = library_migration.migrate(real_db, utcnow(), apply=True)
    assert second["wouldBind"] == second["bound"] == 0
    assert manifest(real_db) == after
    assert owner.get(f"/api/surveys/{records[0]['id']}/statistics").json()["statistics"]["submissionCount"] == 1


@pytest.mark.case("S2-38", "S2-41")
def test_missing_historical_definition_stops_before_any_migration_write(real_db, api_factory, survey_factory, submit_response):
    legacy_fixture(real_db, api_factory, survey_factory, submit_response)
    real_db.responses.update_one({}, {"$set": {"surveyDefinitionVersion": 2}})
    before = manifest(real_db)
    for apply in (False, True):
        with pytest.raises(DomainError) as error:
            library_migration.migrate(real_db, utcnow(), apply=apply)
        assert error.value.code == "MIGRATION_INCOMPLETE"
        assert manifest(real_db) == before


@pytest.mark.case("S2-38", "S2-61")
def test_current_and_historical_definitions_get_distinct_exact_mappings(real_db, api_factory, survey_factory, submit_response):
    _, records = legacy_fixture(real_db, api_factory, survey_factory, submit_response)
    current = real_db.surveys.find_one({"_id": ObjectId(records[0]["id"])})
    historical = deepcopy(current)
    historical.update({"_id": ObjectId(), "surveyId": current["_id"], "definitionVersion": 2})
    real_db.survey_versions.insert_one(historical)
    real_db.responses.update_one({}, {"$set": {"surveyDefinitionVersion": 2}})
    response_bytes = [BSON.encode(row) for row in real_db.responses.find()]
    result = library_migration.migrate(real_db, utcnow(), apply=True)
    assert result["definitions"] == result["bound"] == 2
    now_current = real_db.surveys.find_one({"_id": current["_id"]})
    now_historical = real_db.survey_versions.find_one({"_id": historical["_id"]})
    current_ref, history_ref = now_current["questionRefs"][0], now_historical["questionRefs"][0]
    assert current_ref["instanceId"] == history_ref["instanceId"]
    assert current_ref["questionVersionId"] != history_ref["questionVersionId"]
    assert current_ref["rootQuestionId"] != history_ref["rootQuestionId"]
    assert [BSON.encode(row) for row in real_db.responses.find()] == response_bytes


@pytest.mark.case("S2-40")
def test_interrupted_migration_resumes_without_duplicate_sources(real_db, api_factory, survey_factory, submit_response, monkeypatch):
    legacy_fixture(real_db, api_factory, survey_factory, submit_response, surveys=2)
    original = library_service.transaction
    calls = {"count": 0}

    def interrupt_second(db, work):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("intentional-migration-interruption")
        return original(db, work)

    monkeypatch.setattr(library_service, "transaction", interrupt_second)
    with pytest.raises(RuntimeError, match="intentional-migration-interruption"):
        library_migration.migrate(real_db, utcnow(), apply=True)
    assert real_db.questions.count_documents({}) == 1
    assert real_db.schema_migrations.find_one({"_id": "002_question_library"}) is None
    monkeypatch.setattr(library_service, "transaction", original)
    resumed = library_migration.migrate(real_db, utcnow(), apply=True)
    assert resumed["bound"] == 1 and resumed["wouldBind"] == 1
    assert real_db.questions.count_documents({}) == 2
    assert real_db.question_usage.count_documents({}) == 2


def test_same_content_from_different_question_cannot_fake_a_mapping(real_db, api_factory, survey_factory, submit_response):
    owner, records = legacy_fixture(real_db, api_factory, survey_factory, submit_response)
    library_migration.migrate(real_db, utcnow(), apply=True)
    survey_id = ObjectId(records[0]["id"])
    survey = real_db.surveys.find_one({"_id": survey_id})
    original_ref = survey["questionRefs"][0]
    original_version = real_db.question_versions.find_one({"_id": original_ref["questionVersionId"]})
    other = owner.write("POST", "/api/library-questions", {"content": original_version["content"], "requestKey": str(uuid4())}).json()["question"]
    other_version = owner.write("POST", f"/api/library-questions/{other['id']}/versions", {"revision": other["revision"], "sourceVersionId": None, "content": original_version["content"], "requestKey": str(uuid4())}).json()["version"]
    # Content hashes agree, but the identity belongs to a different question.
    fake = deepcopy(original_ref)
    fake["questionVersionId"] = ObjectId(other_version["id"])
    real_db.surveys.update_one({"_id": survey_id}, {"$set": {"questionRefs": [fake]}})
    before = manifest(real_db)
    with pytest.raises(DomainError) as error:
        library_migration.migrate(real_db, utcnow(), apply=True)
    assert error.value.code == "MIGRATION_INCOMPLETE"
    assert manifest(real_db) == before


def test_missing_legacy_reference_rebinds_original_v1_after_later_revision(real_db, api_factory, survey_factory, submit_response):
    owner, records = legacy_fixture(real_db, api_factory, survey_factory, submit_response)
    library_migration.migrate(real_db, utcnow(), apply=True)
    survey_id = ObjectId(records[0]["id"])
    survey = real_db.surveys.find_one({"_id": survey_id})
    original_ref = survey["questionRefs"][0]
    q = real_db.questions.find_one({"_id": original_ref["questionId"]})
    revised = deepcopy(q["workingContent"]); revised["title"] = "后来修订的标题"
    response = owner.write("POST", f"/api/library-questions/{q['_id']}/versions", {"revision": q["revision"], "sourceVersionId": str(original_ref["questionVersionId"]), "content": revised, "requestKey": str(uuid4())})
    assert response.status_code == 201, response.text
    later_id = ObjectId(response.json()["version"]["id"])
    real_db.surveys.update_one({"_id": survey_id}, {"$unset": {"questionRefs": ""}})
    answers = [BSON.encode(row) for row in real_db.responses.find()]
    result = library_migration.migrate(real_db, utcnow(), apply=True)
    assert result["bound"] == 1
    rebound = real_db.surveys.find_one({"_id": survey_id})["questionRefs"][0]
    assert rebound["questionId"] == original_ref["questionId"]
    assert rebound["questionVersionId"] == original_ref["questionVersionId"] != later_id
    assert real_db.questions.find_one({"_id": q["_id"]})["latestVersionId"] == later_id
    assert [BSON.encode(row) for row in real_db.responses.find()] == answers

"""Final acceptance boundaries on real databases, never the original data."""
from copy import deepcopy
from uuid import uuid4

from bson import BSON, ObjectId
from pymongo import MongoClient
import pytest

from app.database import utcnow
from app.services import library_migration, library_service as library
from app.services.storage_adapters import DomainError


pytestmark = pytest.mark.integration


def number(title="数字", maximum="120"):
    return {"type": "number", "title": title, "required": True, "options": [],
            "validation": {"integerOnly": True, "minValue": "0", "maxValue": maximum}}


def create(api, value):
    response = api.write("POST", "/api/library-questions", {"content": value, "requestKey": str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()["question"]


def formal(api, question, value):
    response = api.write("POST", f"/api/library-questions/{question['id']}/versions", {
        "revision": question["revision"], "sourceVersionId": question["latestVersionId"],
        "content": value, "requestKey": str(uuid4()),
    })
    assert response.status_code == 201, response.text
    return response.json()["question"], response.json()["version"]


def pick(api, survey, version_id):
    response = api.write("POST", f"/api/surveys/{survey['id']}/library-instances", {
        "revision": survey["revision"], "versionId": version_id, "requestKey": str(uuid4()),
    })
    assert response.status_code == 201, response.text
    return response.json()["survey"]


def publish(api, survey):
    response = api.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert response.status_code == 200, response.text
    return response.json()["survey"]


def statistics(api, question_id, version_id, **parameters):
    response = api.get(f"/api/library-questions/{question_id}/statistics", params={"versionId": version_id, **parameters})
    assert response.status_code == 200, response.text
    return response.json()["statistics"]


@pytest.mark.case("S2-13")
def test_upgrade_removing_rule_option_is_atomic_and_preserves_usage(
    api_factory, survey_factory, real_db,
):
    author = api_factory()
    first_content = {"type": "single", "title": "选择", "required": True,
                     "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], "validation": {}}
    question, v1 = formal(author, create(author, first_content), first_content)
    survey = pick(author, survey_factory(author, questions=[], publish=False), v1["id"])
    instance = survey["questions"][0]["id"]
    items = deepcopy(survey["questions"])
    items[0]["jumpRules"] = [{"id": "choose-b-end", "operator": "eq", "value": "b", "targetQuestionId": "END"}]
    patched = author.write("PATCH", f"/api/surveys/{survey['id']}", {"revision": survey["revision"], "questions": items})
    assert patched.status_code == 200, patched.text
    survey = patched.json()["survey"]
    revised = deepcopy(first_content)
    revised["options"] = [revised["options"][0]]
    question, v2 = formal(author, question, revised)
    survey_id = ObjectId(survey["id"])
    before_survey = BSON.encode(real_db.surveys.find_one({"_id": survey_id}))
    before_usage = [BSON.encode(row) for row in real_db.question_usage.find({"surveyId": survey_id}).sort("_id", 1)]
    before_question = BSON.encode(real_db.questions.find_one({"_id": ObjectId(question["id"])}))
    key = str(uuid4())
    failed = author.write("POST", f"/api/surveys/{survey['id']}/library-instances/upgrade", {
        "revision": survey["revision"], "instanceId": instance, "versionId": v2["id"], "requestKey": key,
    })
    assert failed.status_code == 422, failed.text
    assert BSON.encode(real_db.surveys.find_one({"_id": survey_id})) == before_survey
    assert [BSON.encode(row) for row in real_db.question_usage.find({"surveyId": survey_id}).sort("_id", 1)] == before_usage
    assert BSON.encode(real_db.questions.find_one({"_id": ObjectId(question["id"])})) == before_question
    assert real_db.operation_receipts.find_one({"requestKey": key}) is None


@pytest.mark.case("S2-69")
def test_mixed_v1_v3_usage_and_highest_version_down_do_not_hide_v1_update(
    api_factory, survey_factory, real_db,
):
    author = api_factory()
    question, v1 = formal(author, create(author, number()), number())
    question, v2 = formal(author, question, number(maximum="100"))
    question, v3 = formal(author, question, number(maximum="80"))
    a = pick(author, survey_factory(author, questions=[], publish=False), v1["id"])
    b = pick(author, survey_factory(author, questions=[], publish=False), v3["id"])
    ids = [ObjectId(a["id"]), ObjectId(b["id"])]
    before = {sid: BSON.encode(real_db.surveys.find_one({"_id": sid})) for sid in ids}
    bookmarked = author.write("POST", "/api/question-bookmarks", {"questionId": question["id"], "versionId": v1["id"], "tags": []})
    assert bookmarked.status_code == 200
    dto = bookmarked.json()["question"]
    assert dto["latestSelectableVersionId"] == v3["id"] and dto["hasUpdate"]
    down = author.write("POST", f"/api/library-questions/{question['id']}/versions/{v3['id']}/availability", {
        "revision": v3["revision"], "selectable": False,
    })
    assert down.status_code == 200, down.text
    dto = author.get(f"/api/library-questions/{question['id']}").json()["question"]
    assert dto["latestVersionNumber"] == 3
    assert dto["latestSelectableVersionId"] == v2["id"] and dto["latestSelectableVersionNumber"] == 2
    assert dto["selectedVersionId"] == v1["id"] and dto["hasUpdate"]
    for sid in ids:
        assert BSON.encode(real_db.surveys.find_one({"_id": sid})) == before[sid]
    assert a["questionRefs"][0]["questionVersionId"] == v1["id"]
    assert b["questionRefs"][0]["questionVersionId"] == v3["id"]


@pytest.mark.case("S2-44")
def test_migrated_old_answer_and_new_reuse_join_the_same_exact_version(
    api_factory, survey_factory, submit_response, real_db,
):
    author = api_factory()
    original = survey_factory(author, questions=[{"id": "old-age", **number()}], allowMultipleSubmissions=True)
    assert submit_response(author, original, {"old-age": "10"}).status_code == 201
    old_response = real_db.responses.find_one({"surveyId": ObjectId(original["id"])})
    old_bytes = BSON.encode(old_response)
    # Create a genuine stage-one-shaped fixture in this generated test database.
    real_db.surveys.update_many({}, {"$unset": {"questionRefs": ""}, "$set": {"schemaVersion": 1}})
    for name in ("questions", "question_versions", "question_version_state", "question_bookmarks", "question_grants", "question_usage", "operation_receipts"):
        real_db[name].delete_many({})
    migrated = library_migration.migrate(real_db, utcnow(), apply=True)
    assert migrated["bound"] == 1
    legacy = real_db.surveys.find_one({"_id": ObjectId(original["id"])})
    ref = legacy["questionRefs"][0]
    new = survey_factory(author, questions=[], publish=False, allowMultipleSubmissions=True)
    new = publish(author, pick(author, new, str(ref["questionVersionId"])))
    assert submit_response(author, new, {new["questions"][0]["id"]: "30"}).status_code == 201
    result = statistics(author, str(ref["questionId"]), str(ref["questionVersionId"]))
    assert result["answerCount"] == result["responseCount"] == result["surveyCount"] == 2
    assert result["average"] == "20"
    assert result["distribution"] == [{"value": "10", "count": 1}, {"value": "30", "count": 1}]
    assert BSON.encode(real_db.responses.find_one({"_id": old_response["_id"]})) == old_bytes


@pytest.mark.case("S2-62")
def test_unanswered_version_has_zero_counts_null_range_and_empty_groups(api_factory):
    author = api_factory()
    question, version = formal(author, create(author, number()), number())
    result = statistics(author, question["id"], version["id"])
    assert result["answerCount"] == result["responseCount"] == result["surveyCount"] == result["distinctValueCount"] == 0
    assert result["average"] is result["min"] is result["max"] is None
    assert result["options"] == result["distribution"] == result["bySurvey"] == []
    assert "respondentCount" not in result


@pytest.mark.case("S2-52")
def test_numeric_frequency_pages_are_numeric_sorted_and_do_not_change_totals(
    api_factory, survey_factory, submit_response,
):
    author = api_factory()
    question, version = formal(author, create(author, number()), number())
    survey = publish(author, pick(author, survey_factory(author, questions=[], publish=False, allowMultipleSubmissions=True), version["id"]))
    instance = survey["questions"][0]["id"]
    for value in ("2", "10", "2", "0"):
        assert submit_response(author, survey, {instance: value}).status_code == 201
    first = statistics(author, question["id"], version["id"], page=1, pageSize=2)
    second = statistics(author, question["id"], version["id"], page=2, pageSize=2)
    empty = statistics(author, question["id"], version["id"], page=3, pageSize=2)
    assert first["distribution"] == [{"value": "0", "count": 1}, {"value": "2", "count": 2}]
    assert second["distribution"] == [{"value": "10", "count": 1}] and empty["distribution"] == []
    for result in (first, second, empty):
        assert result["answerCount"] == result["responseCount"] == 4
        assert result["distinctValueCount"] == 3 and result["average"] == "3.5"


@pytest.mark.case("S2-30")
def test_exception_after_version_and_state_insert_rolls_back_every_write(
    api_factory, real_db, monkeypatch,
):
    author = api_factory()
    question = create(author, number())
    actor = real_db.users.find_one({"_id": ObjectId(author.user["id"])})
    qid = ObjectId(question["id"])
    before = BSON.encode(real_db.questions.find_one({"_id": qid}))
    original_insert = library._insert_version
    inserted = []

    def insert_then_fail(db, *args, **kwargs):
        row = original_insert(db, *args, **kwargs)
        session = kwargs.get("session") or args[6]
        assert db.question_versions.find_one({"_id": row["_id"]}, session=session)
        assert db.question_version_state.find_one({"versionId": row["_id"]}, session=session)
        inserted.append(row["_id"])
        raise RuntimeError("intentional-after-real-version-insert")

    monkeypatch.setattr(library, "_insert_version", insert_then_fail)
    key = str(uuid4())
    with pytest.raises(RuntimeError, match="intentional-after-real-version-insert"):
        library.save_version(real_db, actor, question["id"], {
            "revision": question["revision"], "sourceVersionId": None,
            "content": number(), "requestKey": key,
        }, utcnow())
    assert len(inserted) == 1
    assert BSON.encode(real_db.questions.find_one({"_id": qid})) == before
    assert real_db.question_versions.find_one({"_id": inserted[0]}) is None
    assert real_db.question_version_state.find_one({"versionId": inserted[0]}) is None
    assert real_db.operation_receipts.find_one({"requestKey": key}) is None


@pytest.mark.case("S2-36")
def test_standalone_rejects_transaction_without_calling_the_write_callback():
    # This fixed URI is the existing standalone server, but the only data
    # namespace accessed is this fresh, strictly generated disposable database.
    name = "survey_project1_test_standalone_" + uuid4().hex[:24]
    assert name.startswith("survey_project1_test_standalone_")
    assert len(name.encode()) <= 63
    assert name != "survey_project1"
    with MongoClient("mongodb://localhost:27017/", tz_aware=True, serverSelectionTimeoutMS=2500) as client:
        assert not client.admin.command("hello").get("setName")
        db = client[name]
        called = []
        try:
            db.marker.insert_one({"_id": "baseline", "value": "preserve"})

            def write(session):
                called.append(True)
                db.marker.insert_one({"_id": "must-not-run"}, session=session)

            with pytest.raises(DomainError) as error:
                library.transaction(db, write)
            assert error.value.code == "TRANSACTIONS_REQUIRED" and error.value.status_code == 503
            assert called == []
            assert list(db.marker.find()) == [{"_id": "baseline", "value": "preserve"}]
        finally:
            assert db.name == name and name.startswith("survey_project1_test_standalone_")
            client.drop_database(name)


@pytest.mark.case("S2-04")
def test_unchanged_ordinary_working_save_keeps_revision_and_content_version(
    api_factory, real_db,
):
    author = api_factory()
    question, version = formal(author, create(author, number()), number())
    before = BSON.encode(real_db.questions.find_one({"_id": ObjectId(question["id"])}))
    result = author.write("POST", f"/api/library-questions/{question['id']}/working-content", {
        "revision": question["revision"], "content": question["workingContent"],
    })
    assert result.status_code == 200, result.text
    unchanged = result.json()["question"]
    assert unchanged["revision"] == question["revision"]
    assert unchanged["latestVersionId"] == version["id"] and unchanged["latestVersionNumber"] == 1
    assert BSON.encode(real_db.questions.find_one({"_id": ObjectId(question["id"])})) == before
    assert real_db.question_versions.count_documents({"questionId": ObjectId(question["id"])}) == 1


@pytest.mark.case("S2-26")
def test_search_is_literal_and_invalid_or_missing_ids_are_structured(api_factory):
    author = api_factory()
    create(author, number("年龄"))
    create(author, number("其他题目"))
    literal = create(author, number("标记 .* 样例"))
    result = author.get("/api/library-questions", params={"scope": "mine", "q": ".*"})
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert [q["id"] for q in result.json()["questions"]] == [literal["id"]]
    bad = author.get("/api/library-questions/not-an-object-id")
    absent = author.get(f"/api/library-questions/{ObjectId()}")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_ID"
    assert absent.status_code == 404 and absent.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.case("S2-71")
def test_five_item_batch_with_last_foreign_instance_rolls_back_earlier_copies(
    api_factory, survey_factory, real_db,
):
    author, other = api_factory(), api_factory()
    own = [survey_factory(author, publish=False) for _ in range(4)]
    foreign = survey_factory(other, publish=False)
    payload = {"instances": [{"surveyId": survey["id"], "definitionVersion": survey["definitionVersion"],
                              "instanceId": survey["questions"][0]["id"]} for survey in [*own, foreign]],
               "requestKey": str(uuid4())}
    names = ("questions", "question_versions", "question_version_state", "question_bookmarks", "operation_receipts")
    before = {name: [BSON.encode(row) for row in real_db[name].find().sort("_id", 1)] for name in names}
    result = author.write("POST", "/api/library-questions/derive-batch", payload)
    assert result.status_code == 404, result.text
    assert result.json()["error"]["code"] == "NOT_FOUND"
    assert {name: [BSON.encode(row) for row in real_db[name].find().sort("_id", 1)] for name in names} == before
    assert real_db.operation_receipts.find_one({"requestKey": payload["requestKey"]}) is None

"""Library bindings keep existing survey instances and submissions intact."""
from copy import deepcopy
from uuid import uuid4

from bson import BSON, ObjectId
import pytest


pytestmark = pytest.mark.integration


def content(maximum="120"):
    return {"type": "number", "title": "年龄", "required": True, "options": [], "validation": {"minValue": "0", "maxValue": maximum, "integerOnly": True}}


def question(api):
    created = api.write("POST", "/api/library-questions", {"content": content(), "requestKey": str(uuid4())})
    assert created.status_code == 201, created.text
    q = created.json()["question"]
    saved = api.write("POST", f"/api/library-questions/{q['id']}/versions", {"revision": q["revision"], "sourceVersionId": None, "content": content(), "requestKey": str(uuid4())})
    assert saved.status_code == 201, saved.text
    return saved.json()["question"], saved.json()["version"]


def draft(api):
    response = api.write("POST", "/api/surveys", {"title": "题库复用问卷", "allowMultipleSubmissions": True})
    assert response.status_code == 201
    return response.json()["survey"]


def select(api, survey, version_id, key=None):
    payload = {"revision": survey["revision"], "versionId": version_id, "requestKey": key or str(uuid4())}
    response = api.write("POST", f"/api/surveys/{survey['id']}/library-instances", payload)
    assert response.status_code == 201, response.text
    return response.json()["survey"], payload


@pytest.mark.case("S2-07", "S2-08", "S2-11", "S2-76")
def test_repeated_instances_publish_freeze_and_old_answers(api_factory, submit_response, real_db):
    author = api_factory(); q, v1 = question(author)
    survey, _ = select(author, draft(author), v1["id"])
    survey, _ = select(author, survey, v1["id"])
    first_id, second_id = [item["id"] for item in survey["questions"]]
    assert first_id != second_id
    assert {ref["questionVersionId"] for ref in survey["questionRefs"]} == {v1["id"]}
    published = author.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert published.status_code == 200, published.text
    survey = published.json()["survey"]
    assert submit_response(author, survey, {first_id: "10", second_id: "30"}).status_code == 201
    raw_before = BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])}))
    answers_before = [BSON.encode(row) for row in real_db.responses.find({"surveyId": ObjectId(survey["id"])})]
    q = author.get(f"/api/library-questions/{q['id']}").json()["question"]
    assert q["hasPublishedUsage"]
    assert author.write("POST", f"/api/library-questions/{q['id']}/working-content", {"revision": q["revision"], "content": content("200")}).status_code == 409
    v2 = author.write("POST", f"/api/library-questions/{q['id']}/versions", {"revision": q["revision"], "sourceVersionId": v1["id"], "content": content("200"), "requestKey": str(uuid4())})
    assert v2.status_code == 201
    assert BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])})) == raw_before
    assert [BSON.encode(row) for row in real_db.responses.find({"surveyId": ObjectId(survey["id"])})] == answers_before
    stats = author.get(f"/api/surveys/{survey['id']}/statistics").json()["statistics"]
    assert [row["average"] for row in stats["questions"]] == ["10", "30"]


@pytest.mark.case("S2-10", "S2-14", "S2-15")
def test_existing_full_patch_cannot_forge_source_content(api_factory, real_db):
    author = api_factory(); q, version = question(author)
    survey, _ = select(author, draft(author), version["id"])
    before = BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])}))
    changed = deepcopy(survey["questions"]); changed[0]["title"] = "伪造的新版标题"
    bad = author.write("PATCH", f"/api/surveys/{survey['id']}", {"revision": survey["revision"], "questions": changed})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "VERSION_REQUIRED"
    assert BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])})) == before
    fake = author.write("PATCH", f"/api/surveys/{survey['id']}", {"revision": survey["revision"], "questionRefs": []})
    assert fake.status_code == 422
    one = author.write("PATCH", f"/api/surveys/{survey['id']}/questions/{survey['questions'][0]['id']}", {"revision": survey["revision"], "question": changed[0]})
    assert one.status_code == 409


@pytest.mark.case("S2-12", "S2-15", "S2-25", "S2-27", "S2-67")
def test_explicit_upgrade_and_removal_keep_historical_usage(api_factory, real_db):
    author = api_factory(); q, first = question(author)
    survey, payload = select(author, draft(author), first["id"])
    replay = author.write("POST", f"/api/surveys/{survey['id']}/library-instances", payload)
    assert replay.status_code == 201 and len(replay.json()["survey"]["questions"]) == 1
    instance_id = survey["questions"][0]["id"]
    second = author.write("POST", f"/api/library-questions/{q['id']}/versions", {"revision": q["revision"], "sourceVersionId": first["id"], "content": content("80"), "requestKey": str(uuid4())}).json()["version"]
    unchanged = author.get(f"/api/surveys/{survey['id']}").json()["survey"]
    assert unchanged["questions"][0]["validation"]["maxValue"] == "120"
    upgraded = author.write("POST", f"/api/surveys/{survey['id']}/library-instances/upgrade", {"revision": survey["revision"], "instanceId": instance_id, "versionId": second["id"], "requestKey": str(uuid4())})
    assert upgraded.status_code == 200, upgraded.text
    survey = upgraded.json()["survey"]
    assert survey["questions"][0]["id"] == instance_id and survey["questions"][0]["validation"]["maxValue"] == "80"
    usage = list(real_db.question_usage.find({"surveyId": ObjectId(survey["id"])}))
    assert len(usage) == 2 and sum(row["isCurrent"] for row in usage) == 1
    removed = author.write("DELETE", f"/api/surveys/{survey['id']}/questions/{instance_id}", {"revision": survey["revision"]})
    assert removed.status_code == 200
    assert removed.json()["survey"]["questionRefs"] == []
    assert real_db.question_usage.count_documents({"surveyId": ObjectId(survey["id"]), "isCurrent": True}) == 0
    assert real_db.question_usage.count_documents({"surveyId": ObjectId(survey["id"])}) == 2


@pytest.mark.case("S2-19", "S2-20", "S2-67", "S2-70", "S2-71")
def test_revoked_source_can_be_batch_derived_from_owned_snapshots(api_factory, real_db):
    a, b, c = api_factory(), api_factory(), api_factory()
    q, version = question(a)
    grant = a.write("POST", f"/api/library-questions/{q['id']}/grants", {"revision": q["revision"], "username": b.user["username"]})
    assert grant.status_code == 200
    survey, _ = select(b, draft(b), version["id"])
    survey, _ = select(b, survey, version["id"])
    before = BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])}))
    usage_a = a.get(f"/api/library-questions/{q['id']}/usage").json()["usage"]
    assert usage_a["otherSurveyCount"] == 1 and usage_a["surveys"] == []
    usage_b = b.get(f"/api/library-questions/{q['id']}/usage").json()["usage"]
    assert "otherSurveyCount" not in usage_b and usage_b["surveys"][0]["id"] == survey["id"]
    assert a.write("DELETE", f"/api/library-questions/{q['id']}/grants/{grant.json()['grants'][0]['id']}", {"revision": grant.json()["question"]["revision"]}).status_code == 200
    assert b.get(f"/api/library-questions/{q['id']}").status_code == 404
    instances = [{"surveyId": survey["id"], "definitionVersion": survey["definitionVersion"], "instanceId": item["id"]} for item in survey["questions"]]
    payload = {"instances": instances, "requestKey": str(uuid4())}
    derived = b.write("POST", "/api/library-questions/derive-batch", payload)
    assert derived.status_code == 201, derived.text
    result = derived.json()
    assert len(result["questions"]) == 1 and len(result["mappings"]) == 2
    own = result["questions"][0]
    assert own["rootQuestionId"] == q["rootQuestionId"] and own["ownerId"] == b.user["id"]
    history = b.get(f"/api/library-questions/{own['id']}/versions").json()["versions"]
    assert history[0]["derivedFromVersionId"] == version["id"] and history[0]["content"] == version["content"]
    replay = b.write("POST", "/api/library-questions/derive-batch", payload)
    assert replay.status_code == 201 and replay.json()["questions"][0]["id"] == own["id"]
    assert BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])})) == before
    assert c.write("POST", "/api/library-questions/derive-batch", {"instances": instances, "requestKey": str(uuid4())}).status_code == 404
    assert b.write("POST", "/api/library-questions/derive-batch", {"instances": instances * 3, "requestKey": str(uuid4())}).status_code == 422


@pytest.mark.case("S2-16")
def test_existing_local_instance_can_be_saved_and_publish_registered(api_factory, survey_factory, real_db):
    author = api_factory()
    survey = survey_factory(author, publish=False)
    instance = survey["questions"][0]["id"]
    saved = author.write("POST", f"/api/surveys/{survey['id']}/library-instances/save", {"revision": survey["revision"], "instanceId": instance, "requestKey": str(uuid4())})
    assert saved.status_code == 200
    survey = saved.json()["survey"]
    assert survey["questionRefs"][0]["instanceId"] == instance
    assert author.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]}).status_code == 200
    assert real_db.questions.find_one({"_id": ObjectId(survey["questionRefs"][0]["questionId"])})["hasPublishedUsage"]

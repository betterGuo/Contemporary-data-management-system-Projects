"""Independent functional recheck of combined stage-two paths on isolated DBs."""
from copy import deepcopy
import json
from uuid import uuid4

from bson import BSON, ObjectId
from fastapi.testclient import TestClient
import pytest

from app.services import library_service as library
from scripts.backup_project import manifest


pytestmark = pytest.mark.integration


def number(title="复核年龄", *, required=True):
    return {"type": "number", "title": title, "required": required,
            "options": [], "validation": {"integerOnly": True, "minValue": "0", "maxValue": "120"}}


def source(api, value=None):
    value = value or number()
    response = api.write("POST", "/api/library-questions", {"content": value, "requestKey": str(uuid4())})
    assert response.status_code == 201, response.text
    q = response.json()["question"]
    return edition(api, q, value)


def edition(api, q, value):
    response = api.write("POST", f"/api/library-questions/{q['id']}/versions", {
        "revision": q["revision"], "sourceVersionId": q["latestVersionId"],
        "content": value, "requestKey": str(uuid4()),
    })
    assert response.status_code == 201, response.text
    return response.json()["question"], response.json()["version"]


def pick(api, survey, version):
    result = api.write("POST", f"/api/surveys/{survey['id']}/library-instances", {
        "revision": survey["revision"], "versionId": version["id"], "requestKey": str(uuid4()),
    })
    assert result.status_code == 201, result.text
    return result.json()["survey"]


def publish(api, survey):
    result = api.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert result.status_code == 200, result.text
    return result.json()["survey"]


def stats(api, q, v):
    result = api.get(f"/api/library-questions/{q['id']}/statistics", params={"versionId": v["id"]})
    assert result.status_code == 200, result.text
    return result.json()["statistics"]


def grant(api, q, receiver):
    result = api.write("POST", f"/api/library-questions/{q['id']}/grants", {
        "revision": q["revision"], "username": receiver.user["username"],
    })
    assert result.status_code == 200, result.text
    return result.json()["question"]


@pytest.mark.case("S2-06", "S2-66")
def test_two_generation_derivation_keeps_root_and_exact_parent_without_reverse_access(api_factory):
    a, b, c = api_factory(), api_factory(), api_factory()
    qa, va = source(a)
    qa = grant(a, qa, b)
    response = b.write("POST", f"/api/library-questions/{qa['id']}/derive", {"versionId": va["id"], "requestKey": str(uuid4())})
    assert response.status_code == 201, response.text
    qb = response.json()["question"]
    vb = b.get(f"/api/library-questions/{qb['id']}/versions").json()["versions"][0]
    qb = grant(b, qb, c)
    response = c.write("POST", f"/api/library-questions/{qb['id']}/derive", {"versionId": vb["id"], "requestKey": str(uuid4())})
    assert response.status_code == 201, response.text
    qc = response.json()["question"]
    vc = c.get(f"/api/library-questions/{qc['id']}/versions").json()["versions"][0]
    assert len({qa["id"], qb["id"], qc["id"]}) == 3
    assert qa["rootQuestionId"] == qb["rootQuestionId"] == qc["rootQuestionId"] == qa["id"]
    assert vb["derivedFromVersionId"] == va["id"] and vc["derivedFromVersionId"] == vb["id"]
    assert qb["ownerId"] == b.user["id"] and qc["ownerId"] == c.user["id"]
    assert a.get(f"/api/library-questions/{qb['id']}").status_code == 404
    assert a.get(f"/api/library-questions/{qc['id']}").status_code == 404
    assert b.get(f"/api/library-questions/{qc['id']}").status_code == 404


@pytest.mark.case("S2-15")
def test_reorder_linked_instances_keeps_bindings_and_answer_interpretation(api_factory, survey_factory, submit_response):
    actor = api_factory()
    qa, va = source(actor, number("第一道"))
    qb, vb = source(actor, number("第二道"))
    survey = survey_factory(actor, questions=[], publish=False)
    survey = pick(actor, pick(actor, survey, va), vb)
    first, second = [q["id"] for q in survey["questions"]]
    previous_refs = {r["instanceId"]: r for r in survey["questionRefs"]}
    result = actor.write("PUT", f"/api/surveys/{survey['id']}/question-order", {
        "revision": survey["revision"], "questionIds": [second, first],
    })
    assert result.status_code == 200, result.text
    survey = result.json()["survey"]
    assert [q["id"] for q in survey["questions"]] == [second, first]
    assert {r["instanceId"]: r for r in survey["questionRefs"]} == previous_refs
    survey = publish(actor, survey)
    assert submit_response(actor, survey, {first: "10", second: "30"}).status_code == 201
    assert stats(actor, qa, va)["average"] == "10"
    assert stats(actor, qb, vb)["average"] == "30"


@pytest.mark.case("S2-16")
def test_publication_second_local_registration_failure_rolls_back_entire_definition(
    api_factory, survey_factory, real_db, monkeypatch,
):
    actor = api_factory()
    survey = survey_factory(actor, questions=[{"id": "local-a", **number("甲")}, {"id": "local-b", **number("乙")}], publish=False)
    before = manifest(real_db)
    original = library.new_question
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError("intentional-second-local-registration-failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(library, "new_question", fail_second)
    with pytest.raises(RuntimeError, match="intentional-second-local-registration-failure"):
        actor.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert len(calls) == 2
    assert manifest(real_db) == before
    assert real_db.surveys.find_one({"_id": ObjectId(survey["id"])})["status"] == "draft"


@pytest.mark.parametrize("kind", ["register-role", "create-owner", "create-root", "select-snapshot"])
@pytest.mark.case("S2-10", "S2-18", "S2-22")
def test_client_cannot_inject_identity_or_snapshot_fields(kind, api_factory, survey_factory, real_db):
    actor = api_factory()
    q, v = source(actor)
    survey = survey_factory(actor, questions=[], publish=False)
    before = manifest(real_db)
    if kind == "register-role":
        result = actor.client.post("/api/auth/register", json={"username": "illegal_"+uuid4().hex[:8], "password": "test-password-123", "role": "admin"}, headers={"Origin": "http://testserver"})
    elif kind.startswith("create-"):
        extra = {"ownerId": str(ObjectId())} if kind == "create-owner" else {"rootQuestionId": q["id"]}
        result = actor.write("POST", "/api/library-questions", {"content": number(), "requestKey": str(uuid4()), **extra})
    else:
        result = actor.write("POST", f"/api/surveys/{survey['id']}/library-instances", {
            "revision": survey["revision"], "versionId": v["id"], "requestKey": str(uuid4()),
            "content": number("伪造的快照"), "rootQuestionId": str(ObjectId()),
        })
    assert result.status_code == 422, result.text
    assert manifest(real_db) == before


@pytest.mark.case("S2-49")
def test_cross_statistics_excludes_optional_blank_and_branch_skip_but_includes_zero(
    api_factory, survey_factory, submit_response,
):
    actor = api_factory()
    q, v = source(actor, number(required=False))
    gate = {"id": "gate", "type": "single", "title": "是否回答年龄", "required": True,
            "options": [{"id": "go", "label": "继续"}, {"id": "skip", "label": "跳过"}],
            "jumpRules": [{"id": "skip-age", "operator": "eq", "value": "skip", "targetQuestionId": "END"}]}
    survey = survey_factory(actor, questions=[gate], publish=False, allowMultipleSubmissions=True)
    survey = publish(actor, pick(actor, survey, v))
    instance = survey["questions"][1]["id"]
    assert submit_response(actor, survey, {"gate": "skip"}).status_code == 201
    assert submit_response(actor, survey, {"gate": "go", instance: ""}).status_code == 201
    assert submit_response(actor, survey, {"gate": "go", instance: "0"}).status_code == 201
    second = publish(actor, pick(actor, survey_factory(actor, questions=[], publish=False, allowMultipleSubmissions=True), v))
    second_instance = second["questions"][0]["id"]
    assert submit_response(actor, second, {second_instance: ""}).status_code == 201
    assert submit_response(actor, second, {second_instance: "10"}).status_code == 201
    result = stats(actor, q, v)
    assert result["answerCount"] == result["responseCount"] == result["surveyCount"] == 2
    assert (result["average"], result["min"], result["max"]) == ("5", "0", "10")
    assert result["distribution"] == [{"value": "0", "count": 1}, {"value": "10", "count": 1}]


@pytest.mark.case("S2-61")
def test_identical_instance_strings_in_different_surveys_do_not_cross_match_versions(
    api_factory, survey_factory, submit_response, real_db,
):
    actor = api_factory()
    qa, va = source(actor, number("目标题"))
    qa, vb = edition(actor, qa, number("不应混入旧版的新版"))
    surveys = []
    for version in (va, vb):
        survey = pick(actor, survey_factory(actor, questions=[], publish=False), version)
        old_id = survey["questions"][0]["id"]
        items, refs = deepcopy(survey["questions"]), deepcopy(survey["questionRefs"])
        items[0]["id"] = refs[0]["instanceId"] = "legacy-same-instance"
        sid = ObjectId(survey["id"])
        real_db.surveys.update_one({"_id": sid}, {"$set": {"questions": items, "questionRefs": [{**r, "questionId": ObjectId(r["questionId"]), "questionVersionId": ObjectId(r["questionVersionId"]), "rootQuestionId": ObjectId(r["rootQuestionId"])} for r in refs]}})
        real_db.question_usage.update_many({"surveyId": sid, "instanceId": old_id}, {"$set": {"instanceId": "legacy-same-instance"}})
        refreshed = actor.get(f"/api/surveys/{survey['id']}").json()["survey"]
        surveys.append(publish(actor, refreshed))
    assert submit_response(actor, surveys[0], {"legacy-same-instance": "10"}).status_code == 201
    assert submit_response(actor, surveys[1], {"legacy-same-instance": "99"}).status_code == 201
    assert stats(actor, qa, va)["average"] == "10"
    assert stats(actor, qa, vb)["average"] == "99"
    assert stats(actor, qa, va)["answerCount"] == 1


@pytest.mark.case("S2-67")
def test_other_usage_count_is_one_after_double_use_upgrade_remove_and_reselect(
    api_factory, survey_factory,
):
    owner, receiver = api_factory(), api_factory()
    q, v1 = source(owner)
    q = grant(owner, q, receiver)
    survey = survey_factory(receiver, questions=[], publish=False)
    survey = pick(receiver, pick(receiver, survey, v1), v1)
    q, v2 = edition(owner, q, number("新版年龄"))
    first = survey["questions"][0]["id"]
    changed = receiver.write("POST", f"/api/surveys/{survey['id']}/library-instances/upgrade", {
        "revision": survey["revision"], "instanceId": first, "versionId": v2["id"], "requestKey": str(uuid4()),
    })
    assert changed.status_code == 200, changed.text
    survey = changed.json()["survey"]
    for instance in [row["id"] for row in survey["questions"]]:
        deleted = receiver.write("DELETE", f"/api/surveys/{survey['id']}/questions/{instance}", {"revision": survey["revision"]})
        assert deleted.status_code == 200, deleted.text
        survey = deleted.json()["survey"]
    survey = pick(receiver, survey, v1)
    for suffix in ("", f"?scope=version&versionId={v1['id']}", f"?scope=version&versionId={v2['id']}"):
        usage = owner.get(f"/api/library-questions/{q['id']}/usage"+suffix).json()["usage"]
        assert usage["otherSurveyCount"] == 1 and usage["surveys"] == []
    received = receiver.get(f"/api/library-questions/{q['id']}/usage").json()["usage"]
    assert len(received["surveys"]) == 1 and "otherSurveyCount" not in received


@pytest.mark.case("S2-70")
def test_five_valid_snapshot_instances_batch_success_is_atomic_deduplicated_and_replayable(
    api_factory, survey_factory, real_db,
):
    actor = api_factory()
    q, v = source(actor)
    survey = survey_factory(actor, questions=[], publish=False)
    for _ in range(5):
        survey = pick(actor, survey, v)
    before_survey = BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])}))
    payload = {"instances": [{"surveyId": survey["id"], "definitionVersion": survey["definitionVersion"], "instanceId": item["id"]} for item in survey["questions"]], "requestKey": str(uuid4())}
    result = actor.write("POST", "/api/library-questions/derive-batch", payload)
    assert result.status_code == 201, result.text
    data = result.json()
    assert len(data["questions"]) == 1 and len(data["mappings"]) == 5
    own = data["questions"][0]
    assert own["rootQuestionId"] == q["rootQuestionId"] and own["latestVersionNumber"] == 1
    replay = actor.write("POST", "/api/library-questions/derive-batch", payload)
    assert replay.status_code == 201 and replay.json()["questions"][0]["id"] == own["id"]
    assert real_db.questions.count_documents({}) == 2
    assert BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])})) == before_survey


@pytest.mark.case("S2-76")
def test_closing_published_survey_and_removing_draft_use_does_not_unlock_working_content(
    api_factory, survey_factory,
):
    actor = api_factory()
    q, v = source(actor)
    published = publish(actor, pick(actor, survey_factory(actor, questions=[], publish=False), v))
    draft = pick(actor, survey_factory(actor, questions=[], publish=False), v)
    assert actor.write("POST", f"/api/surveys/{published['id']}/close", {}).status_code == 200
    assert actor.write("DELETE", f"/api/surveys/{draft['id']}/questions/{draft['questions'][0]['id']}", {"revision": draft["revision"]}).status_code == 200
    current = actor.get(f"/api/library-questions/{q['id']}").json()["question"]
    assert current["hasPublishedUsage"]
    rejected = actor.write("POST", f"/api/library-questions/{q['id']}/working-content", {"revision": current["revision"], "content": number("不允许直接覆盖")})
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "VERSION_REQUIRED"


@pytest.mark.case("S2-75")
def test_three_users_personal_tags_are_independent_of_source_and_each_other(api_factory, real_db):
    a, b, c = api_factory(), api_factory(), api_factory()
    q, version = source(a)
    q = grant(a, grant(a, q, b), c)
    for actor, tag in ((b, "乙分类"), (c, "丙分类")):
        saved = actor.write("POST", "/api/question-bookmarks", {"questionId": q["id"], "versionId": version["id"], "tags": [tag]})
        assert saved.status_code == 200, saved.text
    before_source = BSON.encode(real_db.questions.find_one({"_id": ObjectId(q["id"])}))
    renamed = b.write("POST", "/api/question-tags", {"oldTag": "乙分类", "newTag": "乙的新分类"})
    assert renamed.status_code == 200 and renamed.json()["modified"] == 1
    rows = {str(row["userId"]): row["tags"] for row in real_db.question_bookmarks.find({"questionId": ObjectId(q["id"])})}
    assert rows[a.user["id"]] == [] and rows[b.user["id"]] == ["乙的新分类"] and rows[c.user["id"]] == ["丙分类"]
    assert BSON.encode(real_db.questions.find_one({"_id": ObjectId(q["id"])})) == before_source


def raw_write_without_server_reraise(app, actor, method, path, payload):
    """Send actual escaped JSON and observe HTTP 500 rather than a test transport exception."""
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.update(actor.client.cookies)
        return client.request(method, path, content=json.dumps(payload, ensure_ascii=True).encode("ascii"), headers={
            "Content-Type": "application/json", "Origin": "http://testserver",
            "X-CSRF-Token": client.cookies.get("csrf_token", ""),
        })


@pytest.mark.parametrize("field", ["question-title", "option-label", "option-id", "rule-id", "answer-text"])
@pytest.mark.case("S2-22")
def test_boundary_escaped_lone_surrogate_is_rejected_without_server_error(
    field, api_factory, survey_factory, app, real_db,
):
    actor = api_factory()
    text_question = {"id": "text", "type": "text", "title": "文字题", "required": True}
    survey = survey_factory(actor, questions=[text_question], publish=field == "answer-text")
    if field == "answer-text":
        method, path = "POST", f"/api/participation/{survey['publicId']}/responses"
        payload = {"definitionVersion": survey["definitionVersion"], "submissionKey": str(uuid4()),
                   "isAnonymous": False, "answers": [{"questionId": "text", "value": "\ud800"}]}
    else:
        question = {**text_question, "title": "\ud800"} if field == "question-title" else {
            "id": "choice", "type": "single", "title": "选项题", "required": True,
            "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        }
        if field == "option-label":
            question["options"][0]["label"] = "\ud800"
        elif field == "option-id":
            question["options"][0]["id"] = "\ud800"
        elif field == "rule-id":
            question["jumpRules"] = [{"id": "\ud800", "operator": "eq", "value": "a", "targetQuestionId": "END"}]
        method, path = "PATCH", f"/api/surveys/{survey['id']}"
        payload = {"revision": survey["revision"], "questions": [question]}
    before = manifest(real_db)
    result = raw_write_without_server_reraise(app, actor, method, path, payload)
    assert manifest(real_db) == before, "Malformed Unicode must not write any business collection"
    assert result.status_code == 422, f"{field}: HTTP {result.status_code}: {result.text}"


@pytest.mark.parametrize("operation", [
    "archive", "grant", "revoke", "availability", "survey-patch", "question-add",
    "question-edit", "question-delete", "question-order", "survey-publish",
])
@pytest.mark.case("S2-22")
def test_boundary_revision_larger_than_bson_integer_is_rejected_before_writes(
    operation, api_factory, survey_factory, app, real_db,
):
    owner, receiver = api_factory(), api_factory()
    q, version = source(owner)
    survey = survey_factory(owner, publish=False)
    revision = 2**63
    payload = {"revision": revision}
    method = "POST"
    if operation == "archive":
        path = f"/api/library-questions/{q['id']}/archive"
    elif operation == "grant":
        path = f"/api/library-questions/{q['id']}/grants"
        payload["username"] = receiver.user["username"]
    elif operation == "revoke":
        grant(owner, q, receiver)
        row = owner.get(f"/api/library-questions/{q['id']}/grants").json()["grants"][0]
        method, path = "DELETE", f"/api/library-questions/{q['id']}/grants/{row['id']}"
    elif operation == "availability":
        path = f"/api/library-questions/{q['id']}/versions/{version['id']}/availability"
        payload["selectable"] = False
    elif operation == "survey-patch":
        method, path = "PATCH", f"/api/surveys/{survey['id']}"
        payload["title"] = "不得写入"
    elif operation in {"question-add", "question-edit"}:
        method = "POST" if operation == "question-add" else "PATCH"
        path = f"/api/surveys/{survey['id']}/questions" + ("/q1" if method == "PATCH" else "")
        payload["question"] = {"id": "new" if method == "POST" else "q1", **number()}
    elif operation == "question-delete":
        method, path = "DELETE", f"/api/surveys/{survey['id']}/questions/q1"
    elif operation == "question-order":
        method, path = "PUT", f"/api/surveys/{survey['id']}/question-order"
        payload["questionIds"] = ["q1"]
    else:
        path = f"/api/surveys/{survey['id']}/publish"
    before = manifest(real_db)
    result = raw_write_without_server_reraise(app, owner, method, path, payload)
    assert manifest(real_db) == before, "Out-of-range revision must not write any business collection"
    assert result.status_code == 422, f"{operation}: HTTP {result.status_code}: {result.text}"


@pytest.mark.parametrize("scope", ["overview", "question", "cross", "surveys", "library", "bookmarks"])
@pytest.mark.parametrize("boundary", ["larger-than-int64", "beyond-safe-page"])
@pytest.mark.case("S2-49")
def test_boundary_all_pagination_rejects_values_beyond_safe_skip_range(
    scope, boundary, api_factory, survey_factory, submit_response, app, real_db,
):
    from app.services.storage_adapters import MAX_PAGE

    actor = api_factory()
    q, version = source(actor)
    survey = publish(actor, pick(actor, survey_factory(actor, questions=[], publish=False), version))
    instance = survey["questions"][0]["id"]
    assert submit_response(actor, survey, {instance: "0"}).status_code == 201
    if scope in {"overview", "question"}:
        path = f"/api/surveys/{survey['id']}" + (f"/questions/{instance}" if scope == "question" else "") + "/statistics"
    else:
        path = {
            "cross": f"/api/library-questions/{q['id']}/statistics",
            "surveys": "/api/surveys", "library": "/api/library-questions", "bookmarks": "/api/question-bookmarks",
        }[scope]
    params = {"page": 2**63 if boundary == "larger-than-int64" else MAX_PAGE + 1}
    if scope == "cross":
        params["versionId"] = version["id"]
    before = manifest(real_db)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.update(actor.client.cookies)
        result = client.get(path, params=params)
    assert manifest(real_db) == before
    assert result.status_code == 422, f"{scope}/{boundary}: HTTP {result.status_code}: {result.text}"


@pytest.mark.parametrize("operation", ["snapshot-source", "submission"])
@pytest.mark.case("S2-22")
def test_boundary_definition_version_larger_than_bson_integer_is_rejected_without_writes(
    operation, api_factory, survey_factory, app, real_db,
):
    actor = api_factory()
    survey = survey_factory(actor)
    if operation == "snapshot-source":
        path = "/api/library-questions/derive-batch"
        payload = {"instances": [{"surveyId": survey["id"], "definitionVersion": 2**63, "instanceId": "q1"}],
                   "requestKey": str(uuid4())}
    else:
        path = f"/api/participation/{survey['publicId']}/responses"
        payload = {"definitionVersion": 2**63, "submissionKey": str(uuid4()), "isAnonymous": False,
                   "answers": [{"questionId": "q1", "value": "a"}]}
    before = manifest(real_db)
    result = raw_write_without_server_reraise(app, actor, "POST", path, payload)
    assert manifest(real_db) == before
    assert result.status_code == 422, f"{operation}: HTTP {result.status_code}: {result.text}"

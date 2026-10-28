"""Real transaction tests for independent questions and their access boundary."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from uuid import uuid4

from bson import ObjectId
import pytest

from app.database import utcnow
from app.services import library_service as library


pytestmark = pytest.mark.integration


def numeric(title="年龄", maximum="120"):
    return {"type": "number", "title": title, "required": True, "options": [], "validation": {"minValue": "0", "maxValue": maximum, "integerOnly": True}}


def create(api, value=None, **extra):
    response = api.write("POST", "/api/library-questions", {"content": value or numeric(), "requestKey": str(uuid4()), **extra})
    assert response.status_code == 201, response.text
    return response.json()["question"]


def version(api, question, value=None, **extra):
    response = api.write("POST", f"/api/library-questions/{question['id']}/versions", {
        "revision": question["revision"], "content": value or question["workingContent"],
        "sourceVersionId": question["latestVersionId"], "requestKey": str(uuid4()), **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.case("S2-01", "S2-03", "S2-05", "S2-64")
def test_persistent_working_copy_versions_and_restore(api_factory):
    author = api_factory()
    q = create(author)
    assert q["latestVersionId"] is None and q["latestVersionNumber"] == 0
    saved = author.write("POST", f"/api/library-questions/{q['id']}/working-content", {"revision": q["revision"], "content": numeric(maximum="100")})
    assert saved.status_code == 200
    q = saved.json()["question"]
    assert q["latestVersionNumber"] == 0
    first = version(author, q)
    q = first["question"]
    changed = author.write("POST", f"/api/library-questions/{q['id']}/working-content", {"revision": q["revision"], "content": numeric(maximum="80")}).json()["question"]
    assert changed["latestVersionNumber"] == 1
    second = version(author, changed)
    restored = author.write("POST", f"/api/library-questions/{q['id']}/restore", {"revision": second["question"]["revision"], "versionId": first["version"]["id"], "requestKey": str(uuid4())})
    assert restored.status_code == 201, restored.text
    assert restored.json()["version"]["versionNumber"] == 3
    assert restored.json()["version"]["content"]["validation"]["maxValue"] == "100"
    assert restored.json()["version"]["derivedFromVersionId"] == first["version"]["id"]
    history = author.get(f"/api/library-questions/{q['id']}/versions").json()["versions"]
    assert [row["versionNumber"] for row in history] == [3, 2, 1]
    assert history[-1]["content"]["validation"]["maxValue"] == "100"


@pytest.mark.case("S2-17", "S2-18", "S2-19", "S2-20", "S2-66", "S2-72")
def test_sharing_does_not_leak_working_copy_or_inherit_root_permission(api_factory):
    a, b, c = api_factory(), api_factory(), api_factory()
    first = version(a, create(a))
    q = first["question"]
    draft_text = {"type": "text", "title": "尚未公开的稿件标题", "required": False, "options": [], "validation": {}}
    q = a.write("POST", f"/api/library-questions/{q['id']}/working-content", {"revision": q["revision"], "content": draft_text}).json()["question"]
    grant = a.write("POST", f"/api/library-questions/{q['id']}/grants", {"revision": q["revision"], "username": b.user["username"]})
    assert grant.status_code == 200, grant.text
    q = grant.json()["question"]
    shared = b.get(f"/api/library-questions/{q['id']}").json()["question"]
    assert "workingContent" not in shared and shared["title"] == "年龄" and shared["type"] == "number"
    assert b.get("/api/library-questions?scope=shared&q=尚未公开").json()["total"] == 0
    assert c.get(f"/api/library-questions/{q['id']}").status_code == 404
    denied = b.write("POST", f"/api/library-questions/{q['id']}/working-content", {"revision": q["revision"], "content": numeric()})
    assert denied.status_code == 403
    derived = b.write("POST", f"/api/library-questions/{q['id']}/derive", {"versionId": first["version"]["id"], "requestKey": str(uuid4())})
    assert derived.status_code == 201, derived.text
    own = derived.json()["question"]
    assert own["rootQuestionId"] == q["rootQuestionId"] and own["ownerId"] == b.user["id"]
    assert a.get(f"/api/library-questions/{own['id']}").status_code == 404
    revoked = a.write("DELETE", f"/api/library-questions/{q['id']}/grants/{grant.json()['grants'][0]['id']}", {"revision": q["revision"]})
    assert revoked.status_code == 200
    assert b.get(f"/api/library-questions/{q['id']}").status_code == 404
    assert b.get(f"/api/library-questions/{own['id']}").status_code == 200


@pytest.mark.case("S2-72")
def test_shared_question_without_formal_version_is_not_visible(api_factory):
    owner, receiver = api_factory(), api_factory()
    q = create(owner, numeric("未生成首版的私密稿"))
    shared = owner.write("POST", f"/api/library-questions/{q['id']}/grants", {"revision": q["revision"], "username": receiver.user["username"]})
    assert shared.status_code == 200
    assert receiver.get(f"/api/library-questions/{q['id']}").status_code == 404
    assert receiver.get(f"/api/library-questions/{q['id']}/versions").status_code == 404
    assert receiver.get("/api/library-questions?scope=shared&q=私密稿").json()["total"] == 0
    assert receiver.write("POST", "/api/question-bookmarks", {"questionId": q["id"], "tags": []}).status_code == 404


@pytest.mark.case("S2-22", "S2-23", "S2-68")
def test_public_maintenance_and_independent_version_availability(api_factory, real_db):
    admin, ordinary = api_factory(), api_factory()
    bad = ordinary.write("POST", "/api/library-questions", {"content": numeric(), "visibility": "public", "requestKey": str(uuid4())})
    assert bad.status_code == 403
    real_db.users.update_one({"_id": ObjectId(admin.user["id"])}, {"$set": {"role": "admin"}})
    first = version(admin, create(admin, visibility="public"))
    q, v = first["question"], first["version"]
    assert ordinary.get("/api/library-questions?scope=public").json()["total"] == 1
    down = admin.write("POST", f"/api/library-questions/{q['id']}/versions/{v['id']}/availability", {"revision": v["revision"], "selectable": False})
    assert down.status_code == 200
    assert ordinary.get("/api/library-questions?scope=public").json()["total"] == 0
    assert admin.get(f"/api/library-questions/{q['id']}/versions").json()["versions"][0]["content"] == v["content"]


@pytest.mark.case("S2-28", "S2-31", "S2-32")
def test_parallel_cas_and_idempotent_replay(api_factory, real_db):
    author = api_factory()
    second_client = api_factory(copy_session=author)
    q = create(author)
    bodies = [{"revision": q["revision"], "sourceVersionId": None, "content": numeric(maximum=str(maximum)), "requestKey": str(uuid4())} for maximum in (60, 80)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda pair: pair[0].write("POST", f"/api/library-questions/{q['id']}/versions", pair[1]), zip((author, second_client), bodies)))
    assert sorted(response.status_code for response in responses) == [201, 409], [r.text for r in responses]
    winner = next(i for i, response in enumerate(responses) if response.status_code == 201)
    replay = author.write("POST", f"/api/library-questions/{q['id']}/versions", bodies[winner])
    assert replay.status_code == 201 and replay.json()["version"]["id"] == responses[winner].json()["version"]["id"]
    bad = deepcopy(bodies[winner]); bad["content"] = numeric(maximum="30")
    assert author.write("POST", f"/api/library-questions/{q['id']}/versions", bad).status_code == 409
    assert real_db.question_versions.count_documents({"questionId": ObjectId(q["id"])}) == 1


@pytest.mark.case("S2-29", "S2-30")
def test_version_insert_failure_rolls_back_pointer_number_and_receipt(api_factory, real_db, monkeypatch):
    author = api_factory(); q = create(author)
    user = real_db.users.find_one({"_id": ObjectId(author.user["id"])})
    before = real_db.questions.find_one({"_id": ObjectId(q["id"])})

    def fail_insert(*args, **kwargs):
        raise RuntimeError("intentional-version-write-failure")

    monkeypatch.setattr(library, "_insert_version", fail_insert)
    key = str(uuid4())
    with pytest.raises(RuntimeError, match="intentional-version-write-failure"):
        library.save_version(real_db, user, q["id"], {"revision": q["revision"], "sourceVersionId": None, "content": numeric(), "requestKey": key}, utcnow())
    assert real_db.questions.find_one({"_id": ObjectId(q["id"])}) == before
    assert real_db.question_versions.count_documents({"questionId": ObjectId(q["id"])}) == 0
    assert real_db.operation_receipts.find_one({"requestKey": key}) is None


@pytest.mark.case("S2-24", "S2-75")
def test_personal_tags_never_change_source_question_or_other_bookmarks(api_factory, real_db):
    a, b = api_factory(), api_factory()
    first = version(a, create(a)); q = first["question"]
    shared = a.write("POST", f"/api/library-questions/{q['id']}/grants", {"revision": q["revision"], "username": b.user["username"]})
    assert shared.status_code == 200
    source_before = real_db.questions.find_one({"_id": ObjectId(q["id"])})
    saved = b.write("POST", "/api/question-bookmarks", {"questionId": q["id"], "versionId": first["version"]["id"], "tags": ["我的课程", "基础"]})
    assert saved.status_code == 200
    # Selection guards are intentional writes, not content/ownership changes.
    source_after = real_db.questions.find_one({"_id": ObjectId(q["id"])})
    source_before.pop("selectionGuard"); source_after.pop("selectionGuard")
    assert source_before == source_after
    assert a.get("/api/question-bookmarks").json()["tags"] == []
    assert b.write("POST", "/api/question-tags", {"oldTag": "基础", "newTag": "通用"}).json()["modified"] == 1
    assert b.get("/api/question-bookmarks").json()["tags"] == ["我的课程", "通用"]
    assert b.write("DELETE", f"/api/question-bookmarks/{q['id']}").status_code == 200
    assert real_db.question_versions.find_one({"_id": ObjectId(first["version"]["id"])})


@pytest.mark.parametrize("bad", [None, "invalid", {"type": "single", "title": "x", "options": None}])
def test_invalid_content_is_structured_validation_error(api_factory, bad):
    author = api_factory()
    response = author.write("POST", "/api/library-questions", {"content": bad, "requestKey": str(uuid4())})
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["title", "option", "requestKey"])
def test_raw_json_surrogate_is_rejected_without_server_error(api_factory, field):
    author = api_factory()
    payload = {"content": numeric(), "requestKey": str(uuid4())}
    if field == "title":
        payload["content"]["title"] = "\ud800"
    elif field == "option":
        payload["content"] = {"type": "single", "title": "选项测试", "options": [{"id": "a", "label": "\ud800"}], "validation": {}}
    else:
        payload["requestKey"] = "\ud800"
    response = author.client.post("/api/library-questions", content=json.dumps(payload, ensure_ascii=True), headers={"Origin": "http://testserver", "Content-Type": "application/json", "X-CSRF-Token": author.client.cookies.get("csrf_token", "")})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] in {"INVALID_DEFINITION", "INVALID_UNICODE", "INVALID_REQUEST"}


def test_regular_unicode_and_public_working_copy_are_kept_separate(api_factory, real_db):
    admin, reader = api_factory(), api_factory()
    real_db.users.update_one({"_id": ObjectId(admin.user["id"])}, {"$set": {"role": "admin"}})
    first = version(admin, create(admin, numeric("年龄 👩🏽‍💻 café"), visibility="public"))
    q = first["question"]
    edited = admin.write("POST", f"/api/library-questions/{q['id']}/working-content", {"revision": q["revision"], "content": {"type": "text", "title": "未公开公共稿", "options": [], "validation": {}}})
    assert edited.status_code == 200
    result = reader.get(f"/api/library-questions/{q['id']}").json()["question"]
    assert result["title"] == "年龄 👩🏽‍💻 café" and result["type"] == "number" and "workingContent" not in result
    assert reader.get("/api/library-questions?scope=public&q=未公开公共稿").json()["total"] == 0
    assert reader.get(f"/api/library-questions/{q['id']}/versions/{first['version']['id']}").json()["version"]["content"]["title"] == "年龄 👩🏽‍💻 café"


@pytest.mark.case("S2-20", "S2-31")
def test_successful_derivation_replays_owned_copy_after_source_revoke(api_factory, real_db):
    owner, receiver = api_factory(), api_factory()
    first = version(owner, create(owner))
    q = first["question"]
    granted = owner.write("POST", f"/api/library-questions/{q['id']}/grants", {"revision": q["revision"], "username": receiver.user["username"]}).json()
    body = {"versionId": first["version"]["id"], "requestKey": str(uuid4())}
    derived = receiver.write("POST", f"/api/library-questions/{q['id']}/derive", body)
    assert derived.status_code == 201
    own_id = derived.json()["question"]["id"]
    revoked = owner.write("DELETE", f"/api/library-questions/{q['id']}/grants/{granted['grants'][0]['id']}", {"revision": granted["question"]["revision"]})
    assert revoked.status_code == 200
    assert receiver.get(f"/api/library-questions/{q['id']}").status_code == 404
    replayed = receiver.write("POST", f"/api/library-questions/{q['id']}/derive", body)
    assert replayed.status_code == 201 and replayed.json()["question"]["id"] == own_id
    fresh = receiver.write("POST", f"/api/library-questions/{q['id']}/derive", {**body, "requestKey": str(uuid4())})
    assert fresh.status_code == 404
    assert real_db.questions.count_documents({"ownerId": ObjectId(receiver.user["id"])}) == 1


def _share(api, question_id, receiver):
    current = api.get(f"/api/library-questions/{question_id}").json()["question"]
    result = api.write("POST", f"/api/library-questions/{question_id}/grants", {"revision": current["revision"], "username": receiver.user["username"]})
    assert result.status_code == 200, result.text


def _derive(api, question_id, version_id):
    response = api.write("POST", f"/api/library-questions/{question_id}/derive", {"versionId": version_id, "requestKey": str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()["question"]


def _survey_using(api, version_ids):
    survey = api.write("POST", "/api/surveys", {"title": "同源使用范围问卷"}).json()["survey"]
    for version_id in version_ids:
        selected = api.write("POST", f"/api/surveys/{survey['id']}/library-instances", {"revision": survey["revision"], "versionId": version_id, "requestKey": str(uuid4())})
        assert selected.status_code == 201, selected.text
        survey = selected.json()["survey"]
    return survey


@pytest.mark.case("S2-27", "S2-66", "S2-67")
def test_root_usage_only_includes_visible_family_and_counts_manageable_members(api_factory):
    original, shared_author, hidden_author = api_factory(), api_factory(), api_factory()
    first = version(original, create(original)); q, v = first["question"], first["version"]
    _share(original, q["id"], shared_author)
    _share(original, q["id"], hidden_author)
    shared = _derive(shared_author, q["id"], v["id"])
    hidden = _derive(hidden_author, q["id"], v["id"])
    _share(shared_author, shared["id"], original)
    mine = _survey_using(original, [shared["latestVersionId"]])
    _survey_using(shared_author, [v["id"], shared["latestVersionId"]])
    _survey_using(hidden_author, [hidden["latestVersionId"]])
    direct = original.get(f"/api/library-questions/{q['id']}/usage?scope=question").json()["usage"]
    assert direct["surveys"] == [] and direct["otherSurveyCount"] == 1
    family = original.get(f"/api/library-questions/{q['id']}/usage?scope=root").json()["usage"]
    assert family["scope"] == "root" and family["visibleQuestionCount"] == 2
    assert [row["id"] for row in family["surveys"]] == [mine["id"]]
    assert family["surveys"][0]["currentInstances"] == [mine["questions"][0]["id"]]
    assert family["otherSurveyCount"] == 1
    assert original.get(f"/api/library-questions/{hidden['id']}").status_code == 404


@pytest.mark.case("S2-27", "S2-67")
def test_root_usage_receiver_gets_own_details_but_no_maintenance_count(api_factory):
    original, derivative_author, receiver = api_factory(), api_factory(), api_factory()
    first = version(original, create(original)); q, v = first["question"], first["version"]
    _share(original, q["id"], derivative_author)
    derivative = _derive(derivative_author, q["id"], v["id"])
    _share(original, q["id"], receiver)
    _share(derivative_author, derivative["id"], receiver)
    mine = _survey_using(receiver, [v["id"], derivative["latestVersionId"]])
    _survey_using(derivative_author, [v["id"]])
    result = receiver.get(f"/api/library-questions/{q['id']}/usage?scope=root").json()["usage"]
    assert result["visibleQuestionCount"] == 2
    assert [row["id"] for row in result["surveys"]] == [mine["id"]]
    assert len(result["surveys"][0]["currentInstances"]) == 2
    assert not result["canSeeOtherCount"] and "otherSurveyCount" not in result and "deletedOtherSurveyCount" not in result
    exact = receiver.get(f"/api/library-questions/{q['id']}/usage?versionId={v['id']}").json()["usage"]
    assert exact["scope"] == "version" and len(exact["surveys"][0]["currentInstances"]) == 1


def test_old_legal_unicode_choice_content_does_not_get_a_smaller_library_limit(api_factory):
    author = api_factory()
    value = {"type": "single", "title": "保留旧系统允许的Unicode上限", "options": [{"id": f"o{i}", "label": "😀" * 2000} for i in range(20)], "validation": {}}
    q = create(author, value)
    assert len(q["workingContent"]["options"]) == 20
    assert q["workingContent"]["options"][0]["label"] == "😀" * 2000

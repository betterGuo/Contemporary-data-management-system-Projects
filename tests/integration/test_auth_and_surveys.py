from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
from threading import Barrier

from bson import ObjectId
from pymongo.errors import WriteError
import pytest


pytestmark = pytest.mark.integration
ORIGIN = "http://testserver"
PASSWORD = "test-password-123"


@pytest.mark.case("T01", "T02", "T03")
def test_registration_normalization_password_hash_and_login(client, real_db):
    response = client.post("/api/auth/register", json={"username": "  Alice  ", "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 201
    assert "password" not in response.text.lower() and "hash" not in response.text.lower()
    stored = real_db.users.find_one({"usernameNormalized": "alice"})
    assert stored["username"] == "Alice"
    assert stored["passwordHash"].startswith("$argon2") and PASSWORD not in stored["passwordHash"]
    assert stored["createdAt"].tzinfo is not None
    duplicate = client.post("/api/auth/register", json={"username": "ALICE", "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert duplicate.status_code == 409 and real_db.users.count_documents({}) == 1
    bad = client.post("/api/auth/login", json={"username": "Alice", "password": "wrong-password"}, headers={"Origin": ORIGIN})
    assert bad.status_code == 401 and real_db.sessions.count_documents({}) == 0
    logged_in = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert logged_in.status_code == 200
    session = real_db.sessions.find_one({})
    raw_session, csrf = client.cookies.get("survey_session"), client.cookies.get("csrf_token")
    assert session["tokenHash"] == hashlib.sha256(raw_session.encode()).hexdigest()
    assert session["csrfTokenHash"] == hashlib.sha256(csrf.encode()).hexdigest()
    assert raw_session not in repr(session) and csrf not in repr(session)
    cookies = logged_in.headers.get_list("set-cookie")
    assert any("survey_session=" in value and "HttpOnly" in value for value in cookies)
    assert any("csrf_token=" in value and "HttpOnly" not in value for value in cookies)
    assert client.get("/api/auth/me").json()["user"]["username"] == "Alice"


@pytest.mark.case("T04", "T56")
def test_anonymous_browser_cannot_manage_or_submit_even_anonymous_survey(client, api_factory, survey_factory):
    owner = api_factory()
    survey = survey_factory(owner, allowAnonymous=True)
    assert client.get("/api/surveys").status_code == 401
    assert client.get(f"/api/participation/{survey['publicId']}").status_code == 401
    response = client.post(f"/api/participation/{survey['publicId']}/responses", json={"definitionVersion": 1, "submissionKey": "anon", "isAnonymous": True, "answers": []}, headers={"Origin": ORIGIN})
    assert response.status_code == 401


@pytest.mark.case("T05")
def test_expired_session_is_rejected_before_ttl_cleanup(api_factory, real_db, clock):
    api = api_factory()
    # This expiry remains in the future for the actual MongoDB TTL clock.
    future_expiry = clock() + timedelta(hours=1)
    real_db.sessions.update_one({"userId": ObjectId(api.user["id"])}, {"$set": {"expiresAt": future_expiry}})
    clock.advance(hours=2)
    assert real_db.sessions.count_documents({"userId": ObjectId(api.user["id"])}) == 1
    assert api.get("/api/auth/me").status_code == 401


@pytest.mark.case("T06")
def test_logout_deletes_session_and_old_cookie_no_longer_authenticates(api_factory, real_db):
    api = api_factory()
    replay = api_factory(copy_session=api)
    assert api.write("POST", "/api/auth/logout").status_code == 200
    assert not api.client.cookies.get("survey_session") and not api.client.cookies.get("csrf_token")
    assert real_db.sessions.count_documents({}) == 0
    assert replay.get("/api/auth/me").status_code == 401


@pytest.mark.case("T07", "T08", "T09", "T78")
def test_owner_isolation_for_all_management_routes(api_factory, survey_factory):
    owner, other = api_factory(), api_factory()
    survey = survey_factory(owner)
    own_other = survey_factory(other)
    assert [row["id"] for row in owner.get("/api/surveys").json()["surveys"]] == [survey["id"]]
    assert [row["id"] for row in other.get("/api/surveys").json()["surveys"]] == [own_other["id"]]
    base = f"/api/surveys/{survey['id']}"
    for path in (base, base + "/preview", base + "/statistics", base + "/questions/q1/statistics"):
        assert other.get(path).status_code == 404
    attempts = [("PATCH", base, {"revision": survey["revision"], "title": "篡改"}),
                ("POST", base + "/publish", {"revision": survey["revision"]}),
                ("POST", base + "/close", {})]
    for method, path, body in attempts:
        assert other.write(method, path, body).status_code == 404
    assert other.get(f"/api/participation/{survey['publicId']}").status_code == 200


@pytest.mark.case("T10", "T87")
def test_csrf_origin_and_refresh_flow(api_factory, real_db):
    api = api_factory()
    csrf = api.client.cookies.get("csrf_token")
    assert api.get("/dashboard").status_code == 200
    assert api.get("/dashboard").status_code == 200
    assert api.client.cookies.get("csrf_token") == csrf
    valid = api.write("POST", "/api/surveys", {"title": "刷新后创建"})
    assert valid.status_code == 201
    assert api.get(f"/surveys/{valid.json()['survey']['id']}/edit").status_code == 200
    second_tab = api_factory(copy_session=api)
    assert second_tab.write("POST", "/api/surveys", {"title": "新页面"}).status_code == 201
    for headers in ({"Origin": ORIGIN}, {"Origin": ORIGIN, "X-CSRF-Token": "wrong"},
                    {"Origin": "https://evil.example", "X-CSRF-Token": csrf}):
        response = api.client.post("/api/surveys", json={"title": "不得创建"}, headers=headers)
        assert response.status_code == 403
    assert real_db.surveys.count_documents({}) == 2


@pytest.mark.case("T11", "T19", "T85")
def test_create_add_four_question_types_and_independent_constraints(api_factory, clock):
    api = api_factory()
    deadline = (clock() + timedelta(days=1)).isoformat()
    response = api.write("POST", "/api/surveys", {"title": "完整创建", "description": "说明", "allowAnonymous": True, "allowMultipleSubmissions": True, "closesAt": deadline})
    assert response.status_code == 201
    survey = response.json()["survey"]
    definitions = [
        {"type": "single", "title": "单选", "options": [{"label": "甲"}]},
        {"type": "multiple", "title": "最多一项", "options": [{"label": "甲"}, {"label": "乙"}], "validation": {"maxSelections": 1}},
        {"type": "text", "title": "只设最少", "validation": {"minLength": 2}},
        {"type": "number", "title": "只有上界", "validation": {"maxValue": "120", "integerOnly": True}},
    ]
    generated_ids = []
    for question in definitions:
        added = api.write("POST", f"/api/surveys/{survey['id']}/questions", {"revision": survey["revision"], "question": question})
        assert added.status_code == 201, added.text
        survey = added.json()["survey"]
        generated_ids.append(survey["questions"][-1]["id"])
    assert len(set(generated_ids)) == 4
    reloaded = api.get(f"/api/surveys/{survey['id']}").json()["survey"]
    assert reloaded["title"] == "完整创建" and reloaded["description"] == "说明"
    assert reloaded["allowAnonymous"] and reloaded["allowMultipleSubmissions"]
    assert reloaded["closesAt"] == deadline
    assert [q["id"] for q in reloaded["questions"]] == generated_ids
    assert reloaded["questions"][1]["validation"] == {"minSelections": 0, "maxSelections": 1}


@pytest.mark.case("T12", "T13", "T14", "T15")
def test_lifecycle_empty_publish_draft_visibility_frozen_content_and_idempotent_close(api_factory, survey_factory, real_db):
    owner, visitor = api_factory(), api_factory()
    empty = survey_factory(owner, questions=[], publish=False)
    assert owner.write("POST", f"/api/surveys/{empty['id']}/publish", {"revision": empty["revision"]}).status_code == 422
    draft = survey_factory(owner, publish=False)
    base = f"/api/surveys/{draft['id']}"
    assert visitor.get(f"/api/participation/{draft['publicId']}").status_code == 404
    assert owner.write("POST", base + "/close").status_code == 409
    published = owner.write("POST", base + "/publish", {"revision": draft["revision"]})
    assert published.status_code == 200
    survey = published.json()["survey"]
    assert owner.write("POST", base + "/publish", {"revision": survey["revision"]}).status_code == 409
    before = real_db.surveys.find_one({"_id": ObjectId(survey["id"])})
    for change in ({"title": "变更"}, {"allowAnonymous": True}, {"allowMultipleSubmissions": True}, {"questions": []}):
        assert owner.write("PATCH", base, {"revision": survey["revision"], **change}).status_code == 409
    assert real_db.surveys.find_one({"_id": before["_id"]}) == before
    assert owner.write("POST", base + "/close").status_code == 200
    assert owner.write("POST", base + "/close").status_code == 200


@pytest.mark.case("T12")
def test_deadline_already_passed_prevents_publication(api_factory, survey_factory, clock):
    owner = api_factory()
    survey = survey_factory(owner, publish=False, closesAt=(clock() - timedelta(seconds=1)).isoformat())
    response = owner.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert response.status_code == 422


@pytest.mark.case("T18")
def test_two_writers_with_same_revision_cannot_silently_overwrite(api_factory, survey_factory):
    owner = api_factory()
    clients = [api_factory(copy_session=owner), api_factory(copy_session=owner)]
    survey = survey_factory(owner, publish=False)
    barrier = Barrier(2)
    def edit(index):
        barrier.wait(timeout=10)
        return clients[index].write("PATCH", f"/api/surveys/{survey['id']}", {"revision": survey["revision"], "title": f"编辑{index}"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(edit, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    saved = owner.get(f"/api/surveys/{survey['id']}").json()["survey"]
    assert saved["revision"] == survey["revision"] + 1
    assert saved["title"] in {"编辑0", "编辑1"}


@pytest.mark.case("T38")
def test_database_validators_reject_invalid_bson_and_api_rejects_server_fields(api_factory, real_db):
    api = api_factory()
    with pytest.raises(WriteError):
        real_db.users.insert_one({"username": "无效结构"})
    with pytest.raises(WriteError):
        real_db.surveys.insert_one({"status": "not-a-status"})
    response = api.write("POST", "/api/surveys", {"title": "不得创建", "ownerId": api.user["id"]})
    assert response.status_code == 422 and real_db.surveys.count_documents({}) == 0

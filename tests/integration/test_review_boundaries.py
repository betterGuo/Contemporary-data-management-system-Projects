"""Regressions found by independently reviewing the completed first-week app."""

from copy import deepcopy
from contextlib import ExitStack
import socket
from threading import Thread
import time
from urllib.parse import quote
from uuid import uuid4

from bson import ObjectId
import httpx
import pytest
import uvicorn


pytestmark = pytest.mark.integration

UTC_OVERFLOW_DEADLINES = [
    "0001-01-01T00:00:00+08:00",
    "9999-12-31T23:59:59-08:00",
]


@pytest.fixture
def wire_api_factory(app):
    """Run the injected test app on our own bound random socket, never port 8000.

    The installed legacy TestClient transport unquotes httpx.URL.path twice.
    Real HTTP is necessary to distinguish literal '%2F' from an encoded slash;
    application code must not compensate with another business-level decode.
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, lifespan="on"))
    thread = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(500):
            if server.started:
                break
            if not thread.is_alive():
                break
            time.sleep(0.01)
        assert server.started, "Isolated Uvicorn server did not start"
        with ExitStack() as stack:
            class WireSession:
                def __init__(self, client, user):
                    self.client, self.user = client, user

                def write(self, method, path, body=None):
                    return self.client.request(
                        method, path, json={} if body is None else body,
                        headers={"Origin": origin, "X-CSRF-Token": self.client.cookies.get("csrf_token", "")},
                    )

                def get(self, path):
                    return self.client.get(path)

            def factory():
                client = stack.enter_context(httpx.Client(base_url=origin, timeout=10))
                credentials = {"username": "wire_" + uuid4().hex[:12], "password": "test-password-123"}
                registered = client.post("/api/auth/register", json=credentials, headers={"Origin": origin})
                assert registered.status_code == 201, registered.text
                logged_in = client.post("/api/auth/login", json=credentials, headers={"Origin": origin})
                assert logged_in.status_code == 200, logged_in.text
                return WireSession(client, logged_in.json()["user"])

            yield factory
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive(), "Isolated test server did not stop"


@pytest.mark.case("T11", "T12", "T16")
@pytest.mark.parametrize("cutoff", UTC_OVERFLOW_DEADLINES)
def test_deadline_utc_overflow_on_create_returns_422_without_partial_survey(api_factory, real_db, cutoff):
    owner = api_factory()
    before = real_db.surveys.count_documents({})
    response = owner.write("POST", "/api/surveys", {"title": "越界截止时间", "closesAt": cutoff})
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "INVALID_DEADLINE"
    assert any(detail.get("field") == "closesAt" for detail in error["details"])
    assert real_db.surveys.count_documents({}) == before


@pytest.mark.case("T11", "T12", "T16")
@pytest.mark.parametrize("cutoff", UTC_OVERFLOW_DEADLINES)
def test_deadline_utc_overflow_on_patch_returns_422_without_changing_document(
    api_factory, survey_factory, real_db, cutoff,
):
    owner = api_factory()
    survey = survey_factory(owner, publish=False)
    original = deepcopy(real_db.surveys.find_one({"_id": ObjectId(survey["id"])}))
    response = owner.write(
        "PATCH", f"/api/surveys/{survey['id']}",
        {"revision": survey["revision"], "title": "不得部分改标题", "closesAt": cutoff},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_DEADLINE"
    assert real_db.surveys.find_one({"_id": original["_id"]}) == original


@pytest.mark.case("T53", "T57", "T58", "T67", "T73", "E03", "E04")
def test_missing_optional_legacy_fields_use_read_only_defaults_through_actual_api_paths(
    api_factory, survey_factory, submit_response, real_db,
):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner)
    survey_id = ObjectId(survey["id"])
    real_db.surveys.update_one(
        {"_id": survey_id},
        {"$unset": {field: "" for field in (
            "allowMultipleSubmissions", "allowAnonymous", "description", "closesAt",
        )}},
    )
    original = deepcopy(real_db.surveys.find_one({"_id": survey_id}))

    def assert_defaults(definition):
        assert definition["allowMultipleSubmissions"] is False
        assert definition["allowAnonymous"] is False
        assert definition["description"] == ""
        assert definition["closesAt"] is None

    managed = owner.get(f"/api/surveys/{survey['id']}")
    assert managed.status_code == 200, managed.text
    assert_defaults(managed.json()["survey"])
    shared = participant.get(f"/api/participation/{survey['publicId']}")
    assert shared.status_code == 200, shared.text
    assert_defaults(shared.json()["survey"])
    preview = owner.get(f"/api/surveys/{survey['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert_defaults(preview.json()["survey"])
    empty_stats = owner.get(f"/api/surveys/{survey['id']}/statistics")
    assert empty_stats.status_code == 200, empty_stats.text
    assert empty_stats.json()["statistics"]["submissionCount"] == 0
    assert real_db.surveys.find_one({"_id": survey_id}) == original

    accepted = submit_response(participant, survey, key="legacy-first")
    assert accepted.status_code == 201, accepted.text
    record = real_db.responses.find_one({"surveyId": survey_id})
    assert record["repeatMode"] == "single" and record["isAnonymous"] is False
    assert record["respondentUserId"] == ObjectId(participant.user["id"])
    repeated = submit_response(participant, survey, key="legacy-second")
    assert repeated.status_code == 409, repeated.text
    forbidden_anonymous = submit_response(participant, survey, key="legacy-anonymous", anonymous=True)
    assert forbidden_anonymous.status_code == 422, forbidden_anonymous.text
    assert real_db.responses.count_documents({"surveyId": survey_id}) == 1
    final_stats = owner.get(f"/api/surveys/{survey['id']}/statistics")
    assert final_stats.status_code == 200, final_stats.text
    assert final_stats.json()["statistics"]["submissionCount"] == 1
    # Defaults are a compatibility view, not an implicit migration on GET/POST.
    assert real_db.surveys.find_one({"_id": survey_id}) == original


@pytest.mark.case("T19", "T21", "T53", "T76")
@pytest.mark.parametrize("question_id", ["group/item", "题目/年龄", "literal%2Fitem"])
def test_encoded_question_ids_keep_identity_through_edit_delete_publish_fill_and_single_statistics(
    wire_api_factory, survey_factory, submit_response, real_db, question_id,
):
    owner, participant = wire_api_factory(), wire_api_factory()
    definition = {"id": question_id, "type": "text", "title": "原始题目", "required": True,
                  "validation": {"minLength": 1, "maxLength": 40}}
    survey = survey_factory(owner, [definition], publish=False)
    base = f"/api/surveys/{survey['id']}"
    encoded_id = quote(question_id, safe="")
    edited_definition = {**definition, "title": "已修改题目"}
    edited = owner.write(
        "PATCH", f"{base}/questions/{encoded_id}",
        {"revision": survey["revision"], "question": edited_definition},
    )
    assert edited.status_code == 200, edited.text
    survey = edited.json()["survey"]
    assert survey["questions"][0]["id"] == question_id
    assert survey["questions"][0]["title"] == "已修改题目"

    deleted = owner.write("DELETE", f"{base}/questions/{encoded_id}", {"revision": survey["revision"]})
    assert deleted.status_code == 200, deleted.text
    survey = deleted.json()["survey"]
    assert survey["questions"] == []
    added = owner.write("POST", base + "/questions", {"revision": survey["revision"], "question": edited_definition})
    assert added.status_code == 201, added.text
    survey = added.json()["survey"]
    assert survey["questions"][0]["id"] == question_id
    published = owner.write("POST", base + "/publish", {"revision": survey["revision"]})
    assert published.status_code == 200, published.text
    survey = published.json()["survey"]
    shared = participant.get(f"/api/participation/{survey['publicId']}")
    assert shared.status_code == 200, shared.text
    assert shared.json()["survey"]["questions"][0]["id"] == question_id
    submitted = submit_response(participant, survey, {question_id: "一个真实回答"})
    assert submitted.status_code == 201, submitted.text
    record = real_db.responses.find_one({"surveyId": ObjectId(survey["id"])})
    assert record["answers"][0]["questionId"] == question_id

    overview = owner.get(base + "/statistics")
    single = owner.get(f"{base}/questions/{encoded_id}/statistics")
    assert overview.status_code == single.status_code == 200, single.text
    expected = next(q for q in overview.json()["statistics"]["questions"] if q["questionId"] == question_id)
    assert single.json()["statistics"] == expected
    assert expected["answerCount"] == 1
    assert expected["values"][0]["value"] == "一个真实回答"

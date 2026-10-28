"""Deterministic HTTP races against a real replica set, without timing sleeps."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import uuid4

from bson import BSON, ObjectId
import pytest

from app.services import library_service as library


pytestmark = pytest.mark.integration


def numeric(maximum="120"):
    return {"type": "number", "title": "并发年龄题", "required": True, "options": [], "validation": {"minValue": "0", "maxValue": maximum, "integerOnly": True}}


def source(api):
    created = api.write("POST", "/api/library-questions", {"content": numeric(), "requestKey": str(uuid4())}).json()["question"]
    result = api.write("POST", f"/api/library-questions/{created['id']}/versions", {"revision": created["revision"], "sourceVersionId": None, "content": numeric(), "requestKey": str(uuid4())})
    assert result.status_code == 201, result.text
    return result.json()["question"], result.json()["version"]


def draft(api):
    return api.write("POST", "/api/surveys", {"title": "并发选题问卷"}).json()["survey"]


def pause_first_transaction_read(monkeypatch, actor_id, question_id):
    original = library.readable
    entered, release = Event(), Event()
    lock = Lock()
    state = {"paused": False, "transactionReads": 0}

    def wrapped(db, user, question, session=None):
        allowed = original(db, user, question, session)
        should_pause = False
        if session is not None and question and str(user["_id"]) == actor_id and str(question["_id"]) == question_id:
            with lock:
                state["transactionReads"] += 1
                if not state["paused"]:
                    state["paused"] = True
                    should_pause = True
        if should_pause:
            entered.set()
            if not release.wait(15):
                raise RuntimeError("concurrency-test-release-timeout")
        return allowed

    monkeypatch.setattr(library, "readable", wrapped)
    return entered, release, state


@pytest.mark.case("S2-34", "S2-35", "S2-68")
@pytest.mark.parametrize("action", ["revoke", "archive", "unavailable"])
def test_revoke_archive_or_unavailable_commits_before_waiting_selection(
    api_factory, real_db, monkeypatch, action,
):
    owner, receiver = api_factory(), api_factory()
    worker = api_factory(copy_session=receiver)
    q, version = source(owner)
    grant = owner.write("POST", f"/api/library-questions/{q['id']}/grants", {"revision": q["revision"], "username": receiver.user["username"]})
    assert grant.status_code == 200
    q = grant.json()["question"]
    survey = draft(receiver)
    entered, release, observed = pause_first_transaction_read(monkeypatch, receiver.user["id"], q["id"])
    key = str(uuid4())
    body = {"revision": survey["revision"], "versionId": version["id"], "requestKey": key}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(worker.write, "POST", f"/api/surveys/{survey['id']}/library-instances", body)
        try:
            assert entered.wait(10), "Selection never reached its authorized transaction read"
            if action == "revoke":
                response = owner.write("DELETE", f"/api/library-questions/{q['id']}/grants/{grant.json()['grants'][0]['id']}", {"revision": q["revision"]})
            elif action == "archive":
                response = owner.write("POST", f"/api/library-questions/{q['id']}/archive", {"revision": q["revision"]})
            else:
                response = owner.write("POST", f"/api/library-questions/{q['id']}/versions/{version['id']}/availability", {"revision": version["revision"], "selectable": False})
            assert response.status_code == 200, response.text
        finally:
            release.set()
        denied = pending.result(timeout=20)
    assert denied.status_code in {403, 404, 409}, denied.text
    assert observed["transactionReads"] >= 2, "The stale transaction must retry its authorization read"
    stored = real_db.surveys.find_one({"_id": ObjectId(survey["id"])})
    assert stored["questions"] == [] and stored.get("questionRefs", []) == []
    assert real_db.question_usage.count_documents({"surveyId": stored["_id"]}) == 0
    assert real_db.operation_receipts.find_one({"actorId": ObjectId(receiver.user["id"]), "requestKey": key}) is None


@pytest.mark.case("S2-33")
def test_committed_selection_survives_later_revoke_and_can_publish(api_factory, real_db):
    owner, receiver = api_factory(), api_factory()
    q, version = source(owner)
    shared = owner.write("POST", f"/api/library-questions/{q['id']}/grants", {"revision": q["revision"], "username": receiver.user["username"]}).json()
    survey = draft(receiver)
    selected = receiver.write("POST", f"/api/surveys/{survey['id']}/library-instances", {"revision": survey["revision"], "versionId": version["id"], "requestKey": str(uuid4())})
    assert selected.status_code == 201
    survey = selected.json()["survey"]
    before = BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])}))
    revoked = owner.write("DELETE", f"/api/library-questions/{q['id']}/grants/{shared['grants'][0]['id']}", {"revision": shared["question"]["revision"]})
    assert revoked.status_code == 200
    assert BSON.encode(real_db.surveys.find_one({"_id": ObjectId(survey["id"])})) == before
    published = receiver.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert published.status_code == 200, published.text
    assert published.json()["survey"]["questions"][0]["title"] == "并发年龄题"


@pytest.mark.case("S2-65")
def test_publication_commits_before_paused_ordinary_working_save(api_factory, real_db, monkeypatch):
    owner = api_factory()
    worker = api_factory(copy_session=owner)
    q, version = source(owner)
    survey = draft(owner)
    selected = owner.write("POST", f"/api/surveys/{survey['id']}/library-instances", {"revision": survey["revision"], "versionId": version["id"], "requestKey": str(uuid4())}).json()["survey"]
    entered, release, observed = pause_first_transaction_read(monkeypatch, owner.user["id"], q["id"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(worker.write, "POST", f"/api/library-questions/{q['id']}/working-content", {"revision": q["revision"], "content": numeric("60")})
        try:
            assert entered.wait(10)
            published = owner.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": selected["revision"]})
            assert published.status_code == 200, published.text
        finally:
            release.set()
        denied = pending.result(timeout=20)
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "VERSION_REQUIRED"
    assert observed["transactionReads"] >= 2
    stored = real_db.questions.find_one({"_id": ObjectId(q["id"])})
    assert stored["hasPublishedUsage"] and stored["workingContent"]["validation"]["maxValue"] == "120"
    assert stored["latestVersionNumber"] == 1

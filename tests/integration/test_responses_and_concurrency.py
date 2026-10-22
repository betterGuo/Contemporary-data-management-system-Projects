from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Event

from bson import ObjectId
from bson.decimal128 import Decimal128
from fastapi.testclient import TestClient
from pymongo.errors import AutoReconnect, DuplicateKeyError
import pytest

from app.services import response_service


pytestmark = pytest.mark.integration


@pytest.mark.case("T53", "T54", "T57", "T38")
def test_submit_is_one_complete_document_and_invalid_submission_has_no_partial_save(api_factory, survey_factory, submit_response, real_db):
    owner, participant = api_factory(), api_factory()
    questions = [
        {"id": "q1", "type": "single", "title": "必答", "required": True,
         "options": [{"id": "a", "label": "甲"}, {"id": "b", "label": "乙"}]},
        {"id": "number", "type": "number", "title": "数字", "required": True,
         "validation": {"minValue": "0", "integerOnly": True}},
    ]
    survey = survey_factory(owner, questions)
    assert submit_response(participant, survey, {"q1": "a", "number": "-1"}).status_code == 422
    assert submit_response(participant, survey, {"q1": "a", "number": "0"}, anonymous=True).status_code == 422
    assert real_db.responses.count_documents({}) == 0
    response = submit_response(participant, survey, {"q1": "a", "number": "0"})
    assert response.status_code == 201
    record = real_db.responses.find_one({})
    assert record["visitedQuestionIds"] == ["q1", "number"] and len(record["answers"]) == 2
    assert record["respondentUserId"] == ObjectId(participant.user["id"])
    assert isinstance(record["answers"][1]["value"], Decimal128)
    assert str(record["answers"][1]["value"].to_decimal()) == "0"
    assert record["admittedAt"] <= record["submittedAt"]
    forbidden = participant.write("POST", f"/api/participation/{survey['publicId']}/responses",
                                  {"definitionVersion": 1, "submissionKey": "extra", "answers": [], "respondentKey": "forged"})
    assert forbidden.status_code == 422 and real_db.responses.count_documents({}) == 1


@pytest.mark.case("T55", "T58", "T61", "T75")
def test_anonymous_and_named_submissions_share_repeat_key_without_exposing_identity(api_factory, survey_factory, submit_response, real_db):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner, allowAnonymous=True)
    result = submit_response(participant, survey, key="first", anonymous=True)
    assert result.status_code == 201
    record = real_db.responses.find_one({})
    assert record["isAnonymous"] is True and record["respondentUserId"] is None
    assert isinstance(record["respondentKey"], str) and record["respondentKey"]
    assert submit_response(participant, survey, key="second", anonymous=False).status_code == 409
    assert submit_response(participant, survey, key="first", anonymous=False).status_code == 409
    stats = owner.get(f"/api/surveys/{survey['id']}/statistics")
    assert stats.status_code == 200
    for secret in (participant.user["id"], participant.user["username"], record["respondentKey"], "respondentUserId", "respondentKey"):
        assert secret not in stats.text
    assert real_db.responses.count_documents({}) == 1


@pytest.mark.case("T58", "T59", "T60", "T61", "T62")
@pytest.mark.parametrize("allow_multiple", [False, True])
def test_repeat_policy_idempotency_conflict_and_retry_after_close(api_factory, survey_factory, submit_response, real_db, clock, allow_multiple):
    owner, participant = api_factory(), api_factory()
    # BSON dates have millisecond precision; initial and replay receipts must
    # agree even when the application's clock includes finer microseconds.
    clock.advance(microseconds=123456)
    survey = survey_factory(owner, allowMultipleSubmissions=allow_multiple)
    first = submit_response(participant, survey, key="same-key")
    assert first.status_code == 201
    replay = submit_response(participant, survey, key="same-key")
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["response"] == first.json()["response"]
    assert submit_response(participant, survey, {"q1": "b"}, key="same-key").status_code == 409
    other = submit_response(participant, survey, key="different-key")
    assert other.status_code == (201 if allow_multiple else 409)
    expected = 2 if allow_multiple else 1
    assert real_db.responses.count_documents({}) == expected
    assert owner.write("POST", f"/api/surveys/{survey['id']}/close").status_code == 200
    assert submit_response(participant, survey, key="same-key").status_code == 200
    assert submit_response(participant, survey, key="after-close").status_code == 410
    assert real_db.responses.count_documents({}) == expected


@pytest.mark.case("T50", "T60")
def test_idempotent_retry_cannot_add_a_hidden_blank_answer(api_factory, survey_factory, submit_response, real_db):
    owner, participant = api_factory(), api_factory()
    questions = [
        {"id": "q1", "type": "single", "title": "提前结束", "required": True,
         "options": [{"id": "a", "label": "结束"}],
         "jumpRules": [{"id": "end", "operator": "eq", "value": "a", "targetQuestionId": "END"}]},
        {"id": "hidden", "type": "text", "title": "被跳过"},
    ]
    survey = survey_factory(owner, questions)
    assert submit_response(participant, survey, {"q1": "a"}, key="same").status_code == 201
    response = submit_response(participant, survey, {"q1": "a", "hidden": None}, key="same")
    assert response.status_code == 422
    assert real_db.responses.count_documents({}) == 1


@pytest.mark.case("T16", "T17")
def test_deadline_before_at_after_and_open_page_does_not_reserve_submission(api_factory, survey_factory, submit_response, clock, real_db):
    owner, participant = api_factory(), api_factory()
    cutoff = clock() + timedelta(seconds=30)
    survey = survey_factory(owner, allowMultipleSubmissions=True, closesAt=cutoff.isoformat())
    assert participant.get(f"/api/participation/{survey['publicId']}").status_code == 200
    clock.set(cutoff - timedelta(milliseconds=1))
    assert submit_response(participant, survey).status_code == 201
    clock.set(cutoff)
    assert submit_response(participant, survey).status_code == 410
    clock.advance(seconds=1)
    assert submit_response(participant, survey).status_code == 410
    assert owner.get(f"/api/surveys/{survey['id']}").json()["survey"]["effectiveStatus"] == "expired"
    assert real_db.responses.count_documents({}) == 1


@pytest.mark.case("T17")
def test_page_opened_before_manual_close_cannot_create_new_submission(api_factory, survey_factory, submit_response, real_db):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner)
    assert participant.get(f"/api/participation/{survey['publicId']}").status_code == 200
    assert owner.write("POST", f"/api/surveys/{survey['id']}/close").status_code == 200
    assert submit_response(participant, survey).status_code == 410
    assert real_db.responses.count_documents({}) == 0


@pytest.mark.case("T63")
def test_ten_different_accounts_submit_concurrently_without_overwriting(api_factory, survey_factory, submit_response, real_db):
    owner = api_factory()
    survey = survey_factory(owner)
    participants = [api_factory() for _ in range(10)]
    barrier = Barrier(10)
    def worker(index):
        barrier.wait(timeout=15)
        return submit_response(participants[index], survey)
    with ThreadPoolExecutor(max_workers=10) as executor:
        responses = list(executor.map(worker, range(10)))
    assert [response.status_code for response in responses] == [201] * 10
    assert real_db.responses.count_documents({"surveyId": ObjectId(survey["id"])}) == 10
    assert len(real_db.responses.distinct("respondentKey")) == 10


@pytest.mark.case("T64", "T65")
@pytest.mark.parametrize("allow_multiple,same_key,expected_new", [(False, False, 1), (True, True, 1), (True, False, 6)])
def test_same_account_concurrency_is_guarded_by_real_unique_indexes(api_factory, survey_factory, submit_response, real_db, allow_multiple, same_key, expected_new):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner, allowMultipleSubmissions=allow_multiple)
    clients = [api_factory(copy_session=participant) for _ in range(6)]
    barrier = Barrier(6)
    def worker(index):
        barrier.wait(timeout=15)
        return submit_response(clients[index], survey, key="same" if same_key else f"submission-{index}")
    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(executor.map(worker, range(6)))
    codes = [response.status_code for response in responses]
    assert codes.count(201) == expected_new
    if same_key:
        assert codes.count(200) == 5
        assert len({response.json()["response"]["id"] for response in responses}) == 1
    elif not allow_multiple:
        assert codes.count(409) == 5
    assert real_db.responses.count_documents({}) == expected_new


@pytest.mark.case("T64", "T65")
@pytest.mark.parametrize("allow_multiple", [False, True])
def test_actual_index_definitions_and_duplicate_inserts(api_factory, survey_factory, submit_response, real_db, allow_multiple):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner, allowMultipleSubmissions=allow_multiple)
    assert submit_response(participant, survey, key="first").status_code == 201
    indexes = real_db.responses.index_information()
    assert indexes["submission_idempotency"]["unique"] is True
    partial = indexes["single_response_per_user"]
    assert partial["unique"] is True and partial["partialFilterExpression"] == {"repeatMode": "single"}
    original = real_db.responses.find_one({})
    duplicate = deepcopy(original)
    duplicate.pop("_id")
    with pytest.raises(DuplicateKeyError):
        real_db.responses.insert_one(duplicate)
    duplicate["submissionKey"] = "different"
    if allow_multiple:
        real_db.responses.insert_one(duplicate)
        assert real_db.responses.count_documents({}) == 2
    else:
        with pytest.raises(DuplicateKeyError):
            real_db.responses.insert_one(duplicate)
        assert real_db.responses.count_documents({}) == 1


@pytest.mark.case("T66")
def test_close_allows_an_already_admitted_inflight_insert_to_finish(api_factory, survey_factory, submit_response, real_db, clock, monkeypatch):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner)
    admitted, release = Event(), Event()
    original_insert = response_service.repository.insert_response
    def delayed_insert(db, response):
        admitted.set()
        assert release.wait(timeout=15)
        return original_insert(db, response)
    monkeypatch.setattr(response_service.repository, "insert_response", delayed_insert)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(submit_response, participant, survey)
        try:
            assert admitted.wait(timeout=15)
            clock.advance(seconds=1)
            closed = owner.write("POST", f"/api/surveys/{survey['id']}/close")
            assert closed.status_code == 200
        finally:
            release.set()
        assert future.result(timeout=15).status_code == 201
    response = real_db.responses.find_one({})
    record = real_db.surveys.find_one({"_id": ObjectId(survey["id"])})
    assert response["admittedAt"] < record["closedAt"]
    assert submit_response(participant, survey).status_code == 410
    assert real_db.responses.count_documents({}) == 1


@pytest.mark.case("T67")
def test_fresh_application_reads_existing_users_definitions_sessions_and_responses(app, api_factory, survey_factory, submit_response, real_db, clock):
    from app.main import create_app

    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner)
    assert submit_response(participant, survey).status_code == 201
    before = {name: real_db[name].count_documents({}) for name in ("users", "sessions", "surveys", "responses")}
    restarted = create_app(app.state.settings, database=real_db, clock=clock)
    with TestClient(restarted) as client:
        client.cookies.update(owner.client.cookies)
        assert client.get("/api/auth/me").status_code == 200
        assert client.get(f"/api/surveys/{survey['id']}").json()["survey"]["questions"][0]["id"] == "q1"
        stats = client.get(f"/api/surveys/{survey['id']}/statistics").json()["statistics"]
        assert stats["submissionCount"] == 1
    assert before == {name: real_db[name].count_documents({}) for name in before}


@pytest.mark.case("T68")
def test_insert_connection_failure_returns_503_then_same_key_can_be_retried(api_factory, survey_factory, submit_response, real_db, monkeypatch):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner)
    def disconnected(db, response):
        raise AutoReconnect("injected transient insert failure")
    with monkeypatch.context() as context:
        context.setattr(response_service.repository, "insert_response", disconnected)
        failed = submit_response(participant, survey, key="retry-me")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "response" not in failed.json() and real_db.responses.count_documents({}) == 0
    retried = submit_response(participant, survey, key="retry-me")
    assert retried.status_code == 201 and real_db.responses.count_documents({}) == 1

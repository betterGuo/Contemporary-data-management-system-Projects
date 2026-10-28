"""Cross-survey statistics preserve version, instance and ownership boundaries."""
from decimal import Decimal
from uuid import uuid4

from bson import ObjectId
import pytest

from app.services.cross_survey_statistics import cross_statistics
from app.services import statistics_scope
from app.services.storage_adapters import DomainError


pytestmark = pytest.mark.integration


def library_version(api, raw=None):
    raw = raw or {"type": "number", "title": "年龄", "required": False, "options": [], "validation": {"integerOnly": False}}
    result = api.write("POST", "/api/library-questions", {"content": raw, "visibility": "private", "requestKey": str(uuid4())})
    assert result.status_code in (200, 201), result.text
    question = result.json()["question"]
    saved = api.write("POST", f"/api/library-questions/{question['id']}/versions", {
        "revision": question["revision"], "sourceVersionId": None, "content": raw,
        "requestKey": str(uuid4()), "reason": "统计测试首版",
    })
    assert saved.status_code in (200, 201), saved.text
    question = saved.json()["question"]
    return question, question["latestVersionId"]


def bound_survey(api, survey_factory, version_id, *, twice=False, **settings):
    survey = survey_factory(api, questions=[], publish=False, allowMultipleSubmissions=True, allowAnonymous=True, **settings)
    for _ in range(2 if twice else 1):
        selected = api.write("POST", f"/api/surveys/{survey['id']}/library-instances", {
            "revision": survey["revision"], "versionId": version_id, "requestKey": str(uuid4()),
        })
        assert selected.status_code in (200, 201), selected.text
        survey = selected.json()["survey"]
    published = api.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert published.status_code == 200, published.text
    return published.json()["survey"]


def get_stats(api, question, version_id, **params):
    response = api.get(f"/api/library-questions/{question['id']}/statistics", params={"versionId": version_id, **params})
    assert response.status_code == 200, response.text
    return response.json()["statistics"]


@pytest.mark.case("S2-45", "S2-48", "S2-49", "S2-73")
def test_numeric_combination_zero_duplicates_and_within_survey_anonymous_accounts(
    api_factory, survey_factory, submit_response,
):
    owner, person = api_factory(), api_factory()
    question, version_id = library_version(owner)
    a = bound_survey(owner, survey_factory, version_id)
    b = bound_survey(owner, survey_factory, version_id, twice=True)
    a_id = a["questions"][0]["id"]
    b_first, b_second = [q["id"] for q in b["questions"]]
    assert submit_response(person, a, {a_id: "0"}, anonymous=True).status_code == 201
    assert submit_response(person, a, {a_id: "20"}, anonymous=False).status_code == 201
    assert submit_response(person, b, {b_first: "40", b_second: "60"}, anonymous=True).status_code == 201
    result = get_stats(owner, question, version_id)
    assert result["answerCount"] == 4 and result["responseCount"] == 3 and result["surveyCount"] == 2
    assert Decimal(result["average"]) == 30
    assert (result["min"], result["max"]) == ("0", "60")
    assert result["distribution"] == [{"value": v, "count": 1} for v in ("0", "20", "40", "60")]
    assert [r["respondentCount"] for r in result["bySurvey"]] == [1, 1]
    assert "respondentCount" not in result
    assert "values" not in result and "answers" not in result


@pytest.mark.case("S2-46", "S2-63")
def test_foreign_answers_and_all_downstream_statistics_respect_single_scope(
    api_factory, survey_factory, submit_response, real_db, monkeypatch,
):
    owner, other, person = api_factory(), api_factory(), api_factory()
    question, version_id = library_version(owner)
    a = bound_survey(owner, survey_factory, version_id)
    b = bound_survey(owner, survey_factory, version_id)
    latest = owner.get(f"/api/library-questions/{question['id']}").json()["question"]
    shared = owner.write("POST", f"/api/library-questions/{question['id']}/grants", {
        "revision": latest["revision"], "username": other.user["username"],
    })
    assert shared.status_code in (200, 201), shared.text
    foreign = bound_survey(other, survey_factory, version_id)
    for survey, value in ((a, "0"), (b, "20"), (foreign, "999")):
        assert submit_response(person, survey, {survey["questions"][0]["id"]: value}).status_code == 201
    result = get_stats(owner, question, version_id)
    assert result["answerCount"] == 2 and Decimal(result["average"]) == 10
    assert {r["surveyId"] for r in result["bySurvey"]} == {a["id"], b["id"]}
    monkeypatch.setattr(statistics_scope, "resolve_statistics_scope", lambda db, user: {"ownerId": user["_id"], "_id": ObjectId(a["id"])})
    actor = real_db.users.find_one({"_id": ObjectId(owner.user["id"])})
    restricted = cross_statistics(real_db, actor, question["id"], version_id)
    assert restricted["answerCount"] == restricted["responseCount"] == restricted["surveyCount"] == 1
    assert restricted["average"] == "0"
    assert restricted["distribution"] == [{"value": "0", "count": 1}]


@pytest.mark.case("S2-47", "S2-54")
def test_versions_are_separate_and_archived_source_does_not_hide_own_answers(
    api_factory, survey_factory, submit_response,
):
    owner, person = api_factory(), api_factory()
    question, v1 = library_version(owner)
    a = bound_survey(owner, survey_factory, v1)
    latest = owner.get(f"/api/library-questions/{question['id']}").json()["question"]
    content = {"type": "number", "title": "年龄新规则", "required": False, "options": [], "validation": {"integerOnly": True}}
    new = owner.write("POST", f"/api/library-questions/{question['id']}/versions", {
        "revision": latest["revision"], "sourceVersionId": v1, "content": content,
        "requestKey": str(uuid4()), "reason": "新版隔离",
    })
    assert new.status_code in (200, 201), new.text
    question = new.json()["question"]
    b = bound_survey(owner, survey_factory, question["latestVersionId"])
    for survey, value in ((a, "10"), (b, "80")):
        assert submit_response(person, survey, {survey["questions"][0]["id"]: value}).status_code == 201
    independent, independent_version = library_version(owner)
    independent_survey = bound_survey(owner, survey_factory, independent_version)
    assert submit_response(person, independent_survey, {independent_survey["questions"][0]["id"]: "999"}).status_code == 201
    derived = owner.write("POST", f"/api/library-questions/{question['id']}/derive", {
        "versionId": v1, "requestKey": str(uuid4()),
    })
    assert derived.status_code in (200, 201), derived.text
    variant = derived.json()["question"]
    assert variant["rootQuestionId"] == question["rootQuestionId"] and variant["id"] != question["id"]
    variant_survey = bound_survey(owner, survey_factory, variant["latestVersionId"])
    assert submit_response(person, variant_survey, {variant_survey["questions"][0]["id"]: "888"}).status_code == 201
    assert get_stats(owner, question, v1)["average"] == "10"
    latest = owner.get(f"/api/library-questions/{question['id']}").json()["question"]
    archived = owner.write("POST", f"/api/library-questions/{question['id']}/archive", {"revision": latest["revision"]})
    assert archived.status_code == 200, archived.text
    assert get_stats(owner, question, v1)["average"] == "10"


@pytest.mark.case("S2-45", "S2-74")
@pytest.mark.parametrize("kind", ["single", "multiple", "text"])
def test_non_numeric_summaries_and_no_cross_response_detail(
    kind, api_factory, survey_factory, submit_response,
):
    owner, person = api_factory(), api_factory()
    content = {"type": kind, "title": "汇总", "required": False,
               "options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}] if kind != "text" else [],
               "validation": {}}
    question, vid = library_version(owner, content)
    a = bound_survey(owner, survey_factory, vid)
    b = bound_survey(owner, survey_factory, vid)
    values = {"single": ["x", "y"], "multiple": [["x", "y"], ["y"]], "text": ["secret-text-one", "secret-text-two"]}[kind]
    for survey, value in zip((a, b), values):
        assert submit_response(person, survey, {survey["questions"][0]["id"]: value}).status_code == 201
    result = get_stats(owner, question, vid)
    assert result["answerCount"] == result["responseCount"] == 2
    if kind == "text":
        assert result["distinctValueCount"] == 2
        assert "secret-text" not in str(result)
    else:
        assert {o["id"]: o["count"] for o in result["options"]} == {"x": 1, "y": 2 if kind == "multiple" else 1}
    assert "values" not in result and result["distribution"] == []


@pytest.mark.case("S2-41", "S2-42")
def test_unmapped_answered_definition_errors_but_unanswered_draft_does_not(
    api_factory, survey_factory, submit_response, real_db,
):
    owner, person = api_factory(), api_factory()
    question, vid = library_version(owner)
    a = bound_survey(owner, survey_factory, vid)
    assert submit_response(person, a, {a["questions"][0]["id"]: "4"}).status_code == 201
    survey_factory(owner, questions=[], publish=False)
    assert get_stats(owner, question, vid)["answerCount"] == 1
    real_db.surveys.update_one({"_id": ObjectId(a["id"])}, {"$unset": {"questionRefs": ""}})
    failed = owner.get(f"/api/library-questions/{question['id']}/statistics", params={"versionId": vid})
    assert failed.status_code == 409 and failed.json()["error"]["code"] == "MIGRATION_INCOMPLETE"


@pytest.mark.case("S2-50")
def test_extreme_decimal_average_keeps_cancellation_residual(
    api_factory, survey_factory, submit_response,
):
    owner, person = api_factory(), api_factory()
    question, vid = library_version(owner)
    a = bound_survey(owner, survey_factory, vid)
    for value in ("1e40", "1", "-1e40"):
        assert submit_response(person, a, {a["questions"][0]["id"]: value}).status_code == 201
    result = get_stats(owner, question, vid)
    assert Decimal(result["average"]) == Decimal("0." + "3" * 34)
    assert result["distribution"] == [{"value": "-10000000000000000000000000000000000000000", "count": 1},
                                      {"value": "1", "count": 1},
                                      {"value": "10000000000000000000000000000000000000000", "count": 1}]


@pytest.mark.case("S2-51")
def test_new_response_during_aggregates_enters_next_statistics_request_only(
    api_factory, survey_factory, submit_response, real_db, monkeypatch,
):
    from pymongo.collection import Collection

    owner, person = api_factory(), api_factory()
    question, vid = library_version(owner)
    survey = bound_survey(owner, survey_factory, vid)
    instance = survey["questions"][0]["id"]
    assert submit_response(person, survey, {instance: "10"}).status_code == 201
    original = Collection.aggregate
    inserted = False

    def insert_between_membership_and_aggregation(collection, pipeline, *args, **kwargs):
        nonlocal inserted
        if collection.full_name == real_db.responses.full_name and not inserted:
            inserted = True
            assert submit_response(person, survey, {instance: "30"}).status_code == 201
        return original(collection, pipeline, *args, **kwargs)

    monkeypatch.setattr(Collection, "aggregate", insert_between_membership_and_aggregation)
    first = get_stats(owner, question, vid)
    assert inserted and first["answerCount"] == first["responseCount"] == 1
    assert first["average"] == "10" and first["distribution"] == [{"value": "10", "count": 1}]
    updated = get_stats(owner, question, vid)
    assert updated["answerCount"] == updated["responseCount"] == 2
    assert updated["average"] == "20"


@pytest.mark.case("S2-53")
def test_cross_statistics_filter_resource_limit_is_explicit(
    api_factory, survey_factory, submit_response, monkeypatch,
):
    from app.services import cross_survey_statistics

    owner, person = api_factory(), api_factory()
    question, vid = library_version(owner)
    survey = bound_survey(owner, survey_factory, vid)
    assert submit_response(person, survey, {survey["questions"][0]["id"]: "0"}).status_code == 201
    monkeypatch.setattr(cross_survey_statistics, "MAX_FILTER_BYTES", 1)
    response = owner.get(f"/api/library-questions/{question['id']}/statistics", params={"versionId": vid})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STATISTICS_TOO_LARGE"


@pytest.mark.case("S2-73")
def test_missing_historical_account_key_is_unknown_not_an_invented_person_count(
    api_factory, survey_factory, submit_response, real_db,
):
    owner, person = api_factory(), api_factory()
    question, vid = library_version(owner)
    survey = bound_survey(owner, survey_factory, vid)
    assert submit_response(person, survey, {survey["questions"][0]["id"]: "4"}, anonymous=True).status_code == 201
    # Deliberate damaged historical fixture, never a production write path.
    real_db.responses.update_many({}, {"$unset": {"respondentKey": ""}}, bypass_document_validation=True)
    result = get_stats(owner, question, vid)
    assert result["answerCount"] == 1 and result["bySurvey"][0]["respondentCount"] is None


@pytest.mark.case("S2-20", "S2-54")
def test_revoked_source_access_does_not_remove_statistics_of_own_held_snapshot(
    api_factory, survey_factory, submit_response,
):
    creator, receiver, person = api_factory(), api_factory(), api_factory()
    question, vid = library_version(creator)
    granted = creator.write("POST", f"/api/library-questions/{question['id']}/grants", {
        "revision": question["revision"], "username": receiver.user["username"],
    })
    assert granted.status_code in (200, 201), granted.text
    survey = bound_survey(receiver, survey_factory, vid)
    assert submit_response(person, survey, {survey["questions"][0]["id"]: "42"}).status_code == 201
    grants = creator.get(f"/api/library-questions/{question['id']}/grants").json()["grants"]
    latest = creator.get(f"/api/library-questions/{question['id']}").json()["question"]
    revoked = creator.write("DELETE", f"/api/library-questions/{question['id']}/grants/{grants[0]['id']}", {"revision": latest["revision"]})
    assert revoked.status_code == 200, revoked.text
    assert receiver.get(f"/api/library-questions/{question['id']}").status_code == 404
    result = get_stats(receiver, question, vid)
    assert result["answerCount"] == 1 and result["average"] == "42"
    assert get_stats(creator, question, vid)["answerCount"] == 0

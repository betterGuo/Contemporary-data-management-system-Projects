from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from bson import ObjectId
import pytest

from app.services.definition_service import load_definition
from app.services import statistics_service
from scripts.migrate import run_example
from scripts.seed_demo import statistics_questions


pytestmark = pytest.mark.integration


def by_question(overview):
    return {row["questionId"]: row for row in overview["questions"]}


def option_counts(question):
    return {row["id"]: row["count"] for row in question["options"]}


@pytest.mark.case("T69", "T70", "T71", "T72", "T76", "T77")
def test_four_response_statistics_match_hand_calculation_and_pages_are_complete(api_factory, survey_factory, submit_response):
    owner = api_factory()
    participants = [api_factory() for _ in range(4)]
    survey = survey_factory(owner, statistics_questions())
    rows = [("A", ["X", "Y"], "0", "甲"), ("B", ["Y", "Z"], "40", "乙"),
            ("A", ["X", "Y", "Z"], "80", "丙"), ("A", ["Y"], "120", "丁")]
    for participant, values in zip(participants, rows):
        payload = dict(zip(["stage", "places", "age", "comment"], values))
        result = submit_response(participant, survey, payload)
        assert result.status_code == 201, result.text
    path = f"/api/surveys/{survey['id']}/statistics"
    result = owner.get(path)
    assert result.status_code == 200
    overview = result.json()["statistics"]
    questions = by_question(overview)
    assert overview["submissionCount"] == overview["respondentCount"] == 4
    assert option_counts(questions["stage"]) == {"A": 3, "B": 1}
    assert questions["stage"]["answerCount"] == questions["stage"]["respondentCount"] == 4
    assert option_counts(questions["places"]) == {"X": 2, "Y": 4, "Z": 2}
    assert questions["age"]["answerCount"] == 4 and Decimal(questions["age"]["average"]) == 60
    for qid in questions:
        single = owner.get(f"/api/surveys/{survey['id']}/questions/{qid}/statistics").json()["statistics"]
        assert single == questions[qid]
    first = owner.get(f"/api/surveys/{survey['id']}/questions/comment/statistics?page=1&pageSize=2").json()["statistics"]
    second = owner.get(f"/api/surveys/{survey['id']}/questions/comment/statistics?page=2&pageSize=2").json()["statistics"]
    assert first["totalValues"] == second["totalValues"] == 4
    assert [row["value"] for row in first["values"] + second["values"]] == ["甲", "乙", "丙", "丁"]
    assert len({row["responseId"] for row in first["values"] + second["values"]}) == 4
    fifth = api_factory()
    assert submit_response(fifth, survey, {"stage": "B", "places": ["X"], "age": "60", "comment": "戊"}).status_code == 201
    updated = owner.get(path).json()["statistics"]
    updated_questions = by_question(updated)
    assert updated["submissionCount"] == 5
    assert option_counts(updated_questions["stage"]) == {"A": 3, "B": 2}
    assert option_counts(updated_questions["places"]) == {"X": 3, "Y": 4, "Z": 2}
    assert Decimal(updated_questions["age"]["average"]) == 60


@pytest.mark.case("T73", "T74", "T79")
def test_empty_stats_skips_optional_blanks_and_zero_are_counted_correctly(api_factory, survey_factory, submit_response, real_db):
    owner, participant = api_factory(), api_factory()
    questions = [
        {"id": "branch", "type": "single", "title": "分支", "required": True,
         "options": [{"id": "skip", "label": "跳过"}, {"id": "continue", "label": "继续"}],
         "jumpRules": [{"id": "skip-number", "operator": "eq", "value": "skip", "targetQuestionId": "optional"}]},
        {"id": "number", "type": "number", "title": "数字"},
        {"id": "optional", "type": "text", "title": "可选文字"},
    ]
    survey = survey_factory(owner, questions, allowMultipleSubmissions=True)
    url = f"/api/surveys/{survey['id']}/statistics"
    empty = owner.get(url).json()["statistics"]
    assert empty["submissionCount"] == 0
    assert by_question(empty)["number"]["average"] is None
    assert option_counts(by_question(empty)["branch"]) == {"skip": 0, "continue": 0}
    preview = owner.get(f"/api/surveys/{survey['id']}/preview")
    assert preview.status_code == 200 and preview.json()["isPreview"] is True
    assert real_db.responses.count_documents({}) == 0
    assert submit_response(participant, survey, {"branch": "unknown"}).status_code == 422
    assert real_db.responses.count_documents({}) == 0
    assert submit_response(participant, survey, {"branch": "skip", "optional": ""}, key="skipped").status_code == 201
    after_skip = by_question(owner.get(url).json()["statistics"])
    assert after_skip["number"]["answerCount"] == 0 and after_skip["number"]["average"] is None
    assert after_skip["optional"]["answerCount"] == 0
    assert submit_response(participant, survey, {"branch": "continue", "number": "0", "optional": None}, key="zero").status_code == 201
    assert submit_response(participant, survey, {"branch": "continue", "number": "0", "optional": ""}, key="zero").status_code == 200
    final = owner.get(url).json()["statistics"]
    assert final["submissionCount"] == 2
    number = by_question(final)["number"]
    assert number["answerCount"] == 1 and Decimal(number["average"]) == 0
    assert number["values"][0]["value"] == "0"


@pytest.mark.case("T75")
def test_repeat_answer_counts_and_distinct_people_are_not_confused(api_factory, survey_factory, submit_response):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner, allowMultipleSubmissions=True)
    for value in ("a", "a", "b"):
        assert submit_response(participant, survey, {"q1": value}).status_code == 201
    stats = owner.get(f"/api/surveys/{survey['id']}/statistics").json()["statistics"]
    assert stats["submissionCount"] == 3 and stats["respondentCount"] == 1
    single = stats["questions"][0]
    assert single["answerCount"] == 3 and single["respondentCount"] == 1
    options = {row["id"]: row for row in single["options"]}
    assert options["a"]["count"] == 2 and options["a"]["respondentCount"] == 1
    assert options["b"]["count"] == 1 and options["b"]["respondentCount"] == 1


@pytest.mark.case("T71", "T88")
def test_mean_of_two_maximum_decimal128_values_stays_finite(api_factory, survey_factory, submit_response):
    owner, participant = api_factory(), api_factory()
    questions = [{"id": "number", "type": "number", "title": "极大精确数字", "required": True}]
    survey = survey_factory(owner, questions, allowMultipleSubmissions=True)
    maximum = "9.999999999999999999999999999999999E+6144"
    for _ in range(2):
        assert submit_response(participant, survey, {"number": maximum}).status_code == 201
    result = owner.get(f"/api/surveys/{survey['id']}/questions/number/statistics")
    assert result.status_code == 200
    average = Decimal(result.json()["statistics"]["average"])
    assert average.is_finite() and average == Decimal(maximum)


@pytest.mark.case("T71", "T88")
def test_average_retains_small_residual_after_large_positive_negative_cancellation(api_factory, survey_factory, submit_response):
    owner, participant = api_factory(), api_factory()
    questions = [{"id": "number", "type": "number", "title": "正负数平均", "required": True}]
    survey = survey_factory(owner, questions, allowMultipleSubmissions=True)
    for value in ("1e40", "1", "-1e40"):
        assert submit_response(participant, survey, {"number": value}).status_code == 201
    result = owner.get(f"/api/surveys/{survey['id']}/questions/number/statistics")
    assert result.status_code == 200
    assert Decimal(result.json()["statistics"]["average"]) == Decimal("0." + "3" * 34)


@pytest.mark.case("T86", "E04", "T62")
def test_explicit_versions_historical_replay_and_retired_version_new_submission(api_factory, survey_factory, submit_response, real_db):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner, allowMultipleSubmissions=True)
    definition = participant.get(f"/api/participation/{survey['publicId']}").json()["survey"]
    assert definition["definitionVersion"] == 1
    initial = submit_response(participant, survey, key="original-v1")
    assert initial.status_code == 201 and initial.json()["response"]["definitionVersion"] == 1
    old = deepcopy(real_db.surveys.find_one({"_id": ObjectId(survey["id"]) }))
    old.pop("_id")
    old["surveyId"] = ObjectId(survey["id"])
    real_db.survey_versions.insert_one(old)
    new_questions = [{"id": "new", "type": "single", "title": "新版题目", "required": True,
                      "options": [{"id": "different", "label": "新版选项"}]}]
    real_db.surveys.update_one({"_id": ObjectId(survey["id"])}, {"$set": {"definitionVersion": 2, "questions": new_questions}})
    historical = load_definition(real_db, ObjectId(survey["id"]), 1)
    assert historical["questions"][0]["id"] == "q1"
    assert historical["questions"][0]["options"][0]["label"] == "A"
    replay = submit_response(participant, survey, key="original-v1", version=1)
    assert replay.status_code == 200
    assert replay.json()["response"] == initial.json()["response"]
    assert submit_response(participant, survey, key="new-request-v1", version=1).status_code == 409
    assert submit_response(participant, survey, key="unknown-version", version=999).status_code == 409
    missing_version = participant.write("POST", f"/api/participation/{survey['publicId']}/responses",
                                        {"submissionKey": "missing-version", "isAnonymous": False, "answers": []})
    assert missing_version.status_code == 422
    v2 = participant.get(f"/api/participation/{survey['publicId']}").json()["survey"]
    assert v2["definitionVersion"] == 2
    assert submit_response(participant, v2, {"new": "different"}, version=2).status_code == 201
    records = list(real_db.responses.find({}).sort("submittedAt", 1))
    assert {record["surveyDefinitionVersion"] for record in records} == {1, 2}
    original = real_db.responses.find_one({"submissionKey": "original-v1"})
    assert original["answers"][0]["questionId"] == "q1"


@pytest.mark.case("E03")
def test_optional_field_migration_dry_run_idempotency_and_unchanged_statistics(api_factory, survey_factory, submit_response, real_db):
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner)
    assert submit_response(participant, survey).status_code == 201
    url = f"/api/surveys/{survey['id']}/statistics"
    baseline = owner.get(url).json()
    count = real_db.responses.count_documents({})
    assert run_example(real_db) == {"dryRun": True, "wouldUpdate": 1, "modified": 0}
    assert "displayHint" not in real_db.surveys.find_one({})
    assert real_db.schema_migrations.count_documents({"_id": "exercise_optional_display_hint"}) == 0
    assert run_example(real_db, apply=True) == {"dryRun": False, "wouldUpdate": 1, "modified": 1}
    first_record = real_db.schema_migrations.find_one({"_id": "exercise_optional_display_hint"})
    assert first_record and real_db.surveys.find_one({})["displayHint"] == ""
    assert run_example(real_db, apply=True) == {"dryRun": False, "wouldUpdate": 0, "modified": 0}
    assert real_db.schema_migrations.find_one({"_id": "exercise_optional_display_hint"}) == first_record
    assert real_db.responses.count_documents({}) == count
    assert owner.get(url).json() == baseline
    with pytest.raises(ValueError, match="隔离库"):
        run_example(SimpleNamespace(name="not_a_test_database"), apply=True)


@pytest.mark.case("T69", "T70", "T71", "T72", "T76", "T77")
@pytest.mark.parametrize("scope", ["overview", "age", "comment"])
def test_statistics_freeze_response_members_before_totals_then_include_new_submission_on_next_request(
    api_factory, survey_factory, submit_response, real_db, monkeypatch, scope,
):
    """Insert through the real API at an exact boundary, without timing sleeps."""
    owner, participant = api_factory(), api_factory()
    survey = survey_factory(owner, statistics_questions(), allowMultipleSubmissions=True)
    first = {"stage": "A", "places": ["X"], "age": "0", "comment": "甲"}
    second = {"stage": "B", "places": ["Y"], "age": "120", "comment": "乙"}
    assert submit_response(participant, survey, first, key="before-statistics").status_code == 201
    original_totals = statistics_service.totals
    inserted = []

    def insert_after_totals(*args, **kwargs):
        result = original_totals(*args, **kwargs)
        if not inserted:
            response = submit_response(participant, survey, second, key="during-statistics")
            assert response.status_code == 201, response.text
            inserted.append(response.json()["response"]["id"])
        return result

    base = f"/api/surveys/{survey['id']}"
    path = base + "/statistics" if scope == "overview" else base + f"/questions/{scope}/statistics"
    with monkeypatch.context() as context:
        context.setattr(statistics_service, "totals", insert_after_totals)
        response = owner.get(path + "?pageSize=2")
    assert response.status_code == 200, response.text
    current = response.json()["statistics"]
    assert len(inserted) == 1 and real_db.responses.count_documents({}) == 2
    if scope == "overview":
        assert current["submissionCount"] == current["respondentCount"] == 1
        current_questions = by_question(current)
        assert option_counts(current_questions["stage"]) == {"A": 1, "B": 0}
        assert option_counts(current_questions["places"]) == {"X": 1, "Y": 0, "Z": 0}
    else:
        current_questions = {scope: current}
    for question in current_questions.values():
        assert question["answerCount"] == 1
        assert question["unansweredCount"] == 0
        assert question["totalValues"] == 1
    if "age" in current_questions:
        number = current_questions["age"]
        assert Decimal(number["average"]) == 0
        assert [value["value"] for value in number["values"]] == ["0"]
    if "comment" in current_questions:
        assert [value["value"] for value in current_questions["comment"]["values"]] == ["甲"]

    # A separate request intentionally observes the newly committed response.
    refreshed = owner.get(path + "?pageSize=2")
    assert refreshed.status_code == 200
    latest = refreshed.json()["statistics"]
    if scope == "overview":
        assert latest["submissionCount"] == 2 and latest["respondentCount"] == 1
        latest_questions = by_question(latest)
        assert option_counts(latest_questions["stage"]) == {"A": 1, "B": 1}
        assert option_counts(latest_questions["places"]) == {"X": 1, "Y": 1, "Z": 0}
    else:
        latest_questions = {scope: latest}
    for question in latest_questions.values():
        assert question["answerCount"] == question["totalValues"] == 2
        assert question["unansweredCount"] == 0
    if "age" in latest_questions:
        assert Decimal(latest_questions["age"]["average"]) == 60
        assert [value["value"] for value in latest_questions["age"]["values"]] == ["0", "120"]
    if "comment" in latest_questions:
        assert [value["value"] for value in latest_questions["comment"]["values"]] == ["甲", "乙"]


@pytest.mark.case("T71", "T72", "T76", "T77")
def test_numeric_average_uses_same_members_as_question_count_and_page_when_new_response_arrives(
    api_factory, survey_factory, submit_response, real_db, monkeypatch,
):
    owner, participant = api_factory(), api_factory()
    question = {"id": "number", "type": "number", "title": "均值一致", "required": True}
    survey = survey_factory(owner, [question], allowMultipleSubmissions=True)
    assert submit_response(participant, survey, {"number": "0"}, key="before-average").status_code == 201
    original_average = statistics_service.exact_numeric_average
    inserted = []

    def insert_before_numeric_scan(*args, **kwargs):
        if not inserted:
            response = submit_response(participant, survey, {"number": "120"}, key="during-average")
            assert response.status_code == 201, response.text
            inserted.append(True)
        return original_average(*args, **kwargs)

    path = f"/api/surveys/{survey['id']}/questions/number/statistics?pageSize=2"
    with monkeypatch.context() as context:
        context.setattr(statistics_service, "exact_numeric_average", insert_before_numeric_scan)
        response = owner.get(path)
    assert response.status_code == 200, response.text
    current = response.json()["statistics"]
    assert inserted and real_db.responses.count_documents({}) == 2
    assert current["answerCount"] == current["totalValues"] == 1
    assert current["unansweredCount"] == 0 and Decimal(current["average"]) == 0
    assert [value["value"] for value in current["values"]] == ["0"]
    latest = owner.get(path).json()["statistics"]
    assert latest["answerCount"] == latest["totalValues"] == 2
    assert Decimal(latest["average"]) == 60
    assert [value["value"] for value in latest["values"]] == ["0", "120"]

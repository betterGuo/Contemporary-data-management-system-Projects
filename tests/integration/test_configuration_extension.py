"""E01: configuration changes through real APIs preserve the published baseline."""

from copy import deepcopy

from bson import BSON, ObjectId
import pytest


pytestmark = pytest.mark.integration


def baseline_questions():
    return [
        {
            "id": "q1", "type": "single", "title": "参与路径", "required": True,
            "options": [{"id": "continue", "label": "继续"}, {"id": "stop", "label": "结束"}],
            "jumpRules": [{"id": "stop-rule", "operator": "eq", "value": "stop", "targetQuestionId": "END"}],
        },
        {
            "id": "q2", "type": "number", "title": "年龄", "required": True,
            "validation": {"minValue": "0", "maxValue": "120", "integerOnly": True},
            "jumpRules": [{"id": "adult-rule", "operator": "gte", "value": "18", "targetQuestionId": "q4"}],
        },
        {"id": "q3", "type": "text", "title": "补充说明", "required": True, "validation": {"minLength": 1}},
        {
            "id": "q4", "type": "single", "title": "确认", "required": True,
            "options": [{"id": "ok", "label": "确认完成"}],
        },
    ]


@pytest.mark.case("E01", "T39", "T43", "T48", "T53")
def test_api_configuration_changes_options_threshold_and_target_without_mutating_published_baseline(
    api_factory, survey_factory, submit_response, real_db,
):
    owner, participant = api_factory(), api_factory()
    original = survey_factory(owner, baseline_questions(), title="E01原发布问卷")
    original_id = ObjectId(original["id"])
    old_submission = submit_response(
        participant, original, {"q1": "continue", "q2": "20", "q4": "ok"}, key="e01-original",
    )
    assert old_submission.status_code == 201, old_submission.text
    old_response_id = ObjectId(old_submission.json()["response"]["id"])
    old_response = real_db.responses.find_one({"_id": old_response_id})
    assert old_response["visitedQuestionIds"] == ["q1", "q2", "q4"]

    # Capture actual BSON and public statistics, not just Python input fixtures.
    old_definition_bson = BSON.encode(real_db.surveys.find_one({"_id": original_id}))
    old_answer_bson = BSON.encode(old_response)
    old_statistics = owner.get(f"/api/surveys/{original['id']}/statistics").json()
    old_response_count = real_db.responses.count_documents({"surveyId": original_id})

    draft = survey_factory(
        owner, deepcopy(original["questions"]), publish=False,
        title="E01配置扩展草稿", allowMultipleSubmissions=True,
    )
    changed = deepcopy(draft["questions"])
    changed[0]["options"][0]["label"] = "继续（新说明）"
    changed[0]["options"].append({"id": "fast", "label": "新增快捷支路"})
    changed[0]["jumpRules"].append(
        {"id": "fast-rule", "operator": "eq", "value": "fast", "targetQuestionId": "q3"},
    )
    changed[1]["jumpRules"][0]["value"] = "21"
    changed[1]["jumpRules"][0]["targetQuestionId"] = "END"

    saved = owner.write(
        "PATCH", f"/api/surveys/{draft['id']}",
        {"revision": draft["revision"], "questions": changed},
    )
    assert saved.status_code == 200, saved.text
    draft = saved.json()["survey"]
    assert draft["questions"][0]["options"][0]["label"] == "继续（新说明）"
    assert draft["questions"][0]["options"][-1] == {"id": "fast", "label": "新增快捷支路"}
    assert draft["questions"][1]["jumpRules"][0]["value"] == "21"
    assert draft["questions"][1]["jumpRules"][0]["targetQuestionId"] == "END"

    preview = owner.get(f"/api/surveys/{draft['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["isPreview"] is True
    assert preview.json()["survey"]["questions"] == draft["questions"]
    assert real_db.responses.count_documents({"surveyId": ObjectId(draft["id"])}) == 0

    published = owner.write(
        "POST", f"/api/surveys/{draft['id']}/publish", {"revision": draft["revision"]},
    )
    assert published.status_code == 200, published.text
    updated = published.json()["survey"]
    definition = participant.get(f"/api/participation/{updated['publicId']}")
    assert definition.status_code == 200
    assert definition.json()["survey"]["questions"] == draft["questions"]

    # 20 used to satisfy >=18 and skip q3. With >=21 it takes q3 instead.
    # 22 now goes directly to END; the newly added option reaches q3 directly.
    scenarios = [
        ({"q1": "continue", "q2": "20", "q3": "新阈值未命中", "q4": "ok"}, ["q1", "q2", "q3", "q4"]),
        ({"q1": "continue", "q2": "22"}, ["q1", "q2"]),
        ({"q1": "fast", "q3": "新增选项支路", "q4": "ok"}, ["q1", "q3", "q4"]),
    ]
    for index, (answers, expected_path) in enumerate(scenarios):
        response = submit_response(participant, updated, answers, key=f"e01-updated-{index}")
        assert response.status_code == 201, response.text
        record = real_db.responses.find_one({"_id": ObjectId(response.json()["response"]["id"])})
        assert record["visitedQuestionIds"] == expected_path
        assert [answer["questionId"] for answer in record["answers"]] == expected_path
        assert record["surveyDefinitionVersion"] == definition.json()["survey"]["definitionVersion"] == 1
    assert real_db.responses.count_documents({"surveyId": ObjectId(updated["id"])}) == 3

    assert BSON.encode(real_db.surveys.find_one({"_id": original_id})) == old_definition_bson
    assert BSON.encode(real_db.responses.find_one({"_id": old_response_id})) == old_answer_bson
    assert real_db.responses.count_documents({"surveyId": original_id}) == old_response_count == 1
    unchanged_stats = owner.get(f"/api/surveys/{original['id']}/statistics")
    assert unchanged_stats.status_code == 200
    assert unchanged_stats.json() == old_statistics

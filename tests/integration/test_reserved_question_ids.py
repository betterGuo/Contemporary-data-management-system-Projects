"""Accepted definitions must not contain IDs browsers cannot route to."""
import json

import pytest


@pytest.mark.case("T19", "T20")
@pytest.mark.parametrize("question_id", [".", "..", "line\nbreak", "null\x00id", "\ud800"])
def test_unaddressable_question_ids_fail_before_storage_without_changing_draft(
    api_factory, survey_factory, real_db, question_id,
):
    owner = api_factory()
    draft = survey_factory(owner, publish=False)
    before = list(real_db.surveys.find({}))
    body = {
        "revision": draft["revision"],
        "questions": [{"id": question_id, "type": "text", "title": "不可路由的标识"}],
    }
    # Escaped JSON also exercises a lone surrogate without a client-side UTF-8
    # encoder rejecting the request before it reaches the application's parser.
    response = owner.client.patch(
        f"/api/surveys/{draft['id']}", content=json.dumps(body, ensure_ascii=True),
        headers={"Origin": "http://testserver", "Content-Type": "application/json",
                 "X-CSRF-Token": owner.client.cookies.get("csrf_token", "")},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_DEFINITION"
    assert list(real_db.surveys.find({})) == before

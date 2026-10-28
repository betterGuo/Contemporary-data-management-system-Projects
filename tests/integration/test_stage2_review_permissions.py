"""Review regressions for unavailable-edition access and personal organization."""
from uuid import uuid4

from bson import BSON, ObjectId
import pytest


pytestmark = pytest.mark.integration


def _content(title="停用旧版的标题", label="停用旧版的选项"):
    return {"type": "single", "title": title, "required": False,
            "options": [{"id": "a", "label": label}], "validation": {}}


def _create_version(api, visibility="private"):
    created = api.write("POST", "/api/library-questions", {
        "content": _content(), "visibility": visibility, "requestKey": str(uuid4()),
    })
    assert created.status_code == 201, created.text
    question = created.json()["question"]
    saved = api.write("POST", f"/api/library-questions/{question['id']}/versions", {
        "revision": question["revision"], "sourceVersionId": None,
        "content": _content(), "requestKey": str(uuid4()),
    })
    assert saved.status_code == 201, saved.text
    return saved.json()["question"], saved.json()["version"]


def _archive(api, question_id):
    current = api.get(f"/api/library-questions/{question_id}").json()["question"]
    response = api.write("POST", f"/api/library-questions/{question_id}/archive", {
        "revision": current["revision"],
    })
    assert response.status_code == 200, response.text


def _stop_version(api, question_id, version):
    response = api.write("POST", f"/api/library-questions/{question_id}/versions/{version['id']}/availability", {
        "revision": version["revision"], "selectable": False,
    })
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("visibility", ["private", "public"])
def test_stopped_version_statistics_require_maintenance_or_an_owned_snapshot(
    api_factory, survey_factory, submit_response, real_db, visibility,
):
    owner, holder, outsider = api_factory(), api_factory(), api_factory()
    if visibility == "public":
        real_db.users.update_one({"_id": ObjectId(owner.user["id"])}, {"$set": {"role": "admin"}})
    question, old = _create_version(owner, visibility)
    if visibility == "private":
        for receiver in (holder, outsider):
            current = owner.get(f"/api/library-questions/{question['id']}").json()["question"]
            granted = owner.write("POST", f"/api/library-questions/{question['id']}/grants", {
                "revision": current["revision"], "username": receiver.user["username"],
            })
            assert granted.status_code == 200, granted.text
    survey = survey_factory(holder, questions=[], publish=False)
    selected = holder.write("POST", f"/api/surveys/{survey['id']}/library-instances", {
        "revision": survey["revision"], "versionId": old["id"], "requestKey": str(uuid4()),
    })
    assert selected.status_code == 201, selected.text
    survey = selected.json()["survey"]
    published = holder.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
    assert published.status_code == 200, published.text
    survey = published.json()["survey"]
    assert submit_response(holder, survey, {survey["questions"][0]["id"]: "a"}).status_code == 201
    current = owner.get(f"/api/library-questions/{question['id']}").json()["question"]
    new = owner.write("POST", f"/api/library-questions/{question['id']}/versions", {
        "revision": current["revision"], "sourceVersionId": old["id"],
        "content": _content("当前可选版", "当前选项"), "requestKey": str(uuid4()),
    })
    assert new.status_code == 201, new.text
    _stop_version(owner, question["id"], old)
    path = f"/api/library-questions/{question['id']}"
    assert outsider.get(path + f"/versions/{old['id']}").status_code == 404
    assert [v["id"] for v in outsider.get(path + "/versions").json()["versions"]] == [new.json()["version"]["id"]]
    maintenance = owner.get(path + "/statistics", params={"versionId": old["id"]})
    assert maintenance.status_code == 200, maintenance.text
    held = holder.get(path + "/statistics", params={"versionId": old["id"]})
    assert held.status_code == 200, held.text
    summary = held.json()["statistics"]
    assert summary["answerCount"] == 1 and summary["options"] == [{"id": "a", "label": "停用旧版的选项", "count": 1}]
    denied = outsider.get(path + "/statistics", params={"versionId": old["id"]})
    assert denied.status_code == 404, denied.text
    assert "停用旧版" not in denied.text


@pytest.mark.parametrize("stop", ["archive", "version"])
def test_existing_owner_bookmark_can_change_only_its_tags_after_source_stops(
    api_factory, real_db, stop,
):
    owner = api_factory()
    question, version = _create_version(owner)
    body = {"questionId": question["id"], "versionId": version["id"], "tags": ["原标签"]}
    initial = owner.write("POST", "/api/question-bookmarks", body)
    assert initial.status_code == 200, initial.text
    source_before = real_db.question_versions.find_one({"_id": ObjectId(version["id"])})
    if stop == "archive":
        _archive(owner, question["id"])
    else:
        _stop_version(owner, question["id"], version)
    changed = owner.write("POST", "/api/question-bookmarks", {**body, "tags": ["整理后标签"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["question"]["bookmarkTags"] == ["整理后标签"]
    bookmark = real_db.question_bookmarks.find_one({"userId": ObjectId(owner.user["id"]), "questionId": ObjectId(question["id"])})
    assert bookmark["selectedVersionId"] == ObjectId(version["id"])
    assert real_db.question_versions.find_one({"_id": ObjectId(version["id"])}) == source_before


@pytest.mark.parametrize("include_version", [False, True])
def test_archived_question_rejects_new_bookmark_but_keeps_old_organization(
    api_factory, real_db, include_version,
):
    owner = api_factory()
    question, version = _create_version(owner)
    # Creation adds an owner bookmark. Remove it before testing a new acquisition.
    removed = owner.write("DELETE", f"/api/question-bookmarks/{question['id']}")
    assert removed.status_code == 200, removed.text
    _archive(owner, question["id"])
    body = {"questionId": question["id"], "tags": ["新收藏"]}
    if include_version:
        body["versionId"] = version["id"]
    rejected = owner.write("POST", "/api/question-bookmarks", body)
    assert rejected.status_code == 409, rejected.text
    assert real_db.question_bookmarks.find_one({"userId": ObjectId(owner.user["id"]), "questionId": ObjectId(question["id"])}) is None


def test_unviewable_stopped_source_rolls_back_bookmark_edit_but_local_tag_rename_works(
    api_factory, real_db,
):
    owner, receiver = api_factory(), api_factory()
    question, version = _create_version(owner)
    shared = owner.write("POST", f"/api/library-questions/{question['id']}/grants", {
        "revision": question["revision"], "username": receiver.user["username"],
    })
    assert shared.status_code == 200, shared.text
    body = {"questionId": question["id"], "versionId": version["id"], "tags": ["整理前"]}
    saved = receiver.write("POST", "/api/question-bookmarks", body)
    assert saved.status_code == 200, saved.text
    _stop_version(owner, question["id"], version)
    assert receiver.get(f"/api/library-questions/{question['id']}").status_code == 404
    # This local organization action neither loads nor acquires unavailable content.
    renamed = receiver.write("POST", "/api/question-tags", {"oldTag": "整理前", "newTag": "本地已整理"})
    assert renamed.status_code == 200 and renamed.json()["modified"] == 1, renamed.text
    identity = {"userId": ObjectId(receiver.user["id"]), "questionId": ObjectId(question["id"])}
    before = real_db.question_bookmarks.find_one(identity)
    assert before["tags"] == ["本地已整理"] and before["selectedVersionId"] == ObjectId(version["id"])
    rejected = receiver.write("POST", "/api/question-bookmarks", {**body, "tags": ["不应偷偷提交"]})
    assert rejected.status_code == 404, rejected.text
    after = real_db.question_bookmarks.find_one(identity)
    assert BSON.encode(after) == BSON.encode(before), {
        "status": rejected.status_code, "beforeTags": before["tags"], "afterTags": after["tags"],
        "beforeRevision": before["revision"], "afterRevision": after["revision"],
    }

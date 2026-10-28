"""Protect real data and historical evidence during the stage-two baseline step."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from bson import ObjectId
import pytest

from scripts import backup_project
from scripts.run_tests import run


pytestmark = pytest.mark.integration


def test_actual_backup_restores_extra_collections_and_non_seed_results(
    app, real_db, api_factory, survey_factory, submit_response, tmp_path,
):
    author = api_factory()
    survey = survey_factory(author, allowMultipleSubmissions=True)
    for _ in range(5):
        assert submit_response(author, survey).status_code == 201
    current = real_db.surveys.find_one({"_id": ObjectId(survey["id"])})
    historical = copy.deepcopy(current)
    historical.update({"_id": ObjectId(), "surveyId": current["_id"], "definitionVersion": 2})
    real_db.survey_versions.insert_one(historical)
    real_db.future_library_notes.insert_one({"_id": "future-note", "content": {"title": "keep"}})
    real_db.future_library_notes.create_index("content.title", name="future_content_title")
    before = backup_project.manifest(real_db)

    report = backup_project.backup(app.state.settings, tmp_path / "actual.archive.gz")

    assert report["status"] == "passed"
    assert {"survey_versions", "future_library_notes"} <= report["collections"].keys()
    assert report["restoredDefinitionCount"] == 2
    assert next(s for s in report["sourceStatistics"] if s["kind"] == "current")["submissionCount"] == 5
    assert report["restoredStatisticsVerified"]
    assert report["temporaryRestoreDatabaseRemoved"]
    assert report["sourceUnchangedAtCompletion"]
    assert backup_project.manifest(real_db) == before


def test_backup_refuses_existing_restore_database_without_deleting_it(
    app, client, real_db, monkeypatch, tmp_path,
):
    fixed_uuid = uuid4()
    suffix = fixed_uuid.hex
    target_name = "survey_project1_test_restore_" + suffix
    target = real_db.client[target_name]
    target.keep.insert_one({"_id": "keep-existing-database"})
    # Replace this module's dependency, not uuid.uuid4 shared by PyMongo.
    monkeypatch.setattr(backup_project, "uuid", SimpleNamespace(uuid4=lambda: fixed_uuid))
    output = tmp_path / "collision.archive.gz"
    try:
        with pytest.raises(ValueError, match="恢复目标不为空"):
            backup_project.backup(app.state.settings, output)
        assert target.keep.find_one({"_id": "keep-existing-database"})
        report = json.loads(output.with_suffix(output.suffix + ".manifest.json").read_text())
        assert report["status"] == "failed" and not report["restoreVerified"]
    finally:
        real_db.client.drop_database(target_name)


def test_backup_detects_source_changes_instead_of_claiming_a_stable_baseline(
    app, client, real_db, monkeypatch, tmp_path,
):
    original_run = backup_project.subprocess.run

    def change_after_dump(args, **kwargs):
        result = original_run(args, **kwargs)
        if Path(args[0]).name == "mongodump":
            real_db.concurrent_write.insert_one({"_id": "arrived-during-backup"})
        return result

    monkeypatch.setattr(backup_project.subprocess, "run", change_after_dump)
    output = tmp_path / "changed.archive.gz"
    with pytest.raises(RuntimeError, match="备份期间源业务数据发生变化"):
        backup_project.backup(app.state.settings, output)
    assert real_db.concurrent_write.find_one({"_id": "arrived-during-backup"})
    report = json.loads(output.with_suffix(output.suffix + ".manifest.json").read_text())
    assert report["status"] == "failed" and report["phase"] == "dump"
    assert not report["restoreVerified"]


def test_test_runner_refuses_to_overwrite_historical_evidence(tmp_path, monkeypatch):
    historical = tmp_path / "test-results.json"
    historical.write_text("existing evidence\n")
    monkeypatch.setattr("scripts.run_tests.pytest.main", lambda *args, **kwargs: pytest.fail("Must not start tests when evidence already exists"))
    with pytest.raises(FileExistsError):
        run(tmp_path)
    assert historical.read_text() == "existing evidence\n"
    assert not (tmp_path / ".run-started").exists()

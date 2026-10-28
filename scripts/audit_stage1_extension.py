"""Recheck extension contracts against a restored, isolated stage-one archive.

This script never reads or writes the running project database.  It restores the
existing BSON archive into a fresh UUID database, exercises the existing
services there, records evidence, and removes only its own temporary database.
The sample changes are audit exercises, not formal second-stage requirements.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bson import BSON

from app.api.statistics import overview
from app.config import ROOT, Settings
from app.database import connect, utcnow
from app.services import response_service, statistics_service
from app.services.definition_service import load_definition
from app.services.jump_engine import validate_answers_path
from app.services.question_types import QUESTION_TYPES, register_question_type
from app.services.rule_operators import RULE_OPERATORS, register_rule_operator
from app.services.storage_adapters import DomainError, with_storage_defaults
from scripts.backup_project import manifest
from scripts.migrate import run_example
from scripts.verify_stage1 import verify


def bson_digest(collection, query=None, *, omit=()):
    digest = hashlib.sha256()
    count = 0
    for document in collection.find(query or {}).sort("_id", 1):
        for field in omit:
            document.pop(field, None)
        digest.update(BSON.encode(document))
        count += 1
    return {"count": count, "bsonSha256": digest.hexdigest()}


def production_calls(function_name):
    calls = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else ""
            )
            if name == function_name:
                calls.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return calls


def registry_exercise(db, survey):
    """Add only process-local sample handlers, then restore the registries."""
    kind = "auditStage1Rating"
    operator_key = ("number", "auditStage1Even")
    assert kind not in QUESTION_TYPES
    assert kind not in statistics_service.STATISTICS_HANDLERS
    assert operator_key not in RULE_OPERATORS

    def definition(question):
        question["validation"] = {"maxStars": 5}
        question["options"] = []
        return question

    def normalize(question, value):
        if type(value) is not int or not 1 <= value <= question["validation"]["maxStars"]:
            raise DomainError("INVALID_RATING", "演练评分必须在 1 至 5 之间")
        return value

    def statistics_handler(db_arg, survey_arg, question, count, page, page_size, response_filter):
        return {"questionId": question["id"], "registeredHandlerCalled": True}

    try:
        register_question_type(kind, definition, normalize)
        statistics_service.register_statistics_handler(kind, statistics_handler)
        question = {"id": "audit-rating", "type": kind, "title": "仅用于注册演练", "required": True}
        replay = validate_answers_path([question], [{"questionId": "audit-rating", "value": 4}])
        assert replay["answers"][0]["value"] == 4
        summary = statistics_service.question_statistics(db, survey, question, 0, response_filter={"_id": {"$in": []}})
        assert summary["registeredHandlerCalled"]

        def condition(question_arg, value):
            if value is not None:
                raise DomainError("INVALID_AUDIT_CONDITION", "演示偶数条件不接受参数")
            return None

        register_rule_operator("number", operator_key[1], condition, lambda value, unused: int(value) % 2 == 0)
        number = {"id": "audit-number", "type": "number", "title": "演示数字", "required": True,
                  "jumpRules": [{"id": "even", "operator": operator_key[1], "value": None, "targetQuestionId": "END"}]}
        tail = {"id": "audit-tail", "type": "text", "title": "后续题", "required": False}
        even = validate_answers_path([number, tail], [{"questionId": "audit-number", "value": "2"}])
        odd = validate_answers_path([number, tail], [{"questionId": "audit-number", "value": "3"}])
        assert even["visitedQuestionIds"] == ["audit-number"]
        assert odd["visitedQuestionIds"] == ["audit-number", "audit-tail"]
        return {"status": "passed", "newQuestionTypeUsesExistingTraversal": True,
                "newStatisticsHandlerDispatched": True, "newOperatorUsesExistingTraversal": True,
                "productionFeaturesAdded": False, "registriesRestoredAfterExercise": True}
    finally:
        QUESTION_TYPES.pop(kind, None)
        statistics_service.STATISTICS_HANDLERS.pop(kind, None)
        RULE_OPERATORS.pop(operator_key, None)


def audit(settings, archive_path, output):
    archive_path = Path(archive_path).resolve()
    source_manifest = json.loads(Path(str(archive_path) + ".manifest.json").read_text())
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert archive_hash == source_manifest["archiveSha256"], "归档与原始 manifest 不一致"
    target_name = "survey_project1_test_recheck_" + uuid.uuid4().hex
    # A delivered git archive intentionally contains no .git directory. The
    # immutable BSON hash is always verified; Git provenance is supplementary.
    tag_commit = None
    if (ROOT / ".git").exists():
        try:
            git_result = subprocess.run(["git", "rev-parse", "stage1-v1.0^{commit}"], cwd=ROOT,
                                        check=False, capture_output=True, text=True)
            tag_commit = git_result.stdout.strip() if git_result.returncode == 0 else None
        except FileNotFoundError:
            pass
    result = {"status": "running", "executedAt": utcnow().isoformat(), "stage1TagCommit": tag_commit,
              "gitTagVerified": tag_commit is not None,
              "archive": str(archive_path.relative_to(ROOT)) if archive_path.is_relative_to(ROOT) else str(archive_path), "archiveSha256": archive_hash,
              "archiveHashMatchesManifest": True, "databasePrefix": "survey_project1_test_recheck_",
              "runningProjectDatabaseAccessed": False, "temporaryDatabaseRemoved": False}
    with connect(settings.mongodb_uri) as client:
        db = client[target_name]
        assert not db.list_collection_names(), "恢复目标必须是全新隔离库"
        try:
            subprocess.run(["mongorestore", f"--uri={settings.mongodb_uri}", f"--archive={archive_path}",
                            "--gzip", f"--nsFrom={source_manifest['sourceDatabase']}.*", f"--nsTo={target_name}.*"],
                           check=True, capture_output=True, text=True)
            restored = manifest(db)
            assert restored == source_manifest["collections"], "恢复后的 BSON、索引或验证器不同"
            result["restoration"] = {"status": "passed", "matchesBsonCountsIndexesValidators": True,
                                     "counts": {name: row["count"] for name, row in restored.items()}}
            baseline = verify(db)
            survey = db.surveys.find_one({"demoKey": "stats"})
            assert survey and survey["definitionVersion"] == 1
            original_statistics = statistics_service.statistics(db, survey)
            users_before = bson_digest(db.users)
            responses_before = bson_digest(db.responses)
            original_response_ids = [row["_id"] for row in db.responses.find({}, {"_id": 1})]
            surveys_before = bson_digest(db.surveys)

            raw = db.surveys.find_one({})
            assert "displayHint" not in raw
            raw_bytes = BSON.encode(raw)
            adapted = with_storage_defaults(raw, {"displayHint": ""})
            assert adapted["displayHint"] == "" and BSON.encode(raw) == raw_bytes
            dry_run = run_example(db)
            assert dry_run == {"dryRun": True, "wouldUpdate": restored["surveys"]["count"], "modified": 0}
            assert bson_digest(db.surveys) == surveys_before
            first_apply = run_example(db, apply=True)
            first_record = db.schema_migrations.find_one({"_id": "exercise_optional_display_hint"})
            second_apply = run_example(db, apply=True)
            assert first_apply["modified"] == restored["surveys"]["count"]
            assert second_apply == {"dryRun": False, "wouldUpdate": 0, "modified": 0}
            assert db.schema_migrations.find_one({"_id": "exercise_optional_display_hint"}) == first_record
            assert bson_digest(db.users) == users_before
            assert bson_digest(db.responses) == responses_before
            assert bson_digest(db.surveys, omit=("displayHint",)) == surveys_before
            assert statistics_service.statistics(db, db.surveys.find_one({"_id": survey["_id"]})) == original_statistics
            try:
                run_example(SimpleNamespace(name="non_isolated_database"), apply=True)
            except ValueError:
                pass
            else:
                raise AssertionError("示例迁移未拒绝非隔离库")
            result["optionalFieldMigration"] = {"status": "passed", "source": "six real stage-one surveys",
                "dryRun": dry_run, "firstApply": first_apply, "secondApply": second_apply,
                "usersBsonUnchanged": True, "responsesBsonUnchanged": True,
                "originalSurveyCoreBsonUnchanged": True, "handCalculatedStatisticsUnchanged": True,
                "migrationRecordUnchangedOnSecondApply": True,
                "nonIsolatedDatabaseRejectedBeforeAnyDatabaseOperation": True,
                "readOnlyDefaultHelperPreservesOriginalDocument": True}

            # Simulate a future definition migration in this clone only. The
            # first-stage public editor remains correctly frozen after publish.
            survey = db.surveys.find_one({"_id": survey["_id"]})
            v1_filter = {"surveyId": survey["_id"], "surveyDefinitionVersion": 1}
            old_answers_before = bson_digest(db.responses, v1_filter)
            historical = deepcopy(survey)
            historical.pop("_id")
            historical["surveyId"] = survey["_id"]
            db.survey_versions.insert_one(historical)
            new_question = {"id": "audit-v2-note", "type": "text", "title": "仅用于兼容验证的新版题目",
                            "required": True, "options": [], "validation": {"minLength": 1, "maxLength": 2000}, "jumpRules": []}
            db.surveys.update_one({"_id": survey["_id"]}, {"$set": {"definitionVersion": 2, "questions": [new_question]}})
            current = db.surveys.find_one({"_id": survey["_id"]})
            user = db.users.find_one({"_id": current["ownerId"]})
            assert user is not None
            payload = {"definitionVersion": 2, "submissionKey": "audit-restored-v2-" + uuid.uuid4().hex,
                       "isAnonymous": True, "answers": [{"questionId": new_question["id"], "value": "仅写入恢复副本"}]}
            receipt, status = response_service.submit(db, settings, user, current["publicId"], payload, utcnow)
            assert status == 201 and receipt["response"]["definitionVersion"] == 2
            assert load_definition(db, survey["_id"], 1)["questions"] == survey["questions"]
            assert bson_digest(db.responses, v1_filter) == old_answers_before
            assert bson_digest(db.responses, {"_id": {"$in": original_response_ids}}) == responses_before
            old_result = statistics_service.statistics(db, {**current, "definitionVersion": 1})
            assert old_result == original_statistics
            latest_result = statistics_service.statistics(db, current)
            assert latest_result["submissionCount"] == 1
            assert latest_result["questions"][0]["questionId"] == new_question["id"]
            assert db.responses.count_documents({}) == responses_before["count"] + 1
            assert bson_digest(db.users) == users_before
            result["definitionCompatibility"] = {"status": "passed", "existingSurveyIdPreserved": True,
                "historicalV1QuestionAndOptionDefinitionsUnchanged": True,
                "allOriginalV1AnswersByteForByteUnchanged": True,
                "allOriginalResponsesVerified": responses_before["count"],
                "v1StatisticsExactlyMatchStageOne": True, "v1SubmissionCount": old_result["submissionCount"],
                "v2SubmissionCount": latest_result["submissionCount"], "newSubmissionStatus": status,
                "totalResponsesAfterAudit": db.responses.count_documents({}), "usersByteForByteUnchanged": True,
                "productionMultiVersionEditingEnabled": False}
            result["registries"] = registry_exercise(db, current)
            parameters = list(inspect.signature(overview).parameters)
            calls = production_calls("with_storage_defaults")
            result["currentBoundaries"] = {
                "statisticsApiUsesCurrentDefinitionVersionOnly": "definitionVersion" not in parameters,
                "historicalStatisticsAvailableThroughServiceWithExplicitVersion": True,
                "storageDefaultHelperProductionCalls": calls,
                "storageDefaultHelperHasProductionCaller": bool(calls),
                "surveyStorageAdapterProductionCalls": production_calls("from_storage_survey"),
                "newTypeEditorAndFillRendererRegistrationFunctionsPresent": all(
                    name in (ROOT / relative).read_text() for name, relative in [
                        ("export function registerQuestionEditor", "app/static/editor.js"),
                        ("export function registerFillRenderer", "app/static/fill.js"),
                        ("export function registerRuleMatcher", "app/static/engine.js")]),
                "newTypeStillRequiresItsEditorUiValidationAndStatisticsImplementation": True,
                "unknownSecondStageRequirementsImplemented": False,
            }
            result["originalBaselineChecks"] = baseline["checks"]
            result["implementationFilesSha256"] = {
                str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [ROOT / relative for relative in [
                    "app/services/storage_adapters.py", "app/services/definition_service.py",
                    "app/services/response_service.py", "app/services/question_types.py",
                    "app/services/rule_operators.py", "app/services/statistics_service.py",
                    "app/services/jump_engine.py", "app/repositories/surveys.py",
                    "app/web_utils.py", "scripts/migrate.py"]]
            }
            result["status"] = "passed"
        finally:
            if not target_name.startswith("survey_project1_test_recheck_"):
                raise ValueError("拒绝清理非本脚本隔离库")
            client.drop_database(target_name)
            result["temporaryDatabaseRemoved"] = True
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default=ROOT / "artifacts/stage1/baseline.archive.gz", type=Path)
    parser.add_argument("--output", default=ROOT / "docs/evidence/stage1/recheck-extension.json", type=Path)
    args = parser.parse_args()
    result = audit(Settings(), args.archive, args.output)
    print(json.dumps({"status": result["status"], "restoredCounts": result["restoration"]["counts"],
                      "migration": result["optionalFieldMigration"]["status"],
                      "v1StatisticsUnchanged": result["definitionCompatibility"]["v1StatisticsExactlyMatchStageOne"],
                      "v2Submissions": result["definitionCompatibility"]["v2SubmissionCount"],
                      "registries": result["registries"]["status"],
                      "temporaryDatabaseRemoved": result["temporaryDatabaseRemoved"]}, ensure_ascii=False))

"""Create BSON archive and validate restoration into a new isolated database."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bson import BSON, json_util
from app.config import ROOT, Settings
from app.database import connect


def manifest(db):
    """Fingerprint every persisted collection except replaceable login sessions."""
    result = {}
    collections = sorted(db.list_collections(), key=lambda entry: entry["name"])
    for entry in collections:
        name = entry["name"]
        if name == "sessions" or name.startswith("system."):
            continue
        if entry.get("type", "collection") != "collection":
            raise ValueError("备份核验暂不支持视图，请先明确其恢复校验方式。")
        digest = hashlib.sha256()
        count = 0
        for row in db[name].find({}).sort("_id", 1):
            digest.update(BSON.encode(row))
            count += 1
        indexes = sorted(list(db[name].list_indexes()), key=lambda row: row["name"])
        result[name] = {"count": count, "bsonSha256": digest.hexdigest(), "indexes": json.loads(json_util.dumps(indexes)), "options": json.loads(json_util.dumps(db[name].options()))}
    return result


def statistics_snapshot(db):
    """Record actual current/historical results, without exporting answer text."""
    from app.services.statistics_service import statistics

    definitions = {(row["_id"], row["definitionVersion"]): "current" for row in db.surveys.find({}, {"definitionVersion": 1})}
    for row in db.survey_versions.find({}, {"surveyId": 1, "definitionVersion": 1}):
        definitions.setdefault((row["surveyId"], row["definitionVersion"]), "historical")
    result = []
    for (survey_id, version), kind in sorted(definitions.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        stats = statistics(db, {"_id": survey_id, "definitionVersion": version})
        digest = hashlib.sha256(json.dumps(stats, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result.append({
            "surveyId": str(survey_id), "definitionVersion": version, "kind": kind,
            "statisticsSha256": digest,
            "submissionCount": stats["submissionCount"], "respondentCount": stats["respondentCount"],
            "questions": [{"instanceId": q["questionId"], "type": q["type"], "answerCount": q["answerCount"], "average": q["average"],
                           "optionCounts": [{"id": o["id"], "count": o["count"]} for o in q.get("options", [])]} for q in stats["questions"]],
        })
    return result


def backup(settings, output, verify_restore=True):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path = output.with_suffix(output.suffix + ".manifest.json")
    lock_path = output.with_suffix(output.suffix + ".in-progress")
    if output.exists() or report_path.exists():
        raise ValueError("备份文件或配套清单已存在，请使用新路径以保留旧基线。")
    with lock_path.open("x") as lock:
        lock.write("Exclusive backup reservation; existing evidence must not be overwritten.\n")
    target_db = "survey_project1_test_restore_" + uuid.uuid4().hex
    report = {"sourceDatabase": settings.mongodb_db, "archive": output.name, "sessionsExcluded": True, "restoreVerified": False, "status": "running", "phase": "source-snapshot"}
    try:
        with connect(settings.mongodb_uri) as client:
            source = client[settings.mongodb_db]
            before = manifest(source)
            if not before:
                raise ValueError("源数据库为空，拒绝把空库当作第一阶段基线。")
            source_stats = statistics_snapshot(source)
            if manifest(source) != before:
                raise RuntimeError("统计盘点期间源业务数据发生变化，请选择稳定窗口重试。")
            report.update({"collections": before, "sourceStatistics": source_stats, "phase": "dump"})
            subprocess.run(["mongodump", f"--uri={settings.mongodb_uri}", f"--db={settings.mongodb_db}", "--excludeCollection=sessions", f"--archive={output}", "--gzip"], check=True, capture_output=True, text=True)
            report["archiveSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
            if manifest(source) != before:
                raise RuntimeError("备份期间源业务数据发生变化，本次归档不声明为一致基线。")
            report["sourceUnchangedAfterDump"] = True
            if verify_restore:
                report["phase"] = "restore"
                if client[target_db].list_collection_names():
                    raise ValueError("恢复目标不为空。")
                try:
                    if not target_db.startswith("survey_project1_test_restore_") or target_db == settings.mongodb_db:
                        raise ValueError("恢复目标必须是本次生成的独立临时库。")
                    subprocess.run(["mongorestore", f"--uri={settings.mongodb_uri}", f"--archive={output}", "--gzip", f"--nsFrom={settings.mongodb_db}.*", f"--nsTo={target_db}.*"], check=True, capture_output=True, text=True)
                    after = manifest(client[target_db])
                    assert after == before, "恢复后的 BSON、数量、索引或验证器与源不一致"
                    restored_stats = statistics_snapshot(client[target_db])
                    assert restored_stats == source_stats, "恢复后的实际问卷统计与源不一致"
                    report.update({"restoreVerified": True, "restoredStatisticsVerified": True, "restoredDefinitionCount": len(restored_stats)})
                    # Do not silently upgrade a legacy layout during backup.
                    checks = {"health": "database-ping-passed", "existingAccountLogin": "not-attempted-legacy-layout", "ownSurveyList": "not-attempted-legacy-layout"}
                    if "question_versions" in before:
                        report["phase"] = "restored-application-smoke"
                        from fastapi.testclient import TestClient
                        from app.main import create_app

                        restored_settings = settings.model_copy(update={"mongodb_db": target_db, "testing": True})
                        with TestClient(create_app(restored_settings, client[target_db]), headers={"Origin": "http://testserver"}) as browser:
                            assert browser.get("/health").json()["database"] == "connected"
                            checks = {"health": "passed", "existingAccountLogin": "not-attempted", "ownSurveyList": "not-attempted"}
                            if client[target_db].users.find_one({"usernameNormalized": "demo_owner"}):
                                logged_in = browser.post("/api/auth/login", json={"username": "demo_owner", "password": "Survey2026!"})
                                if logged_in.status_code == 200:
                                    assert browser.get("/api/surveys").status_code == 200
                                    checks.update({"existingAccountLogin": "passed", "ownSurveyList": "passed"})
                                else:
                                    checks["existingAccountLogin"] = "demo-password-no-longer-valid"
                    assert manifest(client[target_db]) == before, "应用启动改变了恢复库业务数据或元数据"
                    report["restoredApplication"] = checks
                finally:
                    if not target_db.startswith("survey_project1_test_restore_") or target_db == settings.mongodb_db:
                        raise ValueError("Refusing to clean an unexpected database")
                    client.drop_database(target_db)
                report["temporaryRestoreDatabaseRemoved"] = target_db not in client.list_database_names()
                assert report["temporaryRestoreDatabaseRemoved"]
            report["sourceUnchangedAtCompletion"] = manifest(source) == before
            if not report["sourceUnchangedAtCompletion"]:
                raise RuntimeError("源业务数据在验证期间发生变化，请重新采集基线。")
        report.update({"status": "passed", "phase": "complete"})
    except Exception as error:
        report.update({"status": "failed", "errorType": type(error).__name__})
        raise
    finally:
        with report_path.open("x") as target:
            target.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        lock_path.unlink(missing_ok=True)
    private = ROOT / ".secrets"
    private.mkdir(exist_ok=True, mode=0o700)
    # Keep the HMAC identity mapping reproducible locally; excluded from Git and delivery archives.
    if (ROOT / ".env").exists():
        backup_env = private / "stage1.env"
        if not backup_env.exists():
            shutil.copyfile(ROOT / ".env", backup_env)
            backup_env.chmod(0o600)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-verify-restore", action="store_true")
    args = parser.parse_args()
    report = backup(Settings(), args.output, not args.no_verify_restore)
    print(json.dumps({"restoreVerified": report["restoreVerified"], "archive": report["archive"], "counts": {name: row["count"] for name, row in report["collections"].items()}}, ensure_ascii=False))

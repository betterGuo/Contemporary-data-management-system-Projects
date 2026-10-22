"""Verify the locked installation in a new venv and a disposable MongoDB database."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings

CHECK = r'''
import json, platform
from fastapi.testclient import TestClient
from app.config import Settings
from app.database import connect, initialize_database
from app.main import create_app
from scripts.seed_demo import seed
from scripts.verify_stage1 import verify

settings = Settings(testing=True)
assert settings.mongodb_db.startswith("survey_project1_test_reproduce_")
with connect(settings.mongodb_uri) as mongo:
    db = mongo[settings.mongodb_db]
    assert not db.list_collection_names()
    try:
        initialize_database(db)
        seed(db, settings)
        before = {name: db[name].count_documents({}) for name in ["users", "surveys", "responses"]}
        seed(db, settings)
        assert before == {name: db[name].count_documents({}) for name in before}
        baseline = verify(db)
        with TestClient(create_app(settings, db), headers={"Origin": "http://testserver"}) as client:
            assert client.get("/health").json()["database"] == "connected"
            assert client.get("/login").status_code == 200
            login = client.post("/api/auth/login", json={"username": "demo_owner", "password": "Survey2026!"})
            assert login.status_code == 200
            assert client.get("/dashboard").status_code == 200
            assert client.get("/static/editor.js").status_code == 200
            survey = db.surveys.find_one({"demoKey": "stats"})
            assert client.get(f"/api/surveys/{survey['_id']}/statistics").json()["statistics"]["submissionCount"] == 4
        result = {"status": "passed", "pythonVersion": platform.python_version(), "seedIdempotent": True, "baselineVerified": baseline["status"], "collections": before, "checks": ["new locked virtual environment", "MongoDB schema initialization", "idempotent fictional demo seed", "hand-calculated statistics", "application lifespan and health", "HTML and static assets", "login and authenticated statistics API"], "temporaryDatabaseRemoved": False}
    finally:
        mongo.drop_database(settings.mongodb_db)
    assert settings.mongodb_db not in mongo.list_database_names()
    result["temporaryDatabaseRemoved"] = True
print(json.dumps(result, ensure_ascii=False))
'''


def reproduce(output):
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("此复现脚本需要 uv；手工 Python venv 步骤见 README。")
    private = ROOT / "artifacts" / "private"
    private.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Pytest reads TEST_MONGODB_URI rather than the application's .env. Keep
    # both verification phases on the configured server unless overridden.
    env.setdefault("TEST_MONGODB_URI", Settings().mongodb_uri)
    env["MONGODB_DB"] = "survey_project1_test_reproduce_" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="reproduce-", dir=private) as directory:
        venv = Path(directory) / "venv"
        subprocess.run([uv, "venv", "--python", sys.executable, str(venv)], check=True, capture_output=True, text=True)
        python = venv / "bin" / "python"
        subprocess.run([uv, "pip", "sync", "--python", str(python), str(ROOT / "requirements.lock")], check=True, capture_output=True, text=True)
        subprocess.run([uv, "pip", "check", "--python", str(python)], check=True, capture_output=True, text=True)
        checked = subprocess.run([str(python), "-c", CHECK], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        result = json.loads(checked.stdout.splitlines()[-1])
        tests = subprocess.run([str(python), "-m", "pytest", "tests", "-q"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        result["cleanEnvironmentTests"] = {"status": "passed", "passed": int(re.search(r"(\d+) passed", tests.stdout).group(1)), "exitCode": tests.returncode}
        test_output = Path(output).parent / "reproduction-pytest-output.txt"
        test_output.parent.mkdir(parents=True, exist_ok=True)
        test_output.write_text(tests.stdout + tests.stderr)
    result["executedAt"] = datetime.now(timezone.utc).isoformat()
    result["lockedDependencyCheck"] = "passed"
    result["temporaryVenvRemoved"] = True
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/evidence/stage1/reproduction.json")
    args = parser.parse_args()
    print(json.dumps(reproduce(args.output), ensure_ascii=False))

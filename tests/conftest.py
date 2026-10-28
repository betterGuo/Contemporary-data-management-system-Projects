"""Real MongoDB fixtures. Cleanup is restricted to one generated test database."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import os
from threading import Lock
from uuid import uuid4

from fastapi.testclient import TestClient
from pymongo import MongoClient
import pytest

from app.config import Settings


TEST_DB_PREFIX = "survey_project1_test_"
ORIGIN = "http://testserver"
PASSWORD = "test-password-123"


class Clock:
    def __init__(self):
        self._value = datetime.now(timezone.utc).replace(microsecond=0)
        self._lock = Lock()

    def __call__(self):
        with self._lock:
            return self._value

    def set(self, value):
        assert value.tzinfo is not None
        with self._lock:
            self._value = value

    def advance(self, **kwargs):
        with self._lock:
            self._value += timedelta(**kwargs)


class ApiSession:
    def __init__(self, client, user=None):
        self.client = client
        self.user = user

    def write(self, method, path, body=None, *, headers=None):
        actual = {"Origin": ORIGIN, "X-CSRF-Token": self.client.cookies.get("csrf_token", "")}
        actual.update(headers or {})
        return self.client.request(method, path, json={} if body is None else body, headers=actual)

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)


@pytest.fixture(scope="session")
def mongo_client():
    client = MongoClient(
        os.environ.get("TEST_MONGODB_URI") or os.environ.get("MONGODB_URI") or Settings().mongodb_uri,
        tz_aware=True, serverSelectionTimeoutMS=2500,
    )
    try:
        client.admin.command("ping")
    except Exception as error:
        pytest.fail(f"Real MongoDB is required for integration tests: {type(error).__name__}")
    yield client
    client.close()


@pytest.fixture
def real_db(mongo_client):
    name = TEST_DB_PREFIX + uuid4().hex
    assert name.startswith(TEST_DB_PREFIX) and len(name) > len(TEST_DB_PREFIX)
    database = mongo_client[name]
    yield database
    # Never accept a main database, a user-supplied name, or a broad deletion.
    assert database.name == name and name.startswith(TEST_DB_PREFIX)
    mongo_client.drop_database(name)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app(real_db, clock, monkeypatch):
    # main.py also constructs its unstarted default app during import. Give that
    # object a test secret without reading or changing the user's .env file.
    monkeypatch.setenv("RESPONDENT_HMAC_SECRET", "test" * 16)
    from app.main import create_app

    settings = Settings(
        _env_file=None, respondent_hmac_secret="test" * 16,
        mongodb_uri=os.environ.get("TEST_MONGODB_URI") or os.environ.get("MONGODB_URI") or Settings().mongodb_uri,
        testing=True, mongodb_db=real_db.name, app_origin=ORIGIN,
    )
    return create_app(settings, database=real_db, clock=clock)


@pytest.fixture
def client_factory(app):
    with ExitStack() as stack:
        def factory():
            return stack.enter_context(TestClient(app))
        yield factory


@pytest.fixture
def client(client_factory):
    return client_factory()


@pytest.fixture
def api_factory(client_factory):
    def factory(username=None, *, copy_session=None):
        client = client_factory()
        if copy_session is not None:
            client.cookies.update(copy_session.client.cookies)
            return ApiSession(client, copy_session.user)
        username = username or "user_" + uuid4().hex[:12]
        registered = client.post("/api/auth/register", json={"username": username, "password": PASSWORD}, headers={"Origin": ORIGIN})
        assert registered.status_code == 201, registered.text
        logged_in = client.post("/api/auth/login", json={"username": username, "password": PASSWORD}, headers={"Origin": ORIGIN})
        assert logged_in.status_code == 200, logged_in.text
        assert client.cookies.get("survey_session") and client.cookies.get("csrf_token")
        return ApiSession(client, logged_in.json()["user"])
    return factory


@pytest.fixture
def survey_factory():
    def factory(api, questions=None, *, publish=True, **settings):
        body = {"title": "测试问卷", **settings}
        created = api.write("POST", "/api/surveys", body)
        assert created.status_code == 201, created.text
        survey = created.json()["survey"]
        if questions is None:
            questions = [{"id": "q1", "type": "single", "title": "单选", "required": True,
                          "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}]
        patched = api.write("PATCH", f"/api/surveys/{survey['id']}", {"revision": survey["revision"], "questions": questions})
        assert patched.status_code == 200, patched.text
        survey = patched.json()["survey"]
        if publish:
            result = api.write("POST", f"/api/surveys/{survey['id']}/publish", {"revision": survey["revision"]})
            assert result.status_code == 200, result.text
            survey = result.json()["survey"]
        return survey
    return factory


@pytest.fixture
def submit_response():
    def submit(api, survey, values=None, *, key=None, anonymous=False, version=None):
        if values is None:
            values = {"q1": "a"}
        entries = values if isinstance(values, list) else [{"questionId": qid, "value": value} for qid, value in values.items()]
        body = {"definitionVersion": survey["definitionVersion"] if version is None else version,
                "submissionKey": key or str(uuid4()), "isAnonymous": anonymous, "answers": entries}
        return api.write("POST", f"/api/participation/{survey['publicId']}/responses", body)
    return submit

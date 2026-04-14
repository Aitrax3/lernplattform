import os
import shutil
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DISCORD_CLIENT_ID", "fake-client")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "fake-secret")
os.environ.setdefault("DISCORD_REDIRECT_URI", "https://localhost/auth/discord/callback")
os.environ.setdefault("DISCORD_SERVER_ID", "fake-server")

import pytest

import app as learning_app


@pytest.fixture(autouse=True)
def isolate_files(tmp_path):
    original_users = learning_app.USERS_PATH
    original_classes = learning_app.CLASSES_PATH
    tmp_users = tmp_path / "users.json"
    tmp_classes = tmp_path / "classes.json"
    shutil.copy(original_users, tmp_users)
    shutil.copy(original_classes, tmp_classes)
    learning_app.USERS_PATH = str(tmp_users)
    learning_app.CLASSES_PATH = str(tmp_classes)
    yield
    learning_app.USERS_PATH = original_users
    learning_app.CLASSES_PATH = original_classes


@pytest.fixture(autouse=True)
def reset_discord_entries():
    learning_app.reset_discord_links()
    yield
    learning_app.reset_discord_links()


@pytest.fixture
def client(isolate_files):
    learning_app.app.config["TESTING"] = True
    with learning_app.app.test_client() as client_instance:
        yield client_instance


def login_as(client_instance, username):
    with client_instance.session_transaction() as sess:
        sess["username"] = username


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Willkommen" in response.data


def test_register_page(client):
    response = client.get("/register")
    assert response.status_code == 200
    assert b"Registrieren" in response.data


def test_topics_requires_login(client):
    response = client.get("/topics")
    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/")


def test_topics_page_for_student(client):
    login_as(client, "test-S")
    response = client.get("/topics")
    assert response.status_code == 200
    assert "Themenübersicht".encode("utf-8") in response.data


def test_student_redirected_from_teacher_portal(client):
    login_as(client, "test-S")
    response = client.get("/teacher")
    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/topics")


def test_teacher_portal_loads_for_teacher(client):
    login_as(client, "test-L")
    response = client.get("/teacher")
    assert response.status_code == 200
    assert "Lehrerportal".encode("utf-8") in response.data


def test_feedback_page_student(client):
    login_as(client, "test-S")
    response = client.get("/feedback")
    assert response.status_code == 200
    assert b"Lernassistent" in response.data


def test_feedback_page_teacher(client):
    login_as(client, "test-L")
    response = client.get("/feedback")
    assert response.status_code == 200
    assert "Schüler-Register".encode("utf-8") in response.data


def test_class_register_page(client):
    login_as(client, "test-L")
    response = client.get("/teacher/classes")
    assert response.status_code == 200
    assert b"Klassenregister" in response.data


def test_generate_chatbot_response_handles_status_error(monkeypatch):
    monkeypatch.setattr(learning_app, "openrouter_configured", lambda: True)
    class DummyResponse:
        ok = False
        status_code = 401
        text = "invalid api key"

        def json(self):
            return {"error": {"message": "Invalid API key"}}
        def raise_for_status(self):
            raise learning_app.requests.HTTPError("401 Client Error", response=self)

    def fake_post(*args, **kwargs):
        return DummyResponse()

    monkeypatch.setattr(learning_app.requests, "post", fake_post)
    response = learning_app.generate_chatbot_response("Test", [])
    assert response["role"] == "assistant"
    assert "OPENROUTER_API_KEY" in response["content"]


def test_generate_chatbot_response_handles_request_exception(monkeypatch):
    monkeypatch.setattr(learning_app, "openrouter_configured", lambda: True)
    def fake_post(*args, **kwargs):
        raise learning_app.requests.RequestException("timeout")

    monkeypatch.setattr(learning_app.requests, "post", fake_post)
    response = learning_app.generate_chatbot_response("Test", [])
    assert response["role"] == "assistant"
    assert "Verbindung zum Assistenten" in response["content"]


def test_generate_openrouter_question_handles_http_error(monkeypatch):
    monkeypatch.setattr(learning_app, "openrouter_configured", lambda: True)
    class DummyResponse:
        status_code = 401
        text = "invalid api key"

        def json(self):
            return {"error": {"message": "Invalid API key"}}

        def raise_for_status(self):
            raise learning_app.requests.HTTPError("401 Client Error", response=self)

    def fake_post(*args, **kwargs):
        return DummyResponse()

    monkeypatch.setattr(learning_app.requests, "post", fake_post)
    with pytest.raises(RuntimeError) as exc_info:
        learning_app.generate_openrouter_question("Mathematik", "Grundlagen", "leicht")
    assert "401" in str(exc_info.value)
    assert "Invalid API key" in str(exc_info.value)


def test_build_quiz_questions_falls_back_when_live_generation_fails(monkeypatch):
    monkeypatch.setattr(learning_app, "openrouter_configured", lambda: True)

    def fake_build_live(*args, **kwargs):
        raise RuntimeError("OpenRouter down")

    monkeypatch.setattr(learning_app, "build_live_quiz_questions", fake_build_live)
    questions = learning_app.build_quiz_questions("Mathematik", "Arithmetik", "leicht")
    assert questions
    assert all(question.get("source") == "static" for question in questions)


def test_assignment_start_blocked_after_completion():
    assignment = {"starts": {}, "completed": ["student1"], "deadline": None}
    assert not learning_app.assignment_start_allowed(assignment, "student1")
    assert learning_app.assignment_start_allowed(assignment, "student2")


def test_discord_callback_persists_link(monkeypatch, client):
    login_as(client, "test-S")

    class DummyTokenResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "abc123"}

    class DummyUserResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "discord-user-1"}

    monkeypatch.setattr(learning_app.requests, "post", lambda *args, **kwargs: DummyTokenResponse())
    monkeypatch.setattr(learning_app.requests, "get", lambda *args, **kwargs: DummyUserResponse())

    response = client.get("/auth/discord/callback?code=code123")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    assert learning_app.get_discord_link("test-S") == "discord-user-1"
    with client.session_transaction() as sess:
        assert "discord_oauth_status" in sess


def test_discord_callback_handles_missing_code(client):
    login_as(client, "test-S")
    response = client.get("/auth/discord/callback")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sess:
        assert sess.get("discord_oauth_status") == "Discord-Code fehlt."


def test_discord_callback_handles_token_error(monkeypatch, client):
    login_as(client, "test-S")

    def fail_post(*args, **kwargs):
        raise learning_app.requests.RequestException("timeout")

    monkeypatch.setattr(learning_app.requests, "post", fail_post)
    response = client.get("/auth/discord/callback?code=fail")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sess:
        assert "Token-Austausch" in sess.get("discord_oauth_status", "")
    assert learning_app.get_discord_link("test-S") is None


def test_discord_callback_auto_login(monkeypatch, client):
    learning_app.persist_discord_link("test-S", "discord-user-1")

    class DummyTokenResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "auto-token"}

    class DummyUserResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "discord-user-1"}

    monkeypatch.setattr(learning_app.requests, "post", lambda *args, **kwargs: DummyTokenResponse())
    monkeypatch.setattr(learning_app.requests, "get", lambda *args, **kwargs: DummyUserResponse())
    response = client.get("/auth/discord/callback?code=auto")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as sess:
        assert sess.get("username") == "test-S"
        assert "Discord" in sess.get("discord_oauth_status", "")


def test_discord_authorize_redirect(client):
    response = client.get("/auth/discord/authorize")
    assert response.status_code == 302
    parsed = urlparse(response.headers["Location"])
    assert parsed.scheme.startswith("https")
    params = parse_qs(parsed.query)
    assert params["client_id"][0] == "fake-client"
    assert "identify" in params["scope"][0]


def test_chat_requires_login(client):
    response = client.get("/chat")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_chat_page_shows_embed(client):
    login_as(client, "test-S")
    response = client.get("/chat")
    assert response.status_code == 200
    assert b"widgetbot" in response.data
    assert b"html-embed" in response.data


def test_api_endpoints_require_login(client):
    response = client.get("/api/next-question")
    assert response.status_code == 401
    response = client.post("/api/answer", json={})
    assert response.status_code == 401
    response = client.get("/api/progress")
    assert response.status_code == 401


def test_weakness_loop_blocks_topic_change(client):
    login_as(client, "test-S")
    for attempt in range(2):
        question_response = client.get(
            "/api/next-question",
            query_string={"topic": "Mathematik", "subtopic": "Arithmetik", "mode": "leicht"},
        )
        assert question_response.status_code == 200
        payload = question_response.get_json()["question"]
        answer_response = client.post(
            "/api/answer",
            json={
                "topic": "Mathematik",
                "subtopic": "Arithmetik",
                "mode": "leicht",
                "question": payload,
                "answer": f"falsch-{attempt}",
            },
        )
        assert answer_response.status_code == 200
        assert answer_response.get_json()["correct"] is False
    blocking_response = client.get(
        "/api/next-question",
        query_string={"topic": "Geografie", "subtopic": "Hauptstädte", "mode": "leicht"},
    )
    assert blocking_response.status_code == 200
    data = blocking_response.get_json()
    assert data["weakness_blocking"] is True
    assert "Mathematik::Arithmetik" in data["skill"]
    progress_response = client.get("/api/progress")
    assert progress_response.status_code == 200
    progress_data = progress_response.get_json()
    weakness_skills = [entry["skillId"] for entry in progress_data["weaknesses"]]
    assert any("Mathematik::Arithmetik" in skill for skill in weakness_skills)

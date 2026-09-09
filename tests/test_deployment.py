"""Deployment storage checks; no provider requests."""
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.perception import Settings
from backend.app.store import default_path
from tests.test_api import complete


def test_runtime_override_and_restart(tmp_path, monkeypatch):
    runtime = tmp_path / "volume"
    monkeypatch.setenv("CONVERGE_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows"))
    assert default_path() == runtime / "converge.sqlite3"
    app = create_app(perception_settings=Settings())
    with TestClient(app) as client:
        state = complete(client)
    assert app.state.observations.store.path == runtime / "converge-text.sqlite3"
    with TestClient(create_app(perception_settings=Settings())) as client:
        assert client.get("/api/v1/incidents").json() == state


def test_windows_local_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("CONVERGE_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_path() == tmp_path / "Converge" / "runtime" / "converge.sqlite3"

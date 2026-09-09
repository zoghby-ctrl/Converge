"""Deployment boundaries: no real cloud credentials or model requests."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.perception import Settings
from backend.app.postgres_store import Connection, PostgresStore, Row, connection_options, portable_sql
from backend.app.store import ROOT, Store
from backend.app.upload_storage import UploadStorage
from tests.test_api import complete


def test_backend_selection_and_no_local_production_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("CONVERGE_RUNTIME_DIR", str(tmp_path))
    assert Store().backend == "sqlite"
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Store()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:6543/demo")
    store = Store()
    assert isinstance(store, PostgresStore)
    assert store.schema == "converge_replay"
    assert store.live_store().schema == "converge_live"
    assert not store.path.exists()
    assert Store(tmp_path / "explicit.sqlite3").backend == "sqlite"


@pytest.mark.parametrize("url", ["", "sqlite:///file", "postgresql://host", "postgres://host:bad/db"])
def test_invalid_postgres_configuration(url):
    with pytest.raises(ValueError, match="PostgreSQL connection URL"):
        connection_options(url)


def test_pooler_configuration_and_sql_dialect():
    url = "postgres://postgres.project:p%40ss@aws-region.pooler.supabase.com:6543/postgres"
    options = connection_options(url)
    assert options["conninfo"] == url and options["prepare_threshold"] is None
    assert options["sslmode"] == "require"
    assert "CASE WHEN task='image' AND role='primary' THEN 1 ELSE 0 END" in portable_sql("sum(task='image' AND role='primary')")
    assert portable_sql("INSERT OR REPLACE INTO extraction_cache VALUES(?,?)").endswith("ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload")
    assert portable_sql("INSERT OR IGNORE INTO raw_responses VALUES(?)").endswith("ON CONFLICT DO NOTHING")
    row = Row([("id", 7), ("payload", "data")])
    assert row[0] == row["id"] == 7 and dict(row)["payload"] == "data"


def test_postgres_transaction_reentrance_rollback_and_parameter_binding(monkeypatch):
    events = []
    class Database:
        def __enter__(self):
            events.append("open")
            return self
        def __exit__(self, kind, *args):
            events.append("rollback" if kind else "commit")
        def execute(self, sql, params=()):
            events.append((sql, params))
            return SimpleNamespace(fetchone=lambda: Row(id=9))
    monkeypatch.setenv("DATABASE_URL", "postgresql://host/db")
    monkeypatch.setattr("backend.app.postgres_store.psycopg.connect", lambda **kwargs: Database())
    store = Store()
    with pytest.raises(RuntimeError):
        with store.lock:
            with store.lock, store.connection() as db:
                db.execute("SELECT payload FROM signals WHERE signal_id=?", ("quote'",))
                assert db.execute("INSERT INTO api_usage(model) VALUES(?)", ("gemini",)).lastrowid == 9
            raise RuntimeError("abort")
    assert events.count("open") == 1 and events[-1] == "rollback"
    assert ("SELECT payload FROM signals WHERE signal_id=%s", ("quote'",)) in events
    assert ("SELECT set_config('search_path', %s, true)", ("converge_replay",)) in events


def test_storage_survives_ephemeral_file_loss_and_sanitizes_errors(tmp_path, monkeypatch):
    objects = {}
    storage = UploadStorage("https://project.supabase.co", "test-server-secret", "images")
    def post(url, *, content, headers, **kwargs):
        assert headers["Authorization"] == "Bearer test-server-secret"
        objects[url] = content
        return httpx.Response(200)
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, content=objects[url]))
    normal = tmp_path / ("a" * 64 + ".normalized.png")
    original = tmp_path / ("a" * 64 + ".source.png")
    normal.write_bytes(b"normalized pixels")
    original.write_bytes(b"source pixels")
    storage.persist({"stored_path": str(normal), "preserved_path": str(original)})
    normal.unlink()
    storage.restore(normal)
    assert normal.read_bytes() == b"normalized pixels" and len(objects) == 2
    normal.unlink()
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(403, text="test-server-secret"))
    with pytest.raises(Exception) as error:
        storage.restore(normal)
    assert "test-server-secret" not in str(error.value)


def test_vercel_entrypoint_completes_background_before_response(monkeypatch):
    from api import index
    events = []
    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 202, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})
        events.append("background finished")
    async def send(message):
        events.append(message["type"])
    monkeypatch.setattr(index, "application", application)
    asyncio.run(index.app({"type": "http"}, None, send))
    assert events == ["background finished", "http.response.start", "http.response.body"]


def test_entrypoint_api_and_signature_unchanged(tmp_path, monkeypatch):
    from api import index
    monkeypatch.setattr(index, "application", create_app(tmp_path / "signature.sqlite3", Settings()))
    with TestClient(index.app) as client:
        state = complete(client, "signature_image")
        a = next(i for i in state["incidents"] if len(i["signal_ids"]) == 8)
        b = next(i for i in state["incidents"] if i["status"] == "candidate")
        assert len(a["signal_ids"]) == 8 and a["independent_capture_count"] == 1
        assert (b["risk"]["display"], b["evidence_strength"], b["independent_capture_count"]) == ("68", "Moderate", 3)
        removed = client.post("/api/v1/demo/compare", json={"disable_families": ["image"]}).json()
        changed = next(i for i in removed["incidents"] if i["status"] == "candidate")
        assert (changed["risk"]["display"], changed["evidence_strength"], changed["independent_capture_count"]) == ("52–83", "Limited", 2)
        restored = client.post("/api/v1/demo/compare", json={}).json()
        assert next(i for i in restored["incidents"] if i["status"] == "candidate")["risk"] == b["risk"]
        copies = client.post("/api/v1/demo/compare", json={"add_duplicates": 10}).json()
        copied = next(i for i in copies["incidents"] if i["status"] == "candidate")
        assert len(copied["signal_ids"]) == 13
        assert (copied["risk"], copied["evidence_strength"], copied["independent_capture_count"]) == (b["risk"], "Moderate", 3)
        assert client.get("/api/v1/missing").status_code == 404


def test_frontend_bundle_has_no_server_secrets():
    assets = list((ROOT / "frontend/dist/assets").glob("*.js"))
    assert assets, "Build the frontend before the final suite"
    for asset in assets:
        text = asset.read_text(encoding="utf-8")
        for forbidden in ("GEMINI_API_KEY", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL", "postgresql://", "railway.app"):
            assert forbidden not in text


def test_schema_namespaces_and_routes():
    schema = (ROOT / "supabase/schema.sql").read_text()
    for table in ("datasets", "signals", "evidence", "incidents", "incident_revisions", "incident_members",
                  "text_jobs", "image_jobs", "extraction_revisions", "api_usage", "raw_responses", "extraction_cache"):
        assert "CREATE TABLE IF NOT EXISTS " + table in schema
    assert "CREATE SCHEMA IF NOT EXISTS converge_replay" in schema
    assert "CREATE SCHEMA IF NOT EXISTS converge_live" in schema
    config = json.loads((ROOT / "vercel.json").read_text())
    assert config["rewrites"][0]["source"] == "/api/:path*"
    assert {r["source"] for r in config["rewrites"]} >= {"/report", "/operations"}

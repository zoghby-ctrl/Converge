"""Offline transport/contract checks; never use a real API key or network."""
import json

import httpx
import pytest

from backend.app.gemini_provider import MODEL, wire_schema
from backend.app.image_contract import ImageExtraction, ImageMetadata
from backend.app.image_perception import ImagePerception
from backend.app.perception import Perception, ProcessingError, Settings
from backend.app.store import Store
from backend.app.text_contract import TextExtraction, evidence_from
from tests.test_perception import extracted
from tests.test_image_perception import extraction, metadata


def response(payload, **changes):
    result = dict(responseId="gemini-response-1", modelVersion=MODEL,
        candidates=[{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(payload)}]}}],
        usageMetadata={"promptTokenCount": 100, "candidatesTokenCount": 50, "thoughtsTokenCount": 20})
    result.update(changes)
    return result


def adapter(tmp_path, payloads, *, image=False, status=200, **settings):
    calls = []
    def handle(request):
        calls.append(request)
        item = payloads[min(len(calls) - 1, len(payloads) - 1)]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(status, json=item)
    client = httpx.Client(transport=httpx.MockTransport(handle))
    cls = ImagePerception if image else Perception
    return cls(Store(tmp_path / "gemini.sqlite3"),
        Settings(provider="gemini", gemini_api_key="test-only-secret", **settings), client), calls


def test_environment_default_and_opt_in(monkeypatch):
    monkeypatch.setattr("backend.app.perception.dotenv_values", lambda _: {})
    monkeypatch.delenv("CONVERGE_PERCEPTION_PROVIDER", raising=False)
    assert Settings.from_env().provider == "openai"
    monkeypatch.setenv("CONVERGE_PERCEPTION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-secret")
    settings = Settings.from_env()
    assert settings.provider == "gemini" and settings.primary == settings.fallback == MODEL
    assert settings.active_api_key == "test-only-secret"
    assert "test-only-secret" not in repr(settings)


def test_text_schema_transport_metadata_usage_and_cache(tmp_path):
    p, calls = adapter(tmp_path, [response(extracted())])
    result = p.extract("water here")
    TextExtraction.model_validate(result["extraction"]).validate_source("water here")
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    assert calls[0].headers["x-goog-api-key"] == "test-only-secret"
    assert "test-only-secret" not in str(calls[0].url) + calls[0].content.decode()
    assert body["generationConfig"]["responseFormat"]["text"]["schema"] == wire_schema(TextExtraction.model_json_schema())
    assert body["tools"] == [] and body["contents"][0]["parts"] == [{"text": "water here"}]
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
    assert body["generationConfig"]["responseFormat"]["text"]["mimeType"] == "APPLICATION_JSON"
    assert result["provider"] == "gemini" and result["model_identifier"] == MODEL
    assert result["raw_response_reference"] == "gemini-response-1"
    assert "store=false" not in result["raw_response_storage"]
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 70}
    assert p.extract("water here")["source"] == "cached" and len(calls) == 1
    original = p.cache_key("water here", MODEL)
    p.settings.provider = "openai"
    assert p.cache_key("water here", MODEL) != original
    with p.store.connection() as db:
        assert db.execute("SELECT outcome FROM api_usage").fetchone()[0] == "validated"
        assert db.execute("SELECT output_text FROM raw_responses").fetchone()[0] == json.dumps(extracted())


def test_image_inline_bytes_existing_schema_and_uncertainty(tmp_path):
    p, calls = adapter(tmp_path, [response(extraction())], image=True)
    meta = metadata(tmp_path)
    result = p.extract(meta)
    ImageExtraction.model_validate(result["extraction"])
    assert result["review_state"] == "needs_review"
    assert result["provider"] == "gemini" and result["image_metadata"] == ImageMetadata.model_validate(meta).model_dump(mode="json")
    body = json.loads(calls[0].content)
    assert body["generationConfig"]["responseFormat"]["text"]["schema"] == wire_schema(ImageExtraction.model_json_schema())
    image = body["contents"][0]["parts"][1]["inlineData"]
    import base64
    from pathlib import Path
    assert image["mimeType"] == "image/png"
    assert base64.b64decode(image["data"]) == Path(meta["stored_path"]).read_bytes()
    assert p.extract(meta)["source"] == "cached" and len(calls) == 1


@pytest.mark.parametrize("payload", [{}, extracted(risk_index=100), extracted("fabricated quote")])
def test_invalid_or_fabricated_output_bounded_repair_no_acceptance(tmp_path, payload):
    p, calls = adapter(tmp_path, [response(payload)])
    with pytest.raises(ProcessingError, match="schema_invalid"):
        p.extract("water here")
    assert len(calls) == 3
    assert p.summary()["schema_failure_count"] == 3
    with p.store.connection() as db:
        assert db.execute("SELECT count(*) FROM extraction_cache").fetchone()[0] == 0


def test_uncertainty_preserved_through_same_provider_recheck(tmp_path):
    uncertain = extracted(standing_water="uncertain", uncertainties=[
        {"field": "standing_water", "reason": "limited_visibility", "affects_admission": True}])
    p, calls = adapter(tmp_path, [response(uncertain)])
    result = p.extract("water here")
    assert len(calls) == 2 and result["primary_extraction"] == uncertain
    assert result["review_state"] == "needs_review" and result["extraction"] == uncertain
    assert evidence_from(TextExtraction.model_validate(result["extraction"]), "test", 1) == []


@pytest.mark.parametrize("status,code", [(400, "api_configuration_rejected"), (401, "invalid_api_key"),
    (403, "api_permission_denied"), (404, "model_unavailable"), (429, "api_rate_or_credit_limit"), (500, "api_error")])
def test_http_failure_is_safe_and_not_retried(tmp_path, status, code):
    p, calls = adapter(tmp_path, [{"error": "test-only-secret"}], status=status)
    with pytest.raises(ProcessingError) as caught:
        p.extract("water here")
    assert str(caught.value) == code and len(calls) == 1
    assert "test-only-secret" not in json.dumps(p.summary())


@pytest.mark.parametrize("body,code", [
    ({"promptFeedback": {"blockReason": "SAFETY"}}, "provider_blocked"),
    ({}, "provider_response_invalid"),
    (response(extracted(), responseId=None), "provider_response_invalid"),
    (response(extracted(), candidates=[{"finishReason": "SAFETY"}]), "provider_blocked"),
])
def test_incomplete_provider_envelope_fails_closed(tmp_path, body, code):
    p, calls = adapter(tmp_path, [body])
    with pytest.raises(ProcessingError, match=code):
        p.extract("water here")
    assert len(calls) == 1


def test_timeout_missing_key_unknown_provider_and_budget(tmp_path):
    p, calls = adapter(tmp_path, [httpx.ReadTimeout("test-only-secret")])
    with pytest.raises(ProcessingError, match="api_unavailable"):
        p.extract("water here")
    assert len(calls) == 1
    p.client = None
    p.settings.gemini_api_key = ""
    with pytest.raises(ProcessingError, match="api_key_missing"):
        p.extract("water here")
    p.settings.provider = "typo"
    with pytest.raises(ProcessingError, match="unsupported_perception_provider"):
        p.extract("water here")
    p.settings.provider = "gemini"
    p.settings.gemini_api_key = "test-only-secret"
    p.settings.max_requests = 0
    with pytest.raises(ProcessingError, match="development_usage_limit"):
        p.extract("water here")


def test_truncated_valid_json_is_not_accepted(tmp_path):
    body = response(extracted())
    body["candidates"][0]["finishReason"] = "MAX_TOKENS"
    p, calls = adapter(tmp_path, [body], fallback_enabled=False)
    with pytest.raises(ProcessingError, match="fallback_disabled"):
        p.extract("water here")
    assert len(calls) == 2 and p.summary()["schema_failure_count"] == 2


def test_credentials_redacted_from_raw_and_never_cached(tmp_path):
    p, calls = adapter(tmp_path, [response(extracted("test-only-secret"))], fallback_enabled=False)
    with pytest.raises(ProcessingError):
        p.extract("test-only-secret")
    with p.store.connection() as db:
        assert "test-only-secret" not in db.execute("SELECT output_text FROM raw_responses").fetchone()[0]
        assert db.execute("SELECT count(*) FROM extraction_cache").fetchone()[0] == 0


def test_wire_projection_keeps_contract_shape_and_local_bounds():
    original = TextExtraction.model_json_schema()
    snapshot = json.dumps(original, sort_keys=True)
    wire = wire_schema(original)
    assert json.dumps(original, sort_keys=True) == snapshot
    assert wire["required"] == original["required"]
    assert wire["additionalProperties"] is False
    assert wire["properties"].keys() == original["properties"].keys()
    assert wire["properties"]["standing_water"]["enum"] == original["properties"]["standing_water"]["enum"]
    assert wire["properties"]["reported_duration"]["anyOf"] == original["properties"]["reported_duration"]["anyOf"]
    assert "maxLength" not in json.dumps(wire)
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TextExtraction.model_validate(extracted("x" * 181))
    with pytest.raises(ValidationError):
        ImageExtraction.model_validate(extraction(visible_description="x" * 401))


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_signature_full_ablation_restore_and_ten_duplicates(tmp_path, provider):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    from tests.test_api import complete
    app = create_app(tmp_path / "signature.sqlite3", Settings(provider=provider, max_requests=0))
    def signature(state):
        incident = next(i for i in state["incidents"] if i["status"] == "candidate")
        return incident["risk"]["display"], incident["evidence_strength"], incident["independent_capture_count"]
    with TestClient(app) as client:
        for scenario in ("signature", "signature_image"):
            baseline = complete(client, scenario)
            assert signature(baseline) == ("68", "Moderate", 3)
            ablated = client.post("/api/v1/demo/compare", json={"disable_families": ["image"]}).json()
            assert signature(ablated) == ("52–83", "Limited", 2)
            restored = client.post("/api/v1/demo/compare", json={"disable_families": []}).json()
            assert signature(restored) == ("68", "Moderate", 3)
            copied = client.post("/api/v1/demo/compare", json={"add_duplicates": 10, "source_signal_id": "b-water-first"}).json()
            assert signature(copied) == ("68", "Moderate", 3)
            assert client.get("/api/v1/incidents").json() == baseline
        assert client.get("/api/v1/perception/usage").json()["total_api_requests"] == 0


def test_provider_metadata_persists_in_existing_observation_history(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    from tests.test_perception import request
    p, calls = adapter(tmp_path, [response(extracted())])
    app = create_app(tmp_path / "pipeline.sqlite3", p.settings, p.client)
    with TestClient(app) as client:
        sid = client.post("/api/v1/signals", json=request()).json()["signal_id"]
        job = client.get(f"/api/v1/signals/{sid}/processing").json()
        assert job["status"] == "processed" and job["revision"] == 1
        assert job["latest"]["provider"] == "gemini"
        assert job["latest"]["model_identifier"] == MODEL
        assert job["revisions"][0]["raw_response_reference"] == "gemini-response-1"
        assert job["original"]["capture_group_id"] == "capture-1"
        assert len(calls) == 1

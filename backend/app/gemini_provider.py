"""Small server-only Gemini transport; observation semantics stay in task adapters."""
from types import SimpleNamespace

import httpx

MODEL = "gemini-3.8-flash"
# Conservative standard-rate ceiling, including the announced January 2027 prices.
RATES = (1.5, 7.5)


class GeminiError(Exception):
    """Only fixed public error codes, never provider bodies or credentials."""


def wire_schema(schema):
    """Project to Gemini's bounded JSON grammar; enforce all limits locally.

    Google documents schema-complexity rejection. Numeric/string/array bounds
    remain in the unchanged Pydantic validator, while names, types, required
    fields, nullability, enums and additionalProperties travel to the provider.
    """
    local_only = {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "title"}
    def convert(node):
        if isinstance(node, list):
            return [convert(item) for item in node]
        if isinstance(node, dict):
            return {key: convert(value) for key, value in node.items() if key not in local_only}
        return node
    return convert(schema)


def generate(*, api_key, model, system, user_content, schema, max_output_tokens, client=None):
    if model != MODEL:
        raise GeminiError("unpriced_model_configuration")
    parts = []
    if isinstance(user_content, str):
        parts.append({"text": user_content})
    else:
        for part in user_content:
            if part["type"] == "input_text":
                parts.append({"text": part["text"]})
            elif part["type"] == "input_image":
                header, data = part["image_url"].split(",", 1)
                if header not in ("data:image/jpeg;base64", "data:image/png;base64"):
                    raise GeminiError("api_configuration_rejected")
                parts.append({"inlineData": {"mimeType": header[5:-7], "data": data}})
            else:
                raise GeminiError("api_configuration_rejected")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": wire_schema(schema)}},
            "thinkingConfig": {"thinkingLevel": "LOW"},
            "maxOutputTokens": max_output_tokens,
            "candidateCount": 1,
        },
        "tools": [],
    }
    try:
        # Header authentication avoids credentials in URLs. No HTTP retries/redirects.
        response = (client.post if client is not None else httpx.post)(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key}, json=body, timeout=35,
            follow_redirects=False,
        )
    except httpx.RequestError:
        raise GeminiError("api_unavailable") from None
    if response.status_code != 200:
        code = {400: "api_configuration_rejected", 401: "invalid_api_key",
                403: "api_permission_denied", 404: "model_unavailable",
                429: "api_rate_or_credit_limit"}.get(response.status_code, "api_error")
        raise GeminiError(code)
    try:
        data = response.json()
        candidates = data.get("candidates", [])
        if data.get("promptFeedback", {}).get("blockReason"):
            raise GeminiError("provider_blocked")
        if len(candidates) != 1:
            raise GeminiError("provider_response_invalid")
        candidate = candidates[0]
        reason = candidate.get("finishReason")
        if reason not in ("STOP", "MAX_TOKENS"):
            raise GeminiError("provider_blocked")
        output = "".join(p["text"] for p in candidate.get("content", {}).get("parts", [])
                         if "text" in p and not p.get("thought"))
        # Provider identity must be real, not substituted with invented response IDs.
        ref, actual_model = data["responseId"], data["modelVersion"]
        if not isinstance(ref, str) or not ref or not isinstance(actual_model, str) or not actual_model:
            raise ValueError("Missing provider identity")
        usage = data.get("usageMetadata", {})
        counts = [usage.get("promptTokenCount"), usage.get("candidatesTokenCount"),
                  usage.get("thoughtsTokenCount", 0)]
        valid_usage = all(type(n) is int and n >= 0 for n in counts)
        return SimpleNamespace(
            id=ref, model=actual_model, output_text=output,
            status="completed" if reason == "STOP" else "incomplete",
            usage=SimpleNamespace(input_tokens=counts[0], output_tokens=counts[1] + counts[2])
                  if valid_usage else None,
        )
    except GeminiError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GeminiError("provider_response_invalid") from None

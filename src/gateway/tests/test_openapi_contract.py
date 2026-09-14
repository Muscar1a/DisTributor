# Regression tests for issue #60 — OpenAPI contract shape and ErrorEnvelope format.

from fastapi.testclient import TestClient

from src.gateway.app.main import app


def _response_schema(openapi: dict, path: str, method: str) -> dict:
    response = openapi["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
    model_name = response["$ref"].rsplit("/", 1)[-1]
    return openapi["components"]["schemas"][model_name]


def test_contract_endpoints_have_object_response_schemas():
    schema = app.openapi()
    expected = {
        ("/healthz", "get"): {
            "status",
            "version",
            "commit_sha",
            "build_timestamp",
            "db",
            "providers",
            "classifier_error_rate",
        },
        ("/readyz", "get"): {"status", "checks"},
        ("/v1/chat/completions", "post"): {"id", "object", "created", "model", "choices", "usage", "smartroute"},
        ("/v1/models", "get"): {"object", "data"},
        ("/v1/usage/{request_id}", "get"): {"status", "smartroute"},
    }

    for (path, method), required in expected.items():
        model_schema = _response_schema(schema, path, method)
        assert model_schema["type"] == "object"
        assert set(model_schema["required"]) == required


def test_chat_contract_declares_roles_and_response_headers():
    schema = app.openapi()
    chat = schema["paths"]["/v1/chat/completions"]["post"]
    request_ref = chat["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]
    message_ref = request_schema["properties"]["messages"]["items"]["$ref"]
    message_schema = schema["components"]["schemas"][message_ref.rsplit("/", 1)[-1]]
    assert set(message_schema["properties"]["role"]["enum"]) == {"assistant", "system", "user"}

    headers = {name.lower() for name in chat["responses"]["200"]["headers"]}
    assert headers == {
        "x-sr-model",
        "x-sr-provider",
        "x-request-id",
        "x-sr-request-id",
        "x-sr-score",
        "x-sr-tier",
        "x-sr-cost-usd",
        "x-sr-clamped",
        "x-sr-dropped-params",
    }
    assert "422" in chat["responses"]


def test_models_endpoint_returns_contract_shape(monkeypatch):
    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    with TestClient(app) as client:
        response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"]
    assert all(
        set(model) == {"id", "object", "provider", "default_tier", "capabilities", "enabled"} for model in body["data"]
    )


def test_validation_error_uses_contract_envelope(monkeypatch):
    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "invalid", "content": "hello"}]},
        )
    assert response.status_code == 422
    error = response.json()["error"]
    assert set(error) == {"message", "type", "param", "code", "request_id", "details"}
    assert error["type"] == "invalid_request_error"
    assert error["code"] == "validation_error"


def test_unsupported_openai_endpoints_declare_404_contracts():
    schema = app.openapi()
    for path in (
        "/v1/responses",
        "/v1/embeddings",
        "/v1/images/generations",
        "/v1/audio/transcriptions",
    ):
        responses = schema["paths"][path]["post"]["responses"]
        assert "404" in responses
        assert "200" not in responses

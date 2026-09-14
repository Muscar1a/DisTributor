from fastapi.testclient import TestClient

from src.gateway.app.main import app


def test_playground_is_served_at_root():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "SmartRoute Playground" in response.text
    assert 'id="prompt-form"' in response.text


def test_playground_and_dashboard_routes_are_served():
    client = TestClient(app)
    for path in ("/playground", "/dashboard", "/logs", "/keys", "/config"):
        response = client.get(path)
        assert response.status_code == 200
        assert "SmartRoute Playground" in response.text


def test_playground_assets_are_served():
    client = TestClient(app)
    assert client.get("/static/styles.css").status_code == 200
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "p-156-latest.onrender.com" not in script.text
    assert 'fetch("/v1/chat/completions"' in script.text

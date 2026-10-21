from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(":memory:"), base_url="http://localhost") as client:
        yield client


def test_manual_workflow_broadcast_and_correction(client: TestClient) -> None:
    with client.websocket_connect("ws://localhost/ws") as websocket:
        assert websocket.receive_json()["cards_seen"] == 0
        for rank, source in [("8", "player"), ("8", "player"), ("6", "dealer_up")]:
            response = client.post("/api/card", json={"rank": rank, "source": source})
            assert response.status_code == 200
            assert websocket.receive_json() == response.json()
        state = response.json()
        assert state["player_hands"][0]["action"] == "SPLIT"
        card = state["recent_cards"][1]
        fixed = client.post("/api/card", json={"rank": "10", "replaces": card["id"]}).json()
        assert fixed["cards_seen"] == 3
        assert websocket.receive_json()["player_hands"][0]["action"] == "STAND"
        client.post("/api/undo")
        assert websocket.receive_json()["player_hands"][0]["action"] == "SPLIT"
        client.post("/api/new-hand")
        assert websocket.receive_json()["cards_seen"] == 3
        client.post("/api/new-shoe")
        assert websocket.receive_json()["cards_seen"] == 0


def test_validation_and_config(client: TestClient) -> None:
    assert client.post("/api/card", json={"rank": "X"}).status_code == 422
    assert client.post("/api/undo").status_code == 400
    assert client.put("/api/config", json={"decks": 1}).status_code == 422
    assert client.put("/api/config", json={"dealer_hits_soft_17": "false"}).status_code == 422
    assert client.put("/api/config", json={"decks": 4, "rounding": "round"}).status_code == 200
    assert client.get("/api/session/state").json()["config"]["decks"] == 4


def test_cross_origin_rejected(client: TestClient) -> None:
    assert client.post("/api/new-shoe", headers={"Origin": "https://example.com"}).status_code == 403
    assert client.get("/api/session/state", headers={"Host": "example.com"}).status_code == 400


def test_configured_host_and_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKJACK_ALLOWED_HOSTS", "blackjack.example.com")
    with TestClient(create_app(":memory:"), base_url="https://blackjack.example.com") as hosted:
        assert hosted.get("/health/live").json() == {"status": "ok"}
        assert hosted.get("/health/ready").json() == {"status": "ok"}
        response = hosted.get("/api/session/state", headers={"Origin": "https://blackjack.example.com"})
        assert response.status_code == 200
        assert "wss:" in response.headers["content-security-policy"]
        assert hosted.get("/api/session/state", headers={"Origin": "https://other.example.com"}).status_code == 403


def test_two_tabs_and_reconnection(client: TestClient) -> None:
    with client.websocket_connect("ws://localhost/ws") as first, client.websocket_connect("ws://localhost/ws") as second:
        first.receive_json()
        second.receive_json()
        client.post("/api/card", json={"rank": "5", "source": "other"})
        assert first.receive_json()["running_count"] == 1
        assert second.receive_json()["running_count"] == 1
    with client.websocket_connect("ws://localhost/ws") as reconnected:
        assert reconnected.receive_json()["cards_seen"] == 1


def test_dashboard_assets_and_local_only_dependencies(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "Your table. Your pace." in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/favicon.svg").status_code == 200
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]

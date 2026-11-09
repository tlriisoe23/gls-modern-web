from fastapi.testclient import TestClient

from app.main import create_app

app = create_app()
client = TestClient(app)

def test_simulate_ecgc_match_null_and_type_safety():
    # Explicit null payload -> these should be caught by the outer loop which throws 422!
    response = client.post("/api/rules/simulate", json={"rules": None, "team_a": None, "team_b": None})
    assert response.status_code == 422
    assert "team_a must be an object" in response.text

    # Null players -> caught by player type check which throws 422!
    response = client.post("/api/rules/simulate", json={"team_a": {"player1": None}, "team_b": {"player2": None}})
    assert response.status_code == 422
    assert "Players must be objects" in response.text

    # Invalid types for teams (e.g. string)
    response = client.post("/api/rules/simulate", json={"team_a": "invalid"})
    assert response.status_code == 422
    assert "must be an object" in response.text

    # Invalid types for players (e.g. number)
    response = client.post("/api/rules/simulate", json={"team_a": {"player1": 123}})
    assert response.status_code == 422
    assert "Players must be objects" in response.text

    # Ensure it works when they are missing entirely
    response = client.post("/api/rules/simulate", json={})
    assert response.status_code == 200

from fastapi.testclient import TestClient

from app import security
from app.main import app

client = TestClient(app)


def _make_route(**overrides):
    payload = {"destination_url": "https://example.com/hook", "description": "test"}
    payload.update(overrides)
    resp = client.post("/routes", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_fetch_route():
    route = _make_route()
    assert route["id"]
    fetched = client.get(f"/routes/{route['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["destination_url"] == "https://example.com/hook"


def test_get_unknown_route_404():
    assert client.get("/routes/does-not-exist").status_code == 404


def test_delete_route():
    route = _make_route()
    assert client.delete(f"/routes/{route['id']}").status_code == 204
    assert client.get(f"/routes/{route['id']}").status_code == 404


def test_ingest_without_secret_accepts():
    route = _make_route()
    resp = client.post(f"/ingest/{route['id']}", json={"event": "ping"})
    assert resp.status_code == 202
    event_id = resp.json()["event_id"]
    detail = client.get(f"/events/{event_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "pending"


def test_ingest_rejects_bad_signature():
    route = _make_route(signing_secret="topsecret")
    resp = client.post(
        f"/ingest/{route['id']}", content=b"{}",
        headers={security.SIGNATURE_HEADER: "wrong"},
    )
    assert resp.status_code == 401


def test_ingest_accepts_valid_signature():
    route = _make_route(signing_secret="topsecret")
    body = b'{"order_id": 42}'
    sig = security.sign("topsecret", body)
    resp = client.post(
        f"/ingest/{route['id']}", content=body,
        headers={security.SIGNATURE_HEADER: sig, "content-type": "application/json"},
    )
    assert resp.status_code == 202


def test_events_listed_for_route():
    route = _make_route()
    client.post(f"/ingest/{route['id']}", json={"n": 1})
    client.post(f"/ingest/{route['id']}", json={"n": 2})
    events = client.get(f"/routes/{route['id']}/events").json()
    assert len(events) == 2


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}

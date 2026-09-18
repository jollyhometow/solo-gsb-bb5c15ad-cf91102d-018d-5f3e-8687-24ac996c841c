"""API integration tests using FastAPI's TestClient."""
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_store
from app.storage import Store

PAYLOAD = {
    "files": [
        {"path": "README.md", "content": "# Home\n\nSee [guide](docs/guide.md#install).\n"},
        {"path": "docs/guide.md", "content": "# Guide\n\n## Install\n\n## Install\n"},
        {"path": "docs/broken.md", "content": "[esc](../../out.md)\n[me](broken.md)\n[404](nope.md)\n"},
    ]
}


@pytest.fixture()
def client(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_get_check(client):
    resp = client.post("/checks", json=PAYLOAD)
    assert resp.status_code == 201
    result = resp.json()

    assert result["file_count"] == 3
    assert result["summary"] == {
        "duplicate_anchor": 1,
        "path_out_of_root": 1,
        "self_reference": 1,
        "missing_file": 1,
    }
    assert result["diagnostic_count"] == 4

    types = {(d["type"], d["source_file"], d["line"]) for d in result["diagnostics"]}
    assert ("duplicate_anchor", "docs/guide.md", 5) in types
    assert ("path_out_of_root", "docs/broken.md", 1) in types
    assert ("self_reference", "docs/broken.md", 2) in types
    assert ("missing_file", "docs/broken.md", 3) in types
    for d in result["diagnostics"]:
        assert d["link"]  # reproducible link as written

    check_id = result["check_id"]
    fetched = client.get(f"/checks/{check_id}")
    assert fetched.status_code == 200
    assert fetched.json() == result


def test_get_unknown_check_returns_404(client):
    assert client.get("/checks/does-not-exist").status_code == 404


def test_list_checks(client):
    client.post("/checks", json=PAYLOAD)
    client.post("/checks", json={"files": [{"path": "only.md", "content": "# Ok\n"}]})
    listing = client.get("/checks").json()
    assert len(listing) == 2
    assert listing[0]["diagnostic_count"] == 0  # newest first
    assert listing[1]["diagnostic_count"] == 4


def test_invalid_paths_rejected(client):
    resp = client.post(
        "/checks",
        json={"files": [{"path": "../evil.md", "content": ""}, {"path": "/abs.md", "content": ""}]},
    )
    assert resp.status_code == 422


def test_duplicate_paths_rejected(client):
    resp = client.post(
        "/checks",
        json={"files": [{"path": "a.md", "content": "1"}, {"path": "./a.md", "content": "2"}]},
    )
    assert resp.status_code == 422


def test_empty_file_set_rejected(client):
    assert client.post("/checks", json={"files": []}).status_code == 422

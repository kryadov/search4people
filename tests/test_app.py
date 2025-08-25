import os
import json
from fastapi.testclient import TestClient

from src.app import app, _md_filter

client = TestClient(app)


def test_index_ok():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Search4People" in resp.text


def test_markdown_filter_bold():
    html = _md_filter("**bold** text")
    assert "<strong>bold</strong>" in html or "<b>bold</b>" in html


def test_search_redirect_and_status():
    # minimal payload
    data = {
        "first_name": "John",
        "last_name": "Doe",
        "surname": "",
        "phone": "",
    }
    resp = client.post("/search", data=data)
    assert resp.status_code in (303, 307)
    # extract person id from redirect location
    loc = resp.headers.get("location")
    assert loc and loc.startswith("/people/")
    person_id = int(loc.rsplit("/", 1)[-1])

    # status should be available (running or done quickly depending on fallback LLM)
    status_resp = client.get(f"/status/{person_id}")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert "status" in body
    assert body["status"] in ("running", "done", "awaiting_user", "idle", "error")

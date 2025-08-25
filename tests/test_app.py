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
    resp = client.post("/search", data=data, follow_redirects=False)
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



def test_search_deduplicates_existing_person():
    data = {
        "first_name": "Alice",
        "last_name": "Smith",
        "surname": "",
        "phone": "",
    }
    # First submission creates (or opens) a record
    resp1 = client.post("/search", data=data, follow_redirects=False)
    assert resp1.status_code in (303, 307)
    loc1 = resp1.headers.get("location")
    assert loc1 and loc1.startswith("/people/")
    pid1 = int(loc1.rsplit("/", 1)[-1])

    # Second identical submission should redirect to the same person id (no duplicate)
    resp2 = client.post("/search", data=data, follow_redirects=False)
    assert resp2.status_code in (303, 307)
    loc2 = resp2.headers.get("location")
    assert loc2 and loc2.startswith("/people/")
    pid2 = int(loc2.rsplit("/", 1)[-1])

    assert pid1 == pid2

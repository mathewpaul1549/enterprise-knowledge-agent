import json
from pathlib import Path
import pytest
from app import create_app
from knowledge import ingest, answer, allowed_chunks, initialize

ROOT = Path(__file__).parents[1]
SUP = {"tenant": "acme", "roles": ["support"]}
ADM = {"tenant": "acme", "roles": ["support", "admin"]}


@pytest.fixture
def path(tmp_path):
    p = str(tmp_path / "kb.db")
    initialize(p)
    for d in json.loads((ROOT / "samples/documents.json").read_text()):
        ingest(p, d)
    return p


def test_supported_and_abstain(path):
    r = answer(path, SUP, "What is the API rate limit?")
    assert r["status"] == "answered" and r["citations"][0]["document"] == "rate-limits"
    assert (
        answer(path, SUP, "Does this support quantum encryption?")["status"]
        == "abstained"
    )


def test_tenant_and_role_isolation(path):
    assert (
        answer(path, SUP, "internal incident escalation code")["status"] == "abstained"
    )
    assert (
        answer(path, ADM, "internal incident escalation code")["citations"][0][
            "document"
        ]
        == "incident-escalation"
    )
    r = answer(path, {"tenant": "beta", "roles": ["support"]}, "API rate limit")
    assert "40 requests" in r["answer"] and "120 requests" not in r["answer"]
    assert all(
        "SYNTHETIC-ORCHID" not in c["text"] and "BETA-ONLY" not in c["text"]
        for c in allowed_chunks(path, SUP)
    )


def test_citations_exact(path):
    r = answer(path, SUP, "Webhook signature verification")
    indexed = {c["id"]: c["text"] for c in allowed_chunks(path, SUP)}
    assert r["citations"]
    for c in r["citations"]:
        assert c["quote"] == indexed[c["id"]]


def test_version_update_and_replay(path):
    d = {
        "tenant": "acme",
        "slug": "test",
        "version": 1,
        "title": "Retention",
        "roles": ["support"],
        "body": "Synthetic retention duration is 20 days.",
    }
    assert ingest(path, d)["status"] == "indexed"
    assert ingest(path, d)["status"] == "unchanged"
    old = answer(path, SUP, "retention duration")["citations"][0]["id"]
    d["body"] = "Synthetic retention duration is 30 days."
    with pytest.raises(ValueError):
        ingest(path, d)
    d["version"] = 2
    ingest(path, d)
    r = answer(path, SUP, "retention duration")
    assert "30 days" in r["answer"] and "20 days" not in r["answer"]
    assert old not in [c["id"] for c in allowed_chunks(path, SUP)]


def test_api_enforcement_and_ticket_idempotency(path):
    c = create_app(path).test_client()
    h = {"Authorization": "Bearer demo-acme-support"}
    assert c.post("/api/search", json={"query": "API"}).status_code == 401
    assert c.post("/api/ingest", json={}, headers=h).status_code == 403
    r = c.post(
        "/api/search",
        json={"query": "API rate limit", "tenant": "beta", "roles": ["admin"]},
        headers=h,
    ).json
    assert "120 requests" in r["answer"] and "40 requests" not in r["answer"]
    body = {
        "query": "API rate limit",
        "request_key": "key1",
        "citation_ids": [r["citations"][0]["id"]],
    }
    first = c.post("/api/tickets", json=body, headers=h).json
    second = c.post("/api/tickets", json=body, headers=h).json
    assert first["id"] == second["id"] and second["replayed"]
    assert (
        c.post(
            "/api/tickets", json={**body, "query": "different"}, headers=h
        ).status_code
        == 400
    )
    restricted = answer(path, ADM, "internal incident escalation code")["citations"][0][
        "id"
    ]
    assert (
        c.post(
            "/api/tickets",
            json={**body, "citation_ids": [restricted], "request_key": "key2"},
            headers=h,
        ).status_code
        == 400
    )
    assert c.get("/").status_code == 200


@pytest.mark.parametrize("value", [{}, [], None, {"query": ""}, {"query": 12}])
def test_bad_requests(path, value):
    c = create_app(path).test_client()
    assert (
        c.post(
            "/api/search",
            json=value,
            headers={"Authorization": "Bearer demo-acme-support"},
        ).status_code
        == 400
    )


def test_ingest_file_acl(path):
    import io

    c = create_app(path).test_client()
    admin = {"Authorization": "Bearer demo-acme-admin"}
    response = c.post(
        "/api/ingest-file",
        headers=admin,
        data={
            "file": (
                io.BytesIO(b"Backup restore duration is 30 minutes."),
                "backup.md",
            ),
            "slug": "backup",
            "title": "Backup guide",
            "version": "1",
            "roles": "admin",
        },
    )
    assert response.status_code == 201
    assert answer(path, SUP, "backup restore duration")["status"] == "abstained"
    assert answer(path, ADM, "backup restore duration")["status"] == "answered"

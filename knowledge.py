"""Tenant-scoped BM25 retrieval with immutable evidence IDs and abstention."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

STOP = set(
    "a an the is are was were how what when where can do does i we to of for on in and or with my our it this please".split()
)


def tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as con:
        con.executescript("""CREATE TABLE IF NOT EXISTS documents(
          tenant TEXT, slug TEXT, version INTEGER, title TEXT, roles TEXT, body TEXT,
          PRIMARY KEY(tenant,slug));
          CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, tenant TEXT, slug TEXT,
          version INTEGER, ordinal INTEGER, text TEXT);
          CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, tenant TEXT, request_key TEXT,
          payload TEXT, UNIQUE(tenant,request_key));""")


def ingest(path, doc):
    for key in ("tenant", "slug", "title", "body"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise ValueError(f"{key} is required")
    if len(doc["body"].encode()) > 1_000_000:
        raise ValueError("Document exceeds 1 MB")
    if type(doc.get("version")) is not int or doc["version"] < 1:
        raise ValueError("Positive integer version required")
    if (
        not isinstance(doc.get("roles"), list)
        or not doc["roles"]
        or any(r not in {"support", "admin"} for r in doc["roles"])
    ):
        raise ValueError("Supported access roles required")
    # Paragraph chunks split by bounded word groups. Evidence always stores original text.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", doc["body"]) if p.strip()]
    pieces = []
    for paragraph in paragraphs:
        words = paragraph.split()
        pieces.extend(" ".join(words[i : i + 160]) for i in range(0, len(words), 160))
    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        old = con.execute(
            "SELECT * FROM documents WHERE tenant=? AND slug=?",
            (doc["tenant"], doc["slug"]),
        ).fetchone()
        if old and doc["version"] <= old["version"]:
            if (
                doc["version"] == old["version"]
                and doc["body"] == old["body"]
                and doc["title"] == old["title"]
                and sorted(doc["roles"]) == sorted(json.loads(old["roles"]))
            ):
                return {"status": "unchanged", "slug": doc["slug"]}
            raise ValueError("Update requires a strictly newer version")
        con.execute(
            "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?)",
            (
                doc["tenant"],
                doc["slug"],
                doc["version"],
                doc["title"],
                json.dumps(doc["roles"]),
                doc["body"],
            ),
        )
        con.execute(
            "DELETE FROM chunks WHERE tenant=? AND slug=?", (doc["tenant"], doc["slug"])
        )
        for index, piece in enumerate(pieces):
            identity = hashlib.sha256(
                f"{doc['tenant']}:{doc['slug']}:{doc['version']}:{index}:{piece}".encode()
            ).hexdigest()[:24]
            con.execute(
                "INSERT INTO chunks VALUES(?,?,?,?,?,?)",
                (identity, doc["tenant"], doc["slug"], doc["version"], index, piece),
            )
    return {"status": "indexed", "slug": doc["slug"], "chunks": len(pieces)}


def allowed_chunks(path, principal):
    with connect(path) as con:
        rows = con.execute(
            "SELECT c.*,d.title,d.roles FROM chunks c JOIN documents d ON c.tenant=d.tenant AND c.slug=d.slug WHERE c.tenant=?",
            (principal["tenant"],),
        ).fetchall()
    return [
        dict(r) for r in rows if set(json.loads(r["roles"])) & set(principal["roles"])
    ]


def retrieve(path, principal, query, limit=3):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
        raise ValueError("Query must contain 1–2000 characters")
    terms = set(tokens(query))
    rows = allowed_chunks(path, principal)
    if not terms or not rows:
        return []
    bags = [Counter(tokens(r["title"] + " " + r["text"])) for r in rows]
    avg = sum(sum(b.values()) for b in bags) / len(bags) or 1
    frequencies = {t: sum(t in b for b in bags) for t in terms}
    scored = []
    for row, bag in zip(rows, bags):
        matched = terms & bag.keys()
        coverage = len(matched) / len(terms)
        # Conservative lexical gate: no speculative answer from a weak match.
        if len(matched) < min(2, len(terms)) or coverage < 0.5:
            continue
        score = 0
        for t in matched:
            idf = math.log(
                1 + (len(rows) - frequencies[t] + 0.5) / (frequencies[t] + 0.5)
            )
            score += (
                idf
                * bag[t]
                * 2.2
                / (bag[t] + 1.2 * (0.25 + 0.75 * sum(bag.values()) / avg))
            )
        scored.append(
            {
                "id": row["id"],
                "document": row["slug"],
                "title": row["title"],
                "version": row["version"],
                "quote": row["text"],
                "score": round(score, 4),
                "term_coverage": round(coverage, 3),
            }
        )
    return sorted(scored, key=lambda x: (-x["score"], x["id"]))[:limit]


def answer(path, principal, query):
    citations = retrieve(path, principal, query)
    return {
        "query": query,
        "status": "answered" if citations else "abstained",
        "method": "BM25 + extractive evidence baseline",
        "answer": (
            "\n\n".join(f"[{c['id']}] {c['quote']}" for c in citations)
            if citations
            else "No sufficiently matched evidence is available to your account. Ask a support reviewer."
        ),
        "citations": citations,
    }


def draft_ticket(path, principal, key, query, citation_ids):
    if not isinstance(key, str) or not 1 <= len(key) <= 120:
        raise ValueError("A request key of 1–120 characters is required")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
        raise ValueError("A query of 1–2000 characters is required")
    if not isinstance(citation_ids, list) or any(
        not isinstance(x, str) for x in citation_ids
    ):
        raise ValueError("citation_ids must be a list of strings")
    available = {r["id"]: r for r in allowed_chunks(path, principal)}
    if any(c not in available for c in citation_ids):
        raise ValueError("Evidence is unavailable or access is denied")
    payload = {
        "query": query,
        "citations": [{"id": c, "quote": available[c]["text"]} for c in citation_ids],
        "status": "draft",
    }
    serialized = json.dumps(payload, sort_keys=True)
    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT * FROM tickets WHERE tenant=? AND request_key=?",
            (principal["tenant"], key),
        ).fetchone()
        if existing:
            if existing["payload"] != serialized:
                raise ValueError("Request key already used for different content")
            return {
                "id": existing["id"],
                **json.loads(existing["payload"]),
                "replayed": True,
            }
        cur = con.execute(
            "INSERT INTO tickets(tenant,request_key,payload) VALUES(?,?,?)",
            (principal["tenant"], key, serialized),
        )
        return {"id": cur.lastrowid, **payload, "replayed": False}

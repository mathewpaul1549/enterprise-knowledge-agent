import io
import json
import os
from pathlib import Path
from flask import Flask, request, render_template, g
from pypdf import PdfReader
from knowledge import initialize, ingest, answer, draft_ticket, allowed_chunks

# Public, synthetic demo credentials. Tenant and role are resolved on the server.
PRINCIPALS = {
    "demo-acme-support": {"tenant": "acme", "roles": ["support"]},
    "demo-acme-admin": {"tenant": "acme", "roles": ["support", "admin"]},
    "demo-beta-support": {"tenant": "beta", "roles": ["support"]},
}


def create_app(database=None, seed=True):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1_100_000
    dbpath = database or os.getenv("DATABASE_PATH", "data/knowledge.sqlite3")
    initialize(dbpath)
    if seed:
        for doc in json.loads(
            (Path(__file__).parent / "samples/documents.json").read_text()
        ):
            try:
                ingest(dbpath, doc)
            except ValueError as exc:
                if "newer version" not in str(exc):
                    raise

    @app.before_request
    def auth():
        if request.path.startswith("/api/"):
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            g.principal = PRINCIPALS.get(token)
            if not g.principal:
                return {
                    "error": "Use one of the documented synthetic demo credentials"
                }, 401

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "enterprise-knowledge-agent"}

    @app.get("/api/documents")
    def docs():
        chunks = allowed_chunks(dbpath, g.principal)
        seen = {}
        for c in chunks:
            seen[c["slug"]] = {
                "slug": c["slug"],
                "title": c["title"],
                "version": c["version"],
            }
        return {"principal": g.principal, "documents": list(seen.values())}

    @app.post("/api/search")
    def search():
        return answer(dbpath, g.principal, body().get("query"))

    @app.post("/api/tickets")
    def ticket():
        b = body()
        return (
            draft_ticket(
                dbpath,
                g.principal,
                b.get("request_key"),
                b.get("query"),
                b.get("citation_ids", []),
            ),
            201,
        )

    @app.post("/api/ingest")
    def upload():
        if "admin" not in g.principal["roles"]:
            return {"error": "Admin role required"}, 403
        b = body()
        if b.get("tenant") not in (None, g.principal["tenant"]):
            return {"error": "Tenant mismatch"}, 403
        b["tenant"] = g.principal["tenant"]
        return ingest(dbpath, b), 201

    @app.post("/api/ingest-file")
    def file_upload():
        if "admin" not in g.principal["roles"]:
            return {"error": "Admin role required"}, 403
        file = request.files.get("file")
        if not file:
            raise ValueError("File required")
        data = file.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Document exceeds 1 MB")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix == ".pdf":
            try:
                reader = PdfReader(io.BytesIO(data))
                if len(reader.pages) > 30:
                    raise ValueError("PDF limit is 30 pages")
                content = "\n\n".join(p.extract_text() or "" for p in reader.pages)
            except Exception as exc:
                raise ValueError("Readable PDF with at most 30 pages required") from exc
        elif suffix in {".md", ".txt"}:
            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("UTF-8 text required") from exc
        else:
            raise ValueError("Use .md, .txt or a text PDF")
        try:
            version = int(request.form.get("version", "1"))
        except ValueError:
            raise ValueError("Integer version required")
        doc = {
            "tenant": g.principal["tenant"],
            "slug": request.form.get("slug"),
            "title": request.form.get("title"),
            "version": version,
            "roles": request.form.getlist("roles"),
            "body": content,
        }
        return ingest(dbpath, doc), 201

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    @app.errorhandler(ValueError)
    def invalid(exc):
        return {"error": str(exc)}, 400

    @app.errorhandler(413)
    def large(_):
        return {"error": "File too large; limit 1 MB"}, 413

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=int(os.getenv("PORT", "8102")))

import json, platform, statistics, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent

from knowledge import initialize, ingest, answer

cases = json.loads((ROOT / "samples/questions.json").read_text())
results = []
latencies = []
with tempfile.TemporaryDirectory() as tmp:
    path = str(Path(tmp) / "eval.db")
    initialize(path)
    for d in json.loads((ROOT / "samples/documents.json").read_text()):
        ingest(path, d)
    for c in cases:
        start = time.perf_counter()
        r = answer(path, {"tenant": "acme", "roles": ["support"]}, c["query"])
        latencies.append((time.perf_counter() - start) * 1000)
        found = [x["document"] for x in r["citations"]]
        expected = c["expected_document"]
        results.append(
            {
                **c,
                "retrieved": found,
                "status": r["status"],
                "correct": (
                    expected in found if expected else r["status"] == "abstained"
                ),
            }
        )
positive = [r for r in results if r["expected_document"]]
negative = [r for r in results if not r["expected_document"]]
report = {
    "run_utc": datetime.now(timezone.utc).isoformat(),
    "python": platform.python_version(),
    "method": "BM25 lexical retrieval + extractive quotes; no model calls",
    "dataset": "20 authored questions against 6 synthetic documents, Acme support identity; no held-out data",
    "answerable_recall_at_3": sum(r["correct"] for r in positive) / len(positive),
    "unanswerable_abstention_accuracy": sum(r["correct"] for r in negative)
    / len(negative),
    "p50_ms": round(statistics.median(latencies), 3),
    "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 3),
    "cases": results,
    "limitations": "Small regression set. Exact quoted passages are not a human-graded measure of answer helpfulness. Paraphrase/semantic recall and live Eve model grounding remain unmeasured.",
}
(ROOT / "docs/evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))

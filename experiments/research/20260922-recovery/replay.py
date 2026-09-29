"""Read-only comparison of claim policies on one sealed, historical research run.

Run inside the API container (artifact mount read-only), passing the run ID.
No import, LLM invocation, external web fetch, or ledger mutation is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

from mova_fpl.ops.db import sha256_json
from mova_fpl.ops.strategy import StrategicContextService as Validator


def replay(run_id: str, root: Path, api_url: str) -> dict:
    request_path = root / "archive" / f"{run_id}.request.json"
    result_path = root / "archive" / f"{run_id}.result.json"
    request = json.loads(request_path.read_text())
    result = json.loads(result_path.read_text())
    request_hash = sha256_json({k: v for k, v in request.items() if k != "request_sha256"})
    if request_hash != request["request_sha256"] or request_hash != result["request_sha256"]:
        raise ValueError("sealed request hash mismatch")
    with urllib.request.urlopen(api_url + "/api/v1/research/documents?limit=100", timeout=20) as response:
        documents = [d for d in json.load(response)["items"] if d["research_run_id"] == run_id]
    if len(documents) != len(result["documents"]):
        raise ValueError("API page does not contain all run documents; no partial replay")
    sealed = 0
    for document in documents:
        document["publication_date_verified"] = False
        if document["artifact_path"]:
            body = Path(document["artifact_path"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != document["artifact_sha256"]:
                raise ValueError("evidence artifact hash mismatch")
            evidence = json.loads(body)
            for key in ("document_id", "research_run_id", "source_url", "excerpt_sha256"):
                if evidence[key] != document[key]:
                    raise ValueError("evidence binding mismatch: " + key)
            document["publication_date_verified"] = evidence.get("publication_date_verified", False)
            sealed += 1
    by_url = {d["source_url"]: d for d in documents}
    summary = request["manifest"]["research_summary"]
    catalog = {int(row[0]): str(row[1]) for row in summary["world"]["catalog"]}
    counts = Counter(name.casefold() for name in catalog.values())
    observed = datetime.fromisoformat(documents[0]["observed_at"])
    if any(d["observed_at"] != documents[0]["observed_at"] for d in documents):
        raise ValueError("mixed import timestamps")
    cutoff = datetime.fromisoformat(request["manifest"]["deadline_at"].replace("Z", "+00:00"))
    conflicts = Validator._validate_conflicts(result.get("conflicts", []), by_url)
    keys = {(c["subject"].casefold(), c["claim_type"]) for c in conflicts if c["status"] == "unresolved"}
    report = {
        "schema": "mova-research-frozen-policy-replay-v1", "run_id": run_id,
        "observed_at": observed.isoformat(), "request_sha256": request_hash,
        "result_file_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "documents": len(documents), "sealed_artifacts_verified": sealed,
        "verified_documents": sum(d["fetch_status"] == "verified" for d in documents),
        "date_verified_documents": sum(d["publication_date_verified"] for d in documents),
        "llm_calls": 0, "runtime_ledger_mutated": False, "results": [],
    }
    for freshness in (False, True):
        signals = Validator._validate_signals(
            result["signals"], by_url, keys, observed, require_verified=True,
            catalog=catalog, cutoff=cutoff, catalog_name_counts=counts,
            require_freshness=freshness,
        )
        coverage = Validator._validate_coverage(
            result["coverage"], summary["focus"], by_url, signals, legacy=False,
            catalog=catalog, fetched_at=observed, cutoff=cutoff, require_freshness=freshness,
        )
        report["results"].append({
            "policy": "research-claim-2026.09." + ("2" if freshness else "1"),
            "accepted_signals": sum(s["validation_status"] == "accepted" for s in signals),
            "candidate_signals": sum(s["validation_status"] == "candidate" for s in signals),
            "quality_reasons": dict(Counter(s["quality"]["reason"] or "supported" for s in signals)),
            "coverage": {k: coverage[k] for k in (
                "status", "required_subjects", "checked_subjects", "evidence_verified_subjects",
                "coverage_ratio", "evidence_ratio",
            )},
            "unresolved_conflicts": len(keys),
        })
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--root", type=Path, default=Path("/var/lib/mova-fpl/artifacts/research"))
    parser.add_argument("--api-url", default="http://127.0.0.1:8787")
    args = parser.parse_args()
    print(json.dumps(replay(args.run_id, args.root, args.api_url), indent=2))

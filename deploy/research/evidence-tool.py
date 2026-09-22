#!/usr/bin/env python3
"""Bounded stdio MCP adapter; no database, credentials or model-selected file paths."""
from __future__ import annotations
import hashlib
import json
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# The image copies only these two stdlib modules, not the runtime application.
from research_evidence import SafeEvidenceFetcher, canonical_public_url
from research_quality import claim_fresh, claim_supported, subject_in_excerpt, TOPIC_WORDS

TOOL = {
    "name": "verify_research_evidence",
    "description": "Independently GET a public HTTPS source and verify an exact excerpt, publication date, player identity and claim freshness. Diagnostic only: final importer rechecks. Correct failed evidence or leave not_checked; never infer acceptance from this tool.",
    "inputSchema": {"type": "object", "additionalProperties": False,
        "required": ["source_url", "evidence_text", "published_at", "player_element", "claim_type"],
        "properties": {
            "source_url": {"type": "string", "maxLength": 2048},
            "evidence_text": {"type": "string", "minLength": 1, "maxLength": 800},
            "published_at": {"type": "string", "description": "ISO timestamp with timezone, matching publication date on page"},
            "player_element": {"type": "integer", "minimum": 1},
            "claim_type": {"type": "string", "enum": ["coverage", *TOPIC_WORDS]},
        }},
    "annotations": {"readOnlyHint": True, "destructiveHint": False,
                    "idempotentHint": True, "openWorldHint": True},
}


class EvidenceTool:
    def __init__(self, request, root, *, fetcher=None, clock=None):
        self.request = request
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.fetcher = fetcher or SafeEvidenceFetcher(self.root)
        self.calls = 0
        self.cache = {}
        self.max_calls = min(32, max(1, int(request.get("scope_policy", {}).get("max_documents", 6))) * 2)
        self.deadline = datetime.fromisoformat(request["manifest"]["deadline_at"].replace("Z", "+00:00"))
        if self.deadline.tzinfo is None:
            raise ValueError("deadline_timezone_required")
        rows = request["manifest"].get("research_summary", {}).get("world", {}).get("catalog", [])
        self.catalog = {int(row[0]): str(row[1]) for row in rows if isinstance(row, list) and len(row) >= 2}
        self.names = Counter(name.casefold() for name in self.catalog.values())
        self.focus = {row["element"] for row in request["manifest"].get("research_summary", {}).get("focus", [])}

    def verify(self, args):
        started = time.monotonic()
        observed = self.clock()
        if observed >= self.deadline:
            return {"status": "rejected", "reasons": ["fetch_after_cutoff"], "remaining_calls": 0}
        if self.calls >= self.max_calls:
            return {"status": "rejected", "reasons": ["verification_budget_exhausted"], "remaining_calls": 0}
        self.calls += 1
        reasons = []
        expected = set(TOOL["inputSchema"]["required"])
        if (not isinstance(args, dict) or set(args) != expected
                or type(args.get("player_element")) is not int
                or args.get("claim_type") not in ["coverage", *TOPIC_WORDS]
                or not isinstance(args.get("evidence_text"), str)
                or not 1 <= len(args["evidence_text"]) <= 800
                or not isinstance(args.get("source_url"), str)
                or len(args["source_url"]) > 2048
                or not isinstance(args.get("published_at"), str)):
            return {"status": "rejected", "reasons": ["invalid_arguments"],
                    "remaining_calls": self.max_calls - self.calls}
        name = self.catalog.get(args["player_element"])
        if not name:
            reasons.append("unknown_element")
        elif self.names[name.casefold()] > 1:
            reasons.append("ambiguous_identity")
        try:
            url = canonical_public_url(args["source_url"])
        except (ValueError, UnicodeError):
            reasons.append("invalid_public_url")
            url = None
        document = {}
        if not reasons:
            key = hashlib.sha256(json.dumps([url, args["evidence_text"], args["published_at"]]).encode()).hexdigest()
            if key not in self.cache:
                self.cache[key] = self.fetcher.seal(
                    research_run_id=self.request["research_run_id"], document_id="document_" + key[:32],
                    source_url=url, evidence_text=args["evidence_text"], published_at=args["published_at"])
            document = self.cache[key]
            if document["fetch_status"] != "verified":
                reasons.append(document.get("error_code") or "fetch_failed")
            else:
                excerpt = document.get("excerpt") or ""
                supported = (subject_in_excerpt(name, excerpt) if args["claim_type"] == "coverage"
                    else claim_supported(name=name, claim_type=args["claim_type"], excerpt=excerpt))
                if not supported:
                    reasons.append("identity_or_claim_unsupported")
                if not document.get("publication_date_verified"):
                    reasons.append("publication_unknown")
                if not claim_fresh(claim_type=args["claim_type"], published_at=args["published_at"], observed=observed):
                    reasons.append("stale_for_claim")
        if self.clock() >= self.deadline:
            reasons.append("fetch_after_cutoff")
        result = {"schema": "mova-evidence-check-v1", "status": "supported" if not reasons else "rejected",
            "reasons": reasons, "remaining_calls": self.max_calls - self.calls,
            "publication_date_verified": bool(document.get("publication_date_verified")),
            "excerpt_sha256": document.get("excerpt_sha256"),
            "covered_focus_elements": [element for element in sorted(self.focus)
                if document.get("fetch_status") == "verified" and document.get("publication_date_verified")
                and claim_fresh(claim_type="coverage", published_at=args["published_at"], observed=observed)
                and self.catalog.get(element) and self.names[self.catalog[element].casefold()] == 1
                and subject_in_excerpt(self.catalog[element], document.get("excerpt") or "")],
            "final_acceptance": False, "observed_at": observed.isoformat(),
            "duration_ms": int((time.monotonic() - started) * 1000)}
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "checks.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({**result, "player_element": args["player_element"],
                "claim_type": args["claim_type"], "source_sha256": hashlib.sha256((url or "").encode()).hexdigest()}) + "\n")
        return result


def serve(tool):
    for line in sys.stdin:
        if len(line) > 16384:
            continue
        message_id = None
        try:
            message = json.loads(line)
            message_id = message.get("id")
            if message_id is None:
                continue
            method = message.get("method")
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mova-evidence", "version": "1.0.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [TOOL]}
            elif method == "tools/call" and message.get("params", {}).get("name") == TOOL["name"]:
                # Overall per-call deadline includes DNS/read and redirects.
                signal.alarm(25)
                try:
                    value = tool.verify(message["params"].get("arguments"))
                except TimeoutError:
                    value = {"status": "rejected", "reasons": ["verification_timeout"]}
                finally:
                    signal.alarm(0)
                result = {"content": [{"type": "text", "text": json.dumps(value)}],
                          "isError": value["status"] == "rejected"}
            else:
                raise ValueError("unknown_method")
            response = {"jsonrpc": "2.0", "id": message_id, "result": result}
        except Exception:
            response = {"jsonrpc": "2.0", "id": message_id,
                        "error": {"code": -32602, "message": "invalid_request"}}
        print(json.dumps(response), flush=True)


def timeout_handler(*_):
    raise TimeoutError("verification_timeout")


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, timeout_handler)
    request = json.loads(Path(sys.argv[1]).read_text())
    serve(EvidenceTool(request, Path(sys.argv[2])))

#!/usr/bin/env python3
"""Bounded stdio MCP adapter; no database, credentials or model-selected file paths."""
from __future__ import annotations
import hashlib
import json
import signal
import sys
import time
import urllib.request
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

# The image copies only these two stdlib modules, not the runtime application.
from research_evidence import SafeEvidenceFetcher, canonical_public_url, normalize_text, ALLOWED_MIME
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

SEARCH_TOOL = {"name": "search_research_web", "description": "Discover public web URLs from the last seven days with a strict per-run query quota. Results are untrusted discovery, not verified evidence.",
 "inputSchema": {"type": "object", "additionalProperties": False, "required": ["query"],
  "properties": {"query": {"type": "string", "minLength": 3, "maxLength": 400}}},
 "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}}
READ_TOOL = {"name": "read_research_source", "description": "GET a public HTTPS page; return bounded literal text around requested official player names and publication metadata candidates. Validate excerpts before citing.",
 "inputSchema": {"type": "object", "additionalProperties": False, "required": ["source_url", "player_elements"],
  "properties": {"source_url": {"type": "string", "maxLength": 2048},
   "player_elements": {"type": "array", "items": {"type": "integer"}, "maxItems": 32}}},
 "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}}
CONTEXT_TOOL = {"name": "research_context", "description": "Retrieve sealed context on demand. Lookup official players by name; fetch memory or previous signals. No live database access.",
 "inputSchema": {"type": "object", "additionalProperties": False, "required": ["section", "query", "offset"],
  "properties": {"section": {"type": "string", "enum": ["catalog", "memory", "signals", "prior_gameweek_signals", "previous_active_signals", "world_alerts"]},
    "query": {"type": "string", "maxLength": 100}, "offset": {"type": "integer", "minimum": 0}}},
 "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}


class EvidenceTool:
    def __init__(self, request, root, *, fetcher=None, clock=None):
        self.request = request
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.fetcher = fetcher or SafeEvidenceFetcher(self.root)
        self.calls = 0
        self.cache = {}
        self.page_cache = {}
        self.search_calls = 0
        self.read_calls = 0
        self.context_calls = 0
        self.controlled = request.get("agent_release", {}).get("execution") == "app_server"
        self.max_calls = min(32, max(1, int(request.get("scope_policy", {}).get("max_documents", 6))) * 2)
        self.deadline = datetime.fromisoformat(request["manifest"]["deadline_at"].replace("Z", "+00:00"))
        if self.deadline.tzinfo is None:
            raise ValueError("deadline_timezone_required")
        rows = request["manifest"].get("research_summary", {}).get("world", {}).get("catalog", [])
        self.catalog = {int(row[0]): str(row[1]) for row in rows if isinstance(row, list) and len(row) >= 2}
        self.names = Counter(name.casefold() for name in self.catalog.values())
        self.focus = {row["element"] for row in request["manifest"].get("research_summary", {}).get("focus", [])}

    def context(self, args):
        self.context_calls += 1
        if self.context_calls > 8 or set(args) != {"section", "query", "offset"}:
            return {"status": "rejected", "reasons": ["context_budget_or_arguments"]}
        section = args["section"]; offset = args["offset"]
        if type(offset) is not int or offset < 0 or not isinstance(args["query"], str):
            return {"status": "rejected", "reasons": ["invalid_arguments"]}
        summary = self.request["manifest"]["research_summary"]
        if section == "catalog":
            rows = [row for row in summary["world"]["catalog"] if args["query"].casefold() in str(row).casefold()]
        elif section == "world_alerts":
            rows = summary["world"].get("alerts", [])
        elif section == "memory":
            memory = self.request["manifest"].get("memory_summary", {})
            rows = [{"section": key, "value": row} for key, value in memory.items()
                    for row in (value if isinstance(value, list) else [value])]
        elif section in {"signals", "prior_gameweek_signals", "previous_active_signals"}:
            rows = summary.get(section, [])
        else:
            return {"status": "rejected", "reasons": ["unknown_context_section"]}
        page = []
        for row in rows[offset:offset+20]:
            if len(json.dumps(page+[row])) > 6000:
                break
            page.append(row)
        return {"status": "ok", "rows": page, "total": len(rows),
                "next_offset": offset+len(page) if offset+len(page) < len(rows) else None}

    def search(self, args):
        if (set(args) != {"query"} or not isinstance(args["query"], str)
                or not 3 <= len(args["query"]) <= 400):
            return {"status": "rejected", "reasons": ["invalid_arguments"]}
        limit = min(8, int(self.request.get("scope_policy", {}).get("max_web_queries", 4)))
        if self.search_calls >= limit or self.clock() >= self.deadline:
            return {"status": "rejected", "reasons": ["search_budget_or_deadline"]}
        self.search_calls += 1
        try:
            key = Path("/run/secrets/research_search_key").read_text().strip()
        except OSError:
            return {"status": "rejected", "reasons": ["search_not_configured"]}
        if not key:
            return {"status": "rejected", "reasons": ["search_not_configured"]}
        observed = self.clock()
        since = observed - timedelta(days=7)
        req = urllib.request.Request("https://api.firecrawl.dev/v1/search",
            data=json.dumps({"query": args["query"], "limit": 5,
                "tbs": f"cdr:1,cd_min:{since:%m/%d/%Y},cd_max:{observed:%m/%d/%Y}"}).encode(),
            headers={"Authorization": "Bearer "+key, "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read(262145)
                if len(raw) > 262144:
                    raise ValueError("search_response_too_large")
                payload = json.loads(raw)
            rows = payload.get("data", [])
            if not payload.get("success") or not isinstance(rows, list):
                raise ValueError("search_unavailable")
            result = {"status": "ok", "remaining_queries": limit-self.search_calls,
                "results": [{"url": row.get("url"), "title": str(row.get("title", ""))[:200],
                             "description": str(row.get("description", ""))[:400]} for row in rows[:5]]}
        except Exception:
            result = {"status": "rejected", "reasons": ["search_provider_failed"],
                      "remaining_queries": limit-self.search_calls}
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root/"search.jsonl").open("a") as stream:
            stream.write(json.dumps({"query_sha256": hashlib.sha256(args["query"].encode()).hexdigest(),
                                    "status": result["status"], "query_number": self.search_calls, "result_count": len(result.get("results", []))})+"\n")
        return result

    def _get_page(self, url):
        if url not in self.page_cache:
            self.page_cache[url] = (self.fetcher.transport(url) if self.fetcher.transport
                                    else self.fetcher._fetch(url))
        return self.page_cache[url]

    def read_source(self, args):
        if set(args) != {"source_url", "player_elements"} or not isinstance(args["player_elements"], list) or len(args["player_elements"]) > 32 or any(type(x) is not int or x < 1 for x in args["player_elements"]):
            return {"status": "rejected", "reasons": ["invalid_arguments"]}
        if self.read_calls >= self.max_calls or self.clock() >= self.deadline:
            return {"status": "rejected", "reasons": ["read_budget_or_deadline"]}
        self.read_calls += 1
        try:
            url = canonical_public_url(args["source_url"])
            payload, meta = self._get_page(url)
            if meta["content_type"].split(";")[0].strip().lower() not in ALLOWED_MIME:
                raise ValueError("mime_not_allowed")
            text = normalize_text(payload, meta["content_type"])
            snippets = []
            for element in args["player_elements"]:
                name = self.catalog.get(element, "")
                if not name: continue
                positions = [m.start() for m in re.finditer(re.escape(name),text,re.IGNORECASE)]
                for position in positions[:3]:
                    snippet = text[max(0,position-150):position+600]
                    if snippet not in snippets and sum(map(len,snippets)) + len(snippet) <= 6000:
                        snippets.append(snippet)
            if not snippets: snippets = [text[:2400]]
            dates = re.findall(r'"date(?:Published|Modified)"\s*:\s*"([^"]{1,60})"', payload.decode("utf-8", "ignore"))[:4]
            return {"status": "ok", "source_url": url, "publication_candidates": dates,
                    "literal_fragments": snippets, "truncated": True,
                    "remaining_reads": self.max_calls-self.read_calls}
        except Exception:
            return {"status": "rejected", "reasons": ["source_read_failed"]}

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
                self.cache[key] = SafeEvidenceFetcher(self.root, transport=self._get_page).seal(
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
                result = {"tools": [TOOL, SEARCH_TOOL, READ_TOOL, CONTEXT_TOOL] if tool and tool.controlled else [TOOL]}
            elif method == "tools/call" and message.get("params", {}).get("name") in ([TOOL["name"], SEARCH_TOOL["name"], READ_TOOL["name"], CONTEXT_TOOL["name"]] if tool and tool.controlled else [TOOL["name"]]):
                # Overall per-call deadline includes DNS/read and redirects.
                signal.alarm(25)
                try:
                    handler = {TOOL["name"]: tool.verify, SEARCH_TOOL["name"]: tool.search,
                               READ_TOOL["name"]: tool.read_source, CONTEXT_TOOL["name"]: tool.context}[message["params"]["name"]]
                    value = handler(message["params"].get("arguments"))
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

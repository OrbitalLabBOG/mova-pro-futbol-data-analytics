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
from html.parser import HTMLParser
from urllib.parse import urljoin
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

# The image copies only these two stdlib modules, not the runtime application.
from research_evidence import SafeEvidenceFetcher, canonical_public_url, normalize_text, ALLOWED_MIME
from research_quality import claim_fresh, claim_supported, subject_in_excerpt, TOPIC_WORDS, _normal, research_identity_catalog

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
   "player_elements": {"type": "array", "items": {"type": "integer"}, "maxItems": 32},
   "offset": {"type": "integer", "minimum": 0}}},
 "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}}
CONTEXT_TOOL = {"name": "research_context", "description": "Retrieve sealed context on demand. Lookup official players by name; fetch memory or previous signals. No live database access.",
 "inputSchema": {"type": "object", "additionalProperties": False, "required": ["section", "query", "offset"],
  "properties": {"section": {"type": "string", "enum": ["catalog", "memory", "signals", "prior_gameweek_signals", "previous_active_signals", "world_alerts", "focus_progress"]},
    "query": {"type": "string", "maxLength": 100}, "offset": {"type": "integer", "minimum": 0}}},
 "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}


class DiscoveryLinks(HTMLParser):
    """Bounded navigation hints only; never evidence or an automatic fetch."""
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag != "a": return
        self.current = None
        href = dict(attrs).get("href", "")
        if not href or len(href) > 2048 or href.startswith(("#", "mailto:", "javascript:")): return
        try: url = canonical_public_url(urljoin(self.base, href))
        except Exception: return
        if url == self.base or any(row["source_url"] == url for row in self.links): return
        self.current = {"source_url": url, "title": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] = (self.current["title"] + " " + data).strip()[:160]

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append(self.current)
            self.links.sort(key=self.priority)
            del self.links[64:]
            self.current = None

    @staticmethod
    def priority(row):
        return (-bool(re.search(r"injur|team.news|press.conference|availability", row["title"], re.I)),
                -bool(re.search(r"/detail/|/articles/|/20[0-9]{2}/|/A/[0-9]", row["source_url"])))


class ClubWorkQueue:
    """Per-request checkpoint shared by bounded retries, never acceptance evidence."""
    def __init__(self, request, root):
        self.binding = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        run_id = request["research_run_id"]
        if not re.fullmatch(r"research_[0-9a-f]{32}", run_id):
            raise ValueError("invalid_work_queue_run")
        self.path = Path(root).parent / (run_id + ".work-queue.json")
        groups = {}
        summary = request["manifest"]["research_summary"]
        needs = set(summary.get("work_progress", {}).get("needs_checking_elements",
                    [row["element"] for row in summary["focus"]]))
        for row in summary["focus"]:
            team = row.get("team") or "unknown:" + str(row["element"])
            group = groups.setdefault(team, {"team": team, "elements": [], "own": 0, "pending_elements": [], "own_pending": 0})
            group["elements"].append(row["element"])
            group["own"] += "current_squad" in row.get("focus_reason", [])
            if row["element"] in needs:
                group["pending_elements"].append(row["element"])
                group["own_pending"] += "current_squad" in row.get("focus_reason", [])
        self.groups = sorted(groups.values(), key=lambda row: (-row["own_pending"], -len(row["pending_elements"]), -row["own"], row["team"]))
        if self.path.exists():
            if self.path.is_symlink() or self.path.stat().st_size > 16384:
                raise ValueError("unsafe_work_queue_checkpoint")
            self.state = json.loads(self.path.read_text())
            if self.state.get("request_binding") != self.binding:
                raise ValueError("work_queue_request_drift")
            counts = self.state.get("searches", {})
            if set(counts) != set(groups) or any(type(n) is not int or n < 0 for n in counts.values()):
                raise ValueError("invalid_work_queue_checkpoint")
            if type(self.state.get("global_searches")) is not int or not 0 <= self.state["global_searches"] <= 1:
                raise ValueError("invalid_work_queue_checkpoint")
            reads = self.state.get("club_reads", {})
            if set(reads) - set(groups) or any(type(n) is not int or n < 0 for n in reads.values()):
                raise ValueError("invalid_club_read_checkpoint")
            hashes = self.state.get("query_hashes", [])
            if (not isinstance(hashes,list) or len(hashes)>32
                    or any(not isinstance(x,str) or not re.fullmatch(r"[0-9a-f]{64}",x) for x in hashes)):
                raise ValueError("invalid_query_checkpoint")
            counters = self.state.get("tool_calls", {})
            if set(counters) - {"read", "verify", "context"} or any(type(n) is not int or n < 0 for n in counters.values()):
                raise ValueError("invalid_tool_quota_checkpoint")
        else:
            self.state = {"request_binding": self.binding, "searches": dict.fromkeys(groups, 0),
                          "global_searches": 0}

    def snapshot(self):
        pending = [row for row in self.groups if not self.state["searches"][row["team"]]]
        return {"schema": "mova-club-work-queue-v1", "next_club": pending[0] if pending else None,
                "unattempted_clubs": len(pending), "club_searches": self.state["searches"].copy(),
                "global_searches": self.state["global_searches"],
                "coverage_verified": False, "final_acceptance": False}

    def consume(self, team, limit, query_key=None):
        if query_key and query_key in self.state.get("query_hashes", []):
            return "duplicate_query"
        count = sum(self.state["searches"].values()) + self.state["global_searches"]
        if count >= limit:
            return "search_budget_or_deadline"
        pending = self.snapshot()["next_club"]
        if team is None:
            if self.state["global_searches"]:
                return "global_radar_already_attempted"
            # Do not let the optional radar consume a first-pass club reservation.
            if limit - count <= self.snapshot()["unattempted_clubs"]:
                return "club_first_pass_budget_reserved"
            self.state["global_searches"] += 1
        elif team not in self.state["searches"]:
            return "unknown_work_item"
        elif pending and team != pending["team"]:
            return "unattempted_club_has_priority"
        else:
            self.state["searches"][team] += 1
        if query_key:
            self.state.setdefault("query_hashes", []).append(query_key)
        self.save()
        return None

    def consume_club_read(self, elements, limit):
        teams = [row["team"] for row in self.groups if set(elements) & set(row["elements"])]
        if len(teams) != 1 or not elements: return False
        group = next(row for row in self.groups if row["team"] == teams[0])
        if not set(elements) <= set(group["elements"]): return False
        counts = self.state.setdefault("club_reads", {})
        base, extra = divmod(limit, len(self.groups))
        allocation = base + (self.groups.index(group) < extra)
        if self.state.get("searches") and any(n==0 for n in self.state["searches"].values()):
            allocation = min(allocation, 3)
        if counts.get(teams[0], 0) >= allocation: return False
        counts[teams[0]] = counts.get(teams[0], 0) + 1
        self.save()
        return True

    def consume_tool(self, name, limit):
        counters = self.state.setdefault("tool_calls", {})
        if counters.get(name, 0) >= limit:
            return False
        counters[name] = counters.get(name, 0) + 1
        self.save()
        return True

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, sort_keys=True) + "\n")
        tmp.chmod(0o660)
        tmp.replace(self.path)


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
        self.navigation = request.get("agent_release", {}).get("source_navigation") == "public_links_v1"
        self.compact = request.get("agent_release", {}).get("source_delivery") == "compact_focus_v1"
        self.max_calls = min(32, max(1, int(request.get("scope_policy", {}).get("max_documents", 6))) * 2)
        self.deadline = datetime.fromisoformat(request["manifest"]["deadline_at"].replace("Z", "+00:00"))
        if self.deadline.tzinfo is None:
            raise ValueError("deadline_timezone_required")
        rows = request["manifest"].get("research_summary", {}).get("world", {}).get("catalog", [])
        self.catalog = research_identity_catalog(request)
        self.names = Counter(name.casefold() for name in self.catalog.values())
        self.focus = {row["element"] for row in request["manifest"].get("research_summary", {}).get("focus", [])}
        self.verified_focus = set()
        self.work_queue = (ClubWorkQueue(request, self.root)
                           if request.get("agent_release", {}).get("coverage_allocation")
                           == "club_work_queue_v1" else None)
        if self.work_queue:
            self.search_calls = (sum(self.work_queue.state["searches"].values())
                                 + self.work_queue.state["global_searches"])
        self.shared_tool_quota = (self.work_queue if request.get("agent_release", {}).get("execution_profile")
                                 == "club_sessions_v1" else None)
        if self.shared_tool_quota:
            counters = self.work_queue.state.get("tool_calls", {})
            self.read_calls = counters.get("read", 0)
            self.calls = counters.get("verify", 0)
            self.context_calls = counters.get("context", 0)

    def search_schema(self):
        schema = json.loads(json.dumps(SEARCH_TOOL))
        if self.work_queue:
            schema["inputSchema"]["properties"]["team"] = {"type": "string", "maxLength": 80}
        return schema

    def context(self, args):
        if self.shared_tool_quota and not self.shared_tool_quota.consume_tool("context", 8):
            return {"status": "rejected", "reasons": ["context_budget_or_arguments"]}
        self.context_calls += 1
        if self.context_calls > 8 or set(args) != {"section", "query", "offset"}:
            return {"status": "rejected", "reasons": ["context_budget_or_arguments"]}
        section = args["section"]; offset = args["offset"]
        if type(offset) is not int or offset < 0 or not isinstance(args["query"], str):
            return {"status": "rejected", "reasons": ["invalid_arguments"]}
        summary = self.request["manifest"]["research_summary"]
        if section == "focus_progress":
            rows = [{**row, "evidence_verified_in_turn": row["element"] in self.verified_focus,
                     "final_acceptance": False}
                    for row in summary.get("focus", []) if row["element"] not in self.verified_focus]
            if self.compact:
                rows = [{key: row[key] for key in ("element", "player_name", "team",
                         "evidence_verified_in_turn", "final_acceptance") if key in row} for row in rows]
        elif section == "catalog":
            query = _normal(args["query"]).strip()
            catalog = summary["world"]["catalog"]
            rows = [row for row in catalog if query in _normal(str(row))]
            if not rows and query:
                terms = [word for word in re.findall(r"[a-z0-9]+",query) if len(word)>=3]
                scored = [(sum(bool(re.search(r"\b"+re.escape(term)+r"\b",_normal(str(row))))
                               for term in terms),row) for row in catalog]
                rows = [row for score,row in sorted(scored,key=lambda pair:-pair[0]) if score]
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
        if (not isinstance(args, dict) or "query" not in args
                or set(args) - ({"query", "team"} if self.work_queue else {"query"}) or not isinstance(args["query"], str)
                or not 3 <= len(args["query"]) <= 400
                or ("team" in args and (not isinstance(args["team"], str) or not 1 <= len(args["team"]) <= 80))):
            return {"status": "rejected", "reasons": ["invalid_arguments"]}
        query_ceiling = 32 if self.request.get("agent_release", {}).get("completion_campaign") else 16 if self.request.get("agent_release", {}).get("discovery_profile") == "expanded_broad_v1" else 8
        limit = min(query_ceiling, int(self.request.get("scope_policy", {}).get("max_web_queries", 4)))
        if self.search_calls >= limit or self.clock() >= self.deadline:
            return {"status": "rejected", "reasons": ["search_budget_or_deadline"]}
        if self.work_queue:
            reason = self.work_queue.consume(args.get("team"), limit,
                hashlib.sha256(" ".join(args["query"].casefold().split()).encode()).hexdigest()
                if self.request.get("agent_release", {}).get("completion_campaign") else None)
            if reason:
                return {"status": "rejected", "reasons": [reason],
                        "work_queue": self.work_queue.snapshot()}
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
                             "description": str(row.get("description", ""))[:160 if self.compact else 400]} for row in rows[:5]]}
        except Exception:
            result = {"status": "rejected", "reasons": ["search_provider_failed"],
                      "remaining_queries": limit-self.search_calls}
        self.root.mkdir(parents=True, exist_ok=True)
        if self.work_queue:
            result["work_queue"] = self.work_queue.snapshot()
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
        if (not isinstance(args,dict) or not {"source_url", "player_elements"} <= set(args)
                or set(args)-{"source_url", "player_elements", "offset"}
                or not isinstance(args["player_elements"], list) or len(args["player_elements"]) > 32
                or any(type(x) is not int or x < 1 for x in args["player_elements"])
                or type(args.get("offset",0)) is not int or args.get("offset",0)<0):
            return {"status": "rejected", "reasons": ["invalid_arguments"]}
        if self.read_calls >= self.max_calls or self.clock() >= self.deadline:
            return {"status": "rejected", "reasons": ["read_budget_or_deadline"]}
        if (self.navigation and self.shared_tool_quota
                and not self.shared_tool_quota.consume_club_read(args["player_elements"], self.max_calls)):
            return {"status": "rejected", "reasons": ["club_read_allocation_exhausted_or_scope_invalid"]}
        if self.shared_tool_quota and not self.shared_tool_quota.consume_tool("read", self.max_calls):
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
                if not positions and self.request.get("agent_release", {}).get("completion_campaign"):
                    surname = name.split()[-1]
                    if len(surname) >= 4:
                        positions = [m.start() for m in re.finditer(r"\b"+re.escape(surname)+r"\b",text,re.IGNORECASE)]
                for position in positions[:1 if self.compact else 3]:
                    snippet = text[max(0,position-100 if self.compact else position-150):position+(350 if self.compact else 600)]
                    if snippet not in snippets and sum(map(len,snippets)) + len(snippet) <= (2400 if self.compact else 6000):
                        snippets.append(snippet)
            if not snippets and not self.compact: snippets = [text[:2400]]
            raw_text = payload.decode("utf-8", "ignore")
            sections = [normalize_text(match.group(1).encode(), meta["content_type"])
                        for match in re.finditer(r'<(?:article|main)\b[^>]*>(.*?)</(?:article|main)\s*>', raw_text, re.I | re.S)]
            article_text = max(sections, key=len, default="")
            extraction = "substantive_region"
            if len(article_text) < 300:
                article_text = text
                extraction = "full_page_fallback"
            if not article_text.strip():
                return {"status": "rejected", "reasons": ["source_body_unavailable"],
                        "remaining_reads": self.max_calls-self.read_calls}
            offset = args.get("offset",0)
            page_size = 1200 if self.compact else 8000
            dates = re.findall(r'"date(?:Published|Modified)"\s*:\s*"([^"]{1,60})"', payload.decode("utf-8", "ignore"))[:4]
            navigation = {}
            if self.navigation and "html" in meta["content_type"].lower():
                parser = DiscoveryLinks(canonical_public_url(meta.get("final_url", url)))
                parser.feed(raw_text)
                navigation = {"discovery_links": parser.links[:8], "links_are_evidence": False}
            return {**navigation, "status": "ok", "source_url": url, "extraction": extraction, "publication_candidates": dates,
                    "literal_fragments": snippets, "article_text": article_text[offset:offset+page_size],
                    "next_offset": offset+page_size if offset+page_size<len(article_text) else None,
                    "truncated": offset+page_size<len(article_text),
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
        if self.shared_tool_quota and not self.shared_tool_quota.consume_tool("verify", self.max_calls):
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
                    else claim_supported(name=name, claim_type=args["claim_type"], excerpt=excerpt,
                        quality_policy=self.request.get("quality_policy")))
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
            "verified_document": {"source_url": url, "published_at": args["published_at"],
                "evidence_text": document.get("excerpt")} if not reasons else None,
            "covered_focus_elements": [element for element in sorted(self.focus)
                if document.get("fetch_status") == "verified" and document.get("publication_date_verified")
                and claim_fresh(claim_type="coverage", published_at=args["published_at"], observed=observed)
                and self.catalog.get(element) and self.names[self.catalog[element].casefold()] == 1
                and subject_in_excerpt(self.catalog[element], document.get("excerpt") or "")],
            "final_acceptance": False,
            "support_scope": "single source only; final signal acceptance requires an official source or two independent hosts supporting the SAME named claim",
            "observed_at": observed.isoformat(),
            "duration_ms": int((time.monotonic() - started) * 1000)}
        if result["status"] == "supported":
            self.verified_focus.update(result["covered_focus_elements"])
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
                result = {"tools": [TOOL, tool.search_schema(), READ_TOOL, CONTEXT_TOOL] if tool and tool.controlled else [TOOL]}
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
    if request.get("agent_release", {}).get("execution") == "app_server":
        try:
            configured = bool(Path("/run/secrets/research_search_key").read_text().strip())
        except OSError:
            configured = False
        if not configured:
            raise SystemExit("search_not_configured")
    serve(EvidenceTool(request, Path(sys.argv[2])))

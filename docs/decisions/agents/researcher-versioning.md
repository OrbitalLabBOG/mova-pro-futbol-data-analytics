---
type: adr
name: Researcher versions and isolated evaluations
created: 2026-09-22
status: experimental
owner: Julián Zuluaga
---

# Researcher versions and isolated evaluations

The agent is a versioned runtime component, not merely a model name. Its registry is
`deploy/research/agent-releases.json`. Each entry fixes expected model/reasoning,
interactive tool availability, output contract and quality policy; each physical
attempt records the selected version, effective model/reasoning, implementation hash,
request hash and exact context hash/bytes. Git commit and image digest fix all source
dependencies. Never overwrite historical receipts or claim an environment override
ran the default model. A release changes `active` only after measured evaluation.
Owner and promotion authority: Julián; this iteration is explicitly authorized.

`1.0.0` is the existing researcher. Candidate `1.1.0` adds bounded stdio MCP
`verify_research_evidence@1.0.0`, reusing the exact stdlib source-fetch and quality
modules used by the final importer. It has no DB, SQL, shell, authenticated FPL,
browser or credential-reading tool. Inputs are URL/excerpt/date/element/claim type;
output is diagnostic reasons, remaining calls, verified focus IDs and hashes.
The host chooses request/artifact paths. Max 32 calls and twice document budget,
25 seconds per call, 8 seconds per HTTP operation, 2 MiB response, 800-character
excerpt. URLs use existing public HTTPS/DNS/redirect guards. The tool does not
validate source-tier classification, conflict resolution or the complete meaning of
claims, and never grants acceptance. Final import independently re-fetches.

The experimental CLI seals up to two variants against one manifest with normal
budget reservations and host attempt authorization. Outcomes finish as `completed`
(not `imported`), store evaluation artifacts and settle actual token receipts.
No research_documents/signals/conflicts are published and no GW coverage gate counts
these rows. Existing SQLite enum supports completed; no new database migration.
The normal timer must be excluded with the host research lock while experimental
code evaluates its pending requests. Existing production importer must never consume
experiment requests until this isolation change is deployed.

Acceptance: adversarial tool tests (wrong excerpt, date, identity, SSRF, quota,
deadline), stdio protocol/real Codex compatibility, equivalent input/budget comparison,
quality and token evidence, full suite, image smoke and doctor. A candidate with no
useful verified evidence or an overrun cannot be described as successfully promoted.
The cross-GW autonomy gate is separate from promoting a better researcher version.

H01/H08/H11/H13 map to tests/test_research_evidence_tool.py,
tests/test_research_worker_contract.py and tests/test_research_evidence.py; operational
health remains doctor.research_worker and doctor.agent_queue_integrity. No new entry
is registered in the separate Orbix Web catalog: no equivalent FPL evidence function
exists there, and this is the MOVA isolated worker boundary.

Protocol sources: [MCP stdio](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
and [Codex MCP configuration](https://developers.openai.com/codex/config-reference).

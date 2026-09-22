---
type: adr
name: Researcher versions and isolated evaluations
created: 2026-09-22
status: experimental
owner: Julián Zuluaga
---

# Researcher versions and isolated evaluations

The agent is a versioned runtime component, not merely a model name. Its registry is
`mova_fpl/ops/agent_releases.json`. Each entry fixes expected model/reasoning,
interactive tool availability, output contract and quality policy; each physical
attempt records the selected version, effective model/reasoning, implementation hash,
request hash and exact context hash/bytes. New requests seal the selected version
and definition before enqueue; unknown versions or definition drift fail before paid dispatch. Git commit and image digest fix all source
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

## Metered candidate 1.2.0 and experiment outcome (2026-09-22)

Candidate 1.2.0 uses one ephemeral Codex app-server turn per host permit, with
native web search disabled. Its MCP surface is `search_research_web`,
`read_research_source`, `research_context`, and `verify_research_evidence`.
Search uses the existing Orbital Firecrawl service with a dedicated read-only
secret mount from `compose.research-lab.yaml`; the normal deployment does not yet
mount it. No tool exposes the credential. Initial context retains the objective,
focus and bounded world alerts; catalog, memory and historical signals remain
available from the same sealed request through bounded context retrieval.

The client observes total input plus output tokens, including cached input, and
interrupts at 80,000 observed tokens. This is a reactive guard, not a provider hard
cap: an in-flight response can overshoot. Interrupted usage stays unknown for
accounting; observed usage is telemetry, never falsely reported as final usage.
There is no automatic retry or extra repair turn.

Experiment `researchexp_1d8ad24677ccc54fd9e1268c5d6c9d1c` produced:

| Version | Outcome | Tokens | Verified subjects | Accepted signals |
| --- | --- | ---: | ---: | ---: |
| 1.0.0 | Completed experimental baseline | 615,333 | 1/25 | 0 |
| 1.1.0 | Blocked before host authorization | 0 | Not evaluated | Not evaluated |
| 1.2.0 | Real app-server/tool startup verified; no inference dispatched | 0 | Not evaluated | Not evaluated |

Baseline input was 608,125 tokens, output 7,208; elapsed time 234,898 ms.
Seven documents yielded six successful fetches and four dated sources, but only
4% subject coverage and one unresolved conflict. Fetch success is not useful
research coverage. The 455,333-token job overrun remains reviewed, not resolved.
No experimental signals, documents or conflicts were published into operational
research tables and these runs do not count toward cross-GW autonomy.

The blocked 1.1.0 request initially retained a conservative 120,000-token charge.
`strategy research reconcile-experiment` released it only after checking the
sealed request hash, terminal budget rejection, zero authorization rows and zero
attempt events. The previous charge and proof remain audited. This exception must
never be used for uncertain or partially dispatched inference.

The real Codex 0.144.6 preflight on image `research-lab-698c9ec` successfully
initialized an ephemeral thread and listed all four MCP tools without `turn/start`.
The deterministic suite passed 1,820 tests (one skipped, 79 deselected), followed
by 24 targeted checks after preflight adjustments. These results validate contracts
and startup, not research quality or the effectiveness of the token guard in live
inference. Active version remains 1.0.0 and production remains 85365e8.

Next promotion gate: run a bounded 1.2.0 experiment after an explicitly authorized
experimental budget is available; inspect useful accepted evidence, coverage,
conflicts, input/output/cached tokens, tool failures and elapsed time. A new prepared
manifest is not a paired comparison with the old baseline. To claim a paired
comparison, reuse an identical sealed input/cutoff and report source availability
changes. Integrate the search mount into the normal cycle before deployment,
verify image/revision, doctor and rollback, then change the active registry version.
Do not promote based on protocol tests or erase the real baseline overrun.

Future agents reuse this registry pattern: independent semantic version per agent,
immutable sealed release definition per request, effective model and implementation
identity per attempt, explicit experimental/promotion status and domain-specific
quality gates. A model alias alone is not an agent version. No general-purpose agent
platform or additional persistence service is required for this iteration.


## Authorized campaign continuation — 2026-09-22

Julián explicitly authorized additional experimental consumption until a promotable
agent is demonstrated. This supersedes the earlier pending-budget question. The lab
uses documented per-command policy overrides (10M GW / 20M month, 400k per job),
sealed in each reservation with actor/reason/idempotency key; production environment
files and FPL permissions are unchanged. These are campaign capacity, not a target
spend or evidence of model quality. Full logical tokens include cached input and
must not be presented as a USD invoice.

The first live 1.2.0 run was interrupted at 92,946 observed tokens after exhausting
eight searches and issuing oversized read arguments. Its final provider usage is
unknown; the conservative charge remains, and observed usage is not mislabeled as
exact. Version 1.3.0 fixed current-date guidance, read batching and model selection,
and completed on Terra at 245,365 tokens, but produced zero verified subjects and
zero accepted signals. Neither result supports promotion.

The next paired variants are 1.4.0 (Terra) and 1.5.0 (Astra), with identical current
context, budgets and tools. Discovery is constrained to the last seven days using
Firecrawl's documented `tbs` date range. The tool reuses a safely fetched page within
one turn across reading and verification; final import still independently fetches.
Multiple literal occurrences reduce title/navigation clipping. Evidence freshness,
identity and acceptance requirements remain unchanged. Failed sealed experiments
terminate after one completed failed attempt instead of silently retrying.

App-server telemetry is written incrementally, and spawn/pipe failure rejects pending
RPCs promptly. The comparison script reports failed attempts and observed usage
without fabricating missing evaluations. Local full suite: 1,825 passed, one skipped,
79 deselected at baa265d. Live evaluation remains the promotion authority.

Search contract source: [Firecrawl v1 OpenAPI](https://github.com/firecrawl/firecrawl/blob/main/apps/api/openapi.json).

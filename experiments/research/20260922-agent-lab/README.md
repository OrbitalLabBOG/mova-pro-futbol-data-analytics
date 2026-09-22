---
type: experiment
name: Researcher evidence lab — 2026-09-22
created: 2026-09-22
status: experimental
owner: Julián Zuluaga
---

# Researcher evidence lab

Goal: produce useful, source-grounded research with reproducible context, cost,
isolation and rollback. Julián authorized the campaign, including increased token
capacity. Runtime FPL authority remains A0/shadow with writes disabled.

`results.json` contains sanitized measurements extracted by
`../compare_agents.py` from sealed requests, terminal attempt receipts, evaluations
and tool telemetry. Raw sources, prompts, auth and player records remain outside
Git. The VPS archive is authoritative; hashes identify evaluated artifacts.

| Variant | Observation |
| --- | --- |
| 1.0.0 | Luna baseline: 615,333 tokens, 1/25 focus, zero accepted signals; overrun reviewed, not erased. |
| 1.1.0 | Never authorized or dispatched; exact zero reconciled with audited proof. |
| 1.2.0 | Guard interrupted after 92,946 observed tokens. Final usage unknown, conservative charge retained. |
| 1.3.0 | Terra completed, 245,365 tokens, no verified focus. |
| 1.4.0 | Date-filtered search: 272,171 tokens, one verified focus. |
| 1.5.0 | Astra rejected by obsolete CLI; dispatched attempt and conservative charge retained. |
| 1.4.1 / 1.5.1 | Same-manifest Terra/Astra comparison on Codex 0.153.4. 267,910 / 253,505 tokens; 0 / 1 verified focus; no accepted signals. |
| 1.6.0 | Global article body helped discovery; exposed timezone and copied-source provenance gaps. 304,906 tokens, no accepted signals. |
| 1.7.0 | Phase-aware global discovery found role changes, but final output concatenated verified excerpts; importer correctly rejected them. 388,366 tokens, one verified focus, no accepted signals. |

No version through 1.7.0 satisfies promotion review. A successful process exit,
valid JSON, many fetched pages or passing deterministic tests do not establish
research usefulness. A partial report is preferable to invented certainty.

Release review requires useful verified evidence in repeated live executions,
manual inspection of claim/source alignment, bounded completion with measured usage,
no operational import from experiments, full contract/adversarial tests, normal
worker wiring, health and rollback verification. The 90% coverage / 80% evidence
and three distinct GWs autonomy gates remain separate and unchanged. Sequential
runs with different manifests/policies are not paired model benchmarks. The existing
comparison command is stricter and reports ineligible whenever its same-input
requirements fail; do not reinterpret that flag as a production promotion.

The first 1.8.0 run completed at 220,874 logical tokens and independently imported
one dated official excerpt supporting two accepted observations: Sangaré benched
and Damsgaard starting in that match. The latter was outside the original focus.
The text explicitly withheld any prediction of permanent role or October fitness.

A same-manifest 1.8.0/1.9.0 pair then completed at 309,904 / 334,202 tokens:
three / four verified focus subjects and zero / one accepted signal respectively.
The comparator correctly remains ineligible: one additional focus subject is below
its pre-existing two-subject material-gain threshold. These runs demonstrate useful
partial research and conservative rejection, not sufficient operational coverage.
The pair uses the same source-fetch implementation, schema and quality policy.

The 1.10.0 candidate expands only broad/forced discovery to 16 queries/documents;
refresh/final retain their smaller delta budgets. It corrects two tested lexical
false negatives (`line up`, `PK duties`) under a new quality policy, without changing
freshness, identity, corroboration or multi-GW gates. Comparing it with earlier
policies does not constitute a paired quality benchmark.

A separate integration regression excludes experimental enqueued/completed audit
records from normal cadence queries. Otherwise a completed experiment could block
a future operational slot indefinitely. Failed/queued experiments cannot consume
an operational research slot; their own physical attempts remain host-authorized.
All consumption and unsuccessful attempts remain visible and auditable.

First 1.10.0 live result (`research_70f8d29afd068cd0e824f346fcbe8fce`):
12/25 verified focus subjects, six independently fetched and dated documents,
four accepted signals including one outside focus, one unresolved conflict,
621,969 logical tokens (614,111 input, 545,920 cached input, 7,858 output),
343,205 ms. No overrun against the sealed 1M job allocation. All six final excerpts
survived independent import. Manual inspection checked the role/bench/ball-taking
claims against the literal excerpts and their qualifications. This is 48% current
coverage, not 90/80 compliance, predictive accuracy or evidence from three GWs.

The researcher explicitly retained the unresolved Haaland availability question;
a recent starting XI does not resolve future fitness. Sangaré's bench observation
does not establish a permanent loss of role. Dewsbury-Hall's added set-piece duties
do not establish penalties or exclusive responsibility. These distinctions are
part of release review, not just the accepted-signal counter. Exact-version repeat
and normal-runtime smoke remain required before calling the component promoted.

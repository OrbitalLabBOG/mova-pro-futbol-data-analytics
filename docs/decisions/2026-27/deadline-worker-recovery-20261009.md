---
type: incident-review
name: GW6 deadline worker recovery
created: 2026-10-09
status: recovered
updated: 2026-10-09
tags: [mova, fpl, harness, incident]
---

# GW6 deadline worker recovery

User requested a live health and deadline audit, then explicitly approved deploying
and recovering the harness while preserving A0/shadow and existing budgets.

## Initial observation

At 2026-10-10 01:28 UTC (9 October 20:28 Colombia), production checkout and engine
image matched `acd84a9`. The official FPL API and runtime agreed on GW6 deadline
2026-10-10 10:00 UTC (05:00 Colombia).

Doctor: 23 PASS, 1 WARN, 1 FAIL, observability available. The warning was two stale
agent requests; the failure was scheduled-service results (watchdog detecting the
queue problem). Incident `incident_eafd620a977e46ccb5354e55d021e9f1` was open since
2026-10-09 11:23 UTC; the outbox recorded successful delivery, not human receipt.

API, PostgreSQL, browser, public data, private 15-player state, model artifacts,
analytics, resource gates and backup freshness passed. Ten timers were active.
Runtime remained shadow/A0, kill switch on, browser writes off, compliance pending.
Readiness was 19 pass, 5 pending, 3 blocked. Research coverage and evidence ratios
were both 0.12; four measured gameweeks had zero passing gameweeks. One unresolved
research conflict blocked the current decision. These are distinct from the worker bug.

Two deliberation requests were queued for more than fourteen hours:

- `deliberation_b9ceec3ebf66303e31ea836ef2a2275c`
- `deliberation_9b298d8b069e5be4529971de04459f9c`

The host repeatedly authorized the first request, but Node dereferenced
`request.manifest.deadline_at` while constructing the unused metered research prompt.
Deliberation has an envelope, not a research manifest. The exception occurred before
its started receipt and before Codex execution; expiring permits did not count as
physical agent attempts.

## Correction and verification

Runtime candidate `dc5a2d82c5595cb1679993503193739db90b6ebd` lazily constructs the
metered prompt only for research. Regression runs the actual worker with a permitted
deliberation lacking a manifest and a fake Codex process, covering success and failure,
request identity, lifecycle receipts and lock cleanup. Both cases reproduced the
original failure before the fix.

- Full local suite: 2027 passed, 1 skipped, 79 deselected (39.65 seconds).
- Worker/deliberation subset: 26 passed.
- Node syntax, compileall, Compose config and diff checks passed.
- GitHub PR #197 CI passed.

No runtime, DB, model, browser or host-wrapper source changed. A full build was
stopped before deployment because it began rebuilding unchanged SQLite dependencies.
The final images are incremental layers over the exact locally verified `acd84a9`
image IDs. Engine/browser change revision metadata only. Research replaces only the
worker, whose source and image SHA-256 both equal
`7c4392799d99dbb9bca975e4bdb3a778724868801a72f83eb08d70748d7d5ae5`.
The incremental Dockerfiles and base image IDs are preserved in the private host
release directory `/opt/orbital/backups/mova-fpl/releases/dc5a2d8/`.

Deployment includes an isolated engine smoke, pre-release SQLite/PostgreSQL backups,
writer locks, preserved capacity override and an error trap restoring prior code/config.
No live database restore, authority promotion, allowance increase or FPL mutation is
part of this recovery. Live recovery evidence follows.


## Live recovery

The release unit completed successfully. Checkout and image both report `dc5a2d8`.
The backup freshness/DR sensor passed all six checks at 01:41:59 UTC. Ten existing
timers were restored with their cadence unchanged. No disruptive restore or reboot
was performed; same-revision drill evidence remains a separate readiness gate.

Both original requests ran once through the host authorizer and normal research
service, without new request identities or increased allowances:

| Request suffix | Finished UTC, 10 October | Exact tokens | Durable outcome |
| --- | --- | ---: | --- |
| b9ceec3ebf66303e31ea836ef2a2275c | 01:44:38 | 92,506 | imported; Critic block |
| 9b298d8b069e5be4529971de04459f9c | 01:50:09 | 93,088 | imported; Critic block |

A manual invocation between these runs returned the supported capacity-busy skip
(75), then succeeded when the shared lock became available. No locks were bypassed.
Queue afterwards: zero requests, zero anomalies, healthy. The watchdog reevaluated
the condition and the runtime subsequently reported no open P0/P1 incidents.
The Critic blocks are valid decision outcomes: unresolved research conflict and no
validated chip case. They are not worker failures or permission to change the team.

Authenticated read-only capture at 01:51:23 UTC succeeded with 15 players, one free
transfer and 0.5 million bank. Its fingerprint exactly matches the pre-release
snapshot, confirming no lineup mutation. No private roster is retained in this note.

Recovery consumed 185,594 tokens total; both original reservations settled exactly.
GW budget remains 8,000,000 tokens, 6,446,666 committed, 1,553,334 remaining,
zero reserved tokens. Existing historical reviewed overruns were not erased.
Runtime controls remain shadow/A0, kill switch on, browser writes off and compliance
pending. Research quality, calibration, driver rehearsals and explicit promotion
remain independent requirements; successful recovery does not establish autonomy.


Readiness after recovery: 20 pass, 1 blocked, 6 pending. The blocked gate is
research evidence calibration. Pending gates cover current-revision recovery/
external restore evidence, captaincy/lineup/R3 drivers, and autonomous closeout.
The live research timer uses the existing capacity override (minutes 07 and 37;
non-persistent), not the source timer's 15-minute default. It evaluates eligibility
without rerunning an already attempted slot. Refresh becomes eligible at 04:00 UTC
(23:00 Colombia), final at 08:00 UTC (03:00 Colombia), with the 70-minute cutoff
preserved. This schedule is enabled, not a guarantee of a future result or budget
sufficiency for every possible retry.

Doctor at 01:52:37 UTC: **25 PASS, 0 WARN, 0 FAIL**, observability available,
exit 0. Runtime status healthy, zero open incidents and zero pending outbox items.

The next scheduled tick ran without manual invocation from 01:55:19 to 01:57:51 UTC
(job `job_69cfc15a170b45609f08f8c67ec6b9f5`), completed with no error and output
SHA-256 `ef3e172b958195d9a0cba9d7ee862ca4e8a0563ed544c8869733a3b5b4c4cc69`.
It refreshed official public inputs. A status read at its start briefly observed
source freshness degradation; after capture and at completion status was healthy.
Final read at 01:58:14 UTC: healthy, no incidents, queue empty/no anomalies and
unchanged A0 controls. Deployment is the runtime commit above; the subsequent
documentation commit does not represent another image release.

## Follow-up: transfer probe validation

At the owner's request to complete execution validation, a live read-only R3
probe timed out while loading Transfers. The host wrapper granted temporary
CPU borrowing to `collect` and pick-team `probe`, but omitted `probe-transfers`.
The omitted case now uses the same two owned resource locks, maximum 0.50 CPU,
and exact restoration trap. Direct sessions without both locks retain their
provisioned limit. This does not enable Save, transfers, chips or autonomy.

The regression reproduced the missing borrowing before correction. Full suite:
2028 passed, 1 skipped, 79 deselected. Shell syntax and diff checks passed.
Runtime `7db00f6` was deployed with a verified PostgreSQL backup, preserved
rollback configuration and unchanged capacity override. Images are metadata-only
layers over the preceding deployed images; the implementation change is in the
host wrapper. Private release artifacts are retained under
`/opt/orbital/backups/mova-fpl/releases/7db00f6/`.

The corrected live R3 probe passed and was imported as
`rehearsal_9d62051bcc65b3742a08a986` for `2026-27-gw06`, contract
`fpl-r3-host-driver-2026.08.1`, with no attempted writes. Its protected source is
`/var/lib/mova-fpl/artifacts/browser-probes/gw06-r3-20261010-cpu-7db00f6.json`.
R3 now has two distinct observed cycles; captaincy and lineup each retain one
under their current contract. The earlier timeout was not counted as passing.
The browser was stopped and its original 0.25 CPU limit restored after the probe.

Post-deployment doctor: 25 PASS, 0 WARN, 0 FAIL. The incident caused by the
temporary private-collector timer pause was resolved through the normal watchdog
after timer restoration and a fresh passing DR observation. No incident was
manually marked resolved. A separate private-state refresh handles the snapshot
aging beyond its one-hour TTL during deployment and validation.

Readiness remains insufficient for writes. Repeating the same cycle cannot
satisfy the distinct-GW rehearsal policy. Research still has four measured cycles
and zero passing; the implemented gate requires every historical measured cycle
to pass. [ADR-011](../../specs/fpl-autonomous-operator/decisions/ADR-011-prospective-research-acceptance.md)
is proposed, awaiting the owner's explicit decision, and is not implemented or
approved by this release. Same-revision recovery proofs, compliance, capability
promotion and execution authority remain separate requirements. No team changes
were saved in this follow-up.

### Same-revision recovery evidence

The supported host drills subsequently completed on runtime `7db00f6`:

| Scenario | Checks passed | Service downtime | Durable job |
| --- | --- | --- | --- |
| API recovery | 5/5 | 23 s | `job_a0c962dc6c5845b883d881d34637c2c2` |
| PostgreSQL recovery | 8/8 | 16 s | `job_f878547edc5347159f051dcfcc32aa18` |
| Browser recovery | 9/9 | 27 s | `job_9ac7660f7fb84ef0993b7baa8169ae9a` |
| Combined recovery | 13/13 | 50 s | `job_c8904d45675b4e44a4e1228c6adcaffe` |
| Isolated offsite restore | 8/8 | 0 s | `job_6a58cee3294246a585755ebfba87995b` |

All declare `fpl_state_mutated=false`. Combined recovery preserves the original
private fingerprint. Offsite restore completed at 2026-10-10 04:07:08 UTC in
345 seconds, verified SQLite and PostgreSQL content, and removed its disposable
environment. Its artifact SHA-256 is
`f979f664bac5864cf508c0918afac9966d124256b5ca7ee8ac1cae5b768ee43f`.

The fresh private capture is `teamstate_d19e4f66197e40f19f30df63f14fff5d`,
observed at 03:50:23 UTC. Its fingerprint still equals the pre-release state;
there are no saved transfers or lineup changes. No full roster is included here.

The reboot scenario was not run or prepared. The runbook requires separate
explicit authorization for a real VPS reboot; it affects other hosted services
and is not implied by these service-scoped drills. Thus the five-scenario host
recovery gate still has one unproven scenario. This record neither upgrades the
old reboot proof nor changes research acceptance, browser rehearsal counts,
compliance or execution authority.

### ADR-011 owner approval and prospective implementation

Julián explicitly approved ADR-011 in this thread on 9 October 2026 (Colombia).
The decision was recorded at `2026-10-10T04:30:32Z`; it does not authorize a host
reboot or change FPL write controls. The earlier `7db00f6` observations above
remain historical facts, not acceptance evidence for the new release.

The implementation separates the unchanged historical coverage report from
immutable future cohorts. SQLite migration 022 records owner/reason/approval
reference/manifest hash and fixes the first operational run per GW in the queue
transaction, before inference authorization. PostgreSQL migration 025 mirrors
those records. Experiments do not bind slots; later successful imports cannot
replace an earlier rejected or failed run. Missing results, material contract
drift, failed attempts, uncertain usage, exceeded budgets and incomplete evidence
fail closed. All preregistered GWs must pass 90%/80%/zero applicable conflicts.
Readiness uses the prospective report and leaves historical failures visible.

Validation before deployment: `pytest -q` — **2054 passed, 1 skipped,
79 deselected**. Compilation, JavaScript syntax and diff whitespace checks pass.
The 19 new acceptance regressions cover registration/idempotency/immutability,
causality, deterministic selection, experiments, individual quality thresholds,
failed attempts, unknown usage, material drift, expiry, late imports and worker asset hashes.

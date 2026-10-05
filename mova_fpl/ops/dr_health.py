"""Assess the sanitized host DR observation without restoring or granting authority."""
from datetime import datetime, timezone
import re

REPORT_MAX_AGE_SECONDS = 90 * 60
RPO_SECONDS = 7 * 3600
REQUIRED_CHECKS = frozenset({
    "local_v2_within_rpo", "external_snapshot_within_rpo", "checkout_images_match",
    "timers", "restore_resources", "api_ready",
})


def assess_backup_freshness(host: dict, *, revision: str, now: datetime) -> dict:
    report = host.get("dr_observation") or {}
    if not isinstance(report, dict):
        report = {}
    reasons = []
    age = None
    try:
        observed = datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("timezone required")
        elapsed = (now.astimezone(timezone.utc) - observed).total_seconds()
        age = int(elapsed)
        if elapsed < 0:
            reasons.append("dr_observation_stale_or_future")
    except (KeyError, TypeError, AttributeError, ValueError):
        reasons.append("dr_observation_missing_or_invalid")
    if age is not None and not 0 <= age <= REPORT_MAX_AGE_SECONDS:
        reasons.append("dr_observation_stale_or_future")
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != REQUIRED_CHECKS:
        reasons.append("dr_checks_incomplete")
    elif any(value != "pass" for value in checks.values()):
        reasons.append("dr_preflight_blocked")
    sha = report.get("revision")
    if (not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or not isinstance(revision, str)
            or not re.fullmatch(r"[0-9a-f]{7,40}", revision)
            or not sha.startswith(revision)):
        reasons.append("dr_revision_mismatch")
    data_ages = {}
    for name in ("local_backup", "remote_backup"):
        fact = report.get(name)
        measured = fact.get("data_age_seconds") if isinstance(fact, dict) else None
        if type(measured) is not int or measured < 0 or age is None or age < 0:
            reasons.append(f"{name}_age_unknown")
            data_ages[name] = None
        else:
            # Backup age continues increasing between hourly preflight runs.
            data_ages[name] = measured + age
            if data_ages[name] > RPO_SECONDS:
                reasons.append(f"{name}_outside_rpo")
    return {
        "schema": "mova-backup-freshness-v1", "healthy": not reasons,
        "status": "pass" if not reasons else "blocked", "reasons": reasons,
        "generated_at": report.get("generated_at"), "report_age_seconds": age,
        "report_max_age_seconds": REPORT_MAX_AGE_SECONDS, "rpo_seconds": RPO_SECONDS,
        "data_age_seconds": data_ages, "revision": sha,
        "checks": checks if isinstance(checks, dict) else {},
        "host_reconstruction_proven": False, "runtime_mutated": False,
    }

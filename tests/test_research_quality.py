from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mova_fpl.ops.research_quality import claim_supported, subject_in_excerpt
from mova_fpl.ops.strategy import StrategicContextService
from test_strategic_context import _plan, _runtime


URL = "https://example.com/team-news"


def _source(excerpt: str, published: str | None) -> dict:
    return {URL: {"fetch_status": "verified", "source_tier": "official",
                  "excerpt": excerpt, "published_at": published,
                  "publication_date_verified": bool(published)}}


def _signal(*, name: str = "Erling Haaland", element: int = 411,
            claim_type: str = "injury") -> dict:
    return {"subject_name": name, "player_element": element,
            "claim_type": claim_type, "claim_text": "Problema físico reciente.",
            "direction": "negative", "confidence": 0.8,
            "source_urls": [URL],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}


def test_identity_and_topic_must_both_be_present():
    assert claim_supported(name="Haaland", claim_type="injury",
                           excerpt="Haaland has a hamstring injury.")
    assert not claim_supported(name="Haaland", claim_type="injury",
                               excerpt="Haaland scored twice last Sunday.")
    assert not claim_supported(name="Haaland", claim_type="injury",
                               excerpt="Foden has a hamstring injury.")
    assert not subject_in_excerpt("Player One", "Player Two is available.")


def test_import_gate_downgrades_wrong_topic_identity_and_undated_source():
    observed = datetime.now(timezone.utc)
    catalog = {411: "Haaland"}
    good = StrategicContextService._validate_signals(
        [_signal()], _source("Haaland has a hamstring injury.", observed.isoformat()),
        set(), observed, require_verified=True, catalog=catalog,
        cutoff=observed + timedelta(hours=1),
    )[0]
    assert good["validation_status"] == "accepted"
    for excerpt, published, name, reason in (
        ("Haaland scored twice.", observed.isoformat(), "Erling Haaland",
         "identity_or_claim_unsupported"),
        ("Foden has a hamstring injury.", observed.isoformat(), "Erling Haaland",
         "identity_or_claim_unsupported"),
        ("Haaland has a hamstring injury.", None, "Erling Haaland",
         "publication_unknown"),
        ("Haaland has a hamstring injury.", observed.isoformat(), "Phil Foden",
         "identity_or_claim_unsupported"),
    ):
        result = StrategicContextService._validate_signals(
            [_signal(name=name)], _source(excerpt, published), set(), observed,
            require_verified=True, catalog=catalog,
            cutoff=observed + timedelta(hours=1),
        )[0]
        assert result["validation_status"] == "candidate"
        assert result["quality"]["reason"] == reason


def test_signal_requires_same_relevant_source_to_be_recent():
    observed = datetime.now(timezone.utc)
    old = (observed - timedelta(days=15)).isoformat()
    signal = _signal(claim_type="starting_role")
    sources = _source("Haaland started in the official XI.", old)
    result = StrategicContextService._validate_signals(
        [signal], sources, set(), observed, require_verified=True,
        catalog={411: "Haaland"}, require_freshness=True,
    )[0]
    assert result["validation_status"] == "candidate"
    assert result["quality"]["reason"] == "stale_for_claim"

    sources["https://example.com/unrelated"] = {
        "fetch_status": "verified", "source_tier": "official",
        "excerpt": "Foden starts today.", "published_at": observed.isoformat(),
        "publication_date_verified": True,
    }
    signal["source_urls"].append("https://example.com/unrelated")
    result = StrategicContextService._validate_signals(
        [signal], sources, set(), observed, require_verified=True,
        catalog={411: "Haaland"}, require_freshness=True,
    )[0]
    assert result["quality"]["reason"] == "stale_for_claim"

    sources[URL]["published_at"] = observed.isoformat()
    sources[URL]["source_tier"] = "tier2"
    result = StrategicContextService._validate_signals(
        [signal], sources, set(), observed, require_verified=True,
        catalog={411: "Haaland"}, require_freshness=True,
    )[0]
    assert result["validation_status"] == "candidate"


def test_stale_document_cannot_count_as_current_coverage():
    observed = datetime.now(timezone.utc)
    rows = StrategicContextService._validate_coverage(
        {"subjects": [{"player_element": 411, "status": "no_material_update",
                       "source_urls": [URL], "note": "Old lineup."}]},
        [{"element": 411, "focus_reason": ["current_squad"], "team": "Man City"}],
        _source("Haaland started in the XI.",
                (observed - timedelta(days=15)).isoformat()), [],
        legacy=False, catalog={411: "Haaland"}, fetched_at=observed,
        require_freshness=True,
    )
    assert rows["checked_subjects"] == 0


def test_coverage_does_not_count_generic_article_as_player_evidence():
    observed = datetime.now(timezone.utc)
    rows = StrategicContextService._validate_coverage(
        {"subjects": [{"player_element": 411, "status": "no_material_update",
                       "source_urls": [URL], "note": "Club news."}]},
        [{"element": 411, "focus_reason": ["current_squad"], "team": "Man City"}],
        _source("City won the match.", observed.isoformat()), [],
        legacy=False, catalog={411: "Haaland"},
    )
    assert rows["checked_subjects"] == 0
    assert rows["evidence_verified_subjects"] == 0
    assert rows["subjects"][0]["status"] == "not_checked"


def test_coverage_does_not_count_fetch_after_deadline():
    observed = datetime.now(timezone.utc)
    rows = StrategicContextService._validate_coverage(
        {"subjects": [{"player_element": 411, "status": "no_material_update",
                       "source_urls": [URL], "note": "Named evidence."}]},
        [{"element": 411, "focus_reason": ["current_squad"], "team": "Man City"}],
        _source("Haaland is available.", observed.isoformat()), [],
        legacy=False, catalog={411: "Haaland"},
        fetched_at=observed, cutoff=observed - timedelta(seconds=1),
    )
    assert rows["coverage_ratio"] == 0


def test_manifest_embeds_active_plan_not_only_revision(tmp_path):
    _config, _db, service, _cycle_id = _runtime(tmp_path)
    service.activate_plan(_plan(), actor="test", reason="context fixture")
    manifest = service.prepare()["manifest"]
    assert manifest["research_summary"]["plan"]["assumptions"] == _plan()["assumptions"]
    assert manifest["research_summary"]["plan"]["guardrails"] == _plan()["guardrails"]
    assert manifest["research_summary"]["world"]["status"] == "missing"


def test_negative_starting_role_is_supported_only_under_new_policy():
    from mova_fpl.ops.research_quality import claim_supported
    kwargs=dict(name="Sangaré",claim_type="starting_role",excerpt="Aaron Hickey and Mamadou Sangare drop to the bench.")
    assert not claim_supported(**kwargs)
    assert claim_supported(**kwargs,allow_bench_role=True)
    assert not claim_supported(**{**kwargs,'claim_type':'injury'},allow_bench_role=True)
    assert not claim_supported(**{**kwargs,'name':'Saka'},allow_bench_role=True)

"""Migraciones SQLite del control plane.

Cada sentencia es independiente para poder aplicar la migración bajo
``BEGIN IMMEDIATE`` sin depender del comportamiento implícito de
``executescript``.
"""

MIGRATION_001 = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        checksum TEXT NOT NULL,
        applied_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_controls (
        control_id INTEGER PRIMARY KEY,
        control_key TEXT NOT NULL,
        value_json TEXT NOT NULL CHECK (json_valid(value_json)),
        effective_at TEXT NOT NULL,
        actor TEXT NOT NULL,
        reason TEXT NOT NULL
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_runtime_controls_latest ON runtime_controls(control_key, effective_at DESC, control_id DESC)",
    """
    CREATE TABLE IF NOT EXISTS seasons (
        season_code TEXT PRIMARY KEY,
        first_gw INTEGER NOT NULL DEFAULT 1 CHECK (first_gw = 1),
        last_gw INTEGER NOT NULL DEFAULT 38 CHECK (last_gw BETWEEN 1 AND 38),
        rules_sha256 TEXT,
        status TEXT NOT NULL CHECK (status IN ('planned','active','complete')),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS gameweek_cycles (
        cycle_id TEXT PRIMARY KEY,
        season TEXT NOT NULL,
        gw INTEGER NOT NULL CHECK (gw BETWEEN 1 AND 38),
        deadline_at TEXT NOT NULL,
        phase TEXT NOT NULL,
        status TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
        first_observed_at TEXT NOT NULL,
        last_observed_at TEXT NOT NULL,
        UNIQUE (season, gw)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS job_runs (
        job_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        correlation_id TEXT NOT NULL,
        cycle_id TEXT REFERENCES gameweek_cycles(cycle_id),
        job_type TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('running','completed','degraded','failed','skipped')),
        attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        input_sha256 TEXT,
        output_sha256 TEXT,
        metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metrics_json)),
        error_code TEXT,
        error_detail TEXT
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_job_runs_type_started ON job_runs(job_type, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_job_runs_cycle ON job_runs(cycle_id, started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS job_steps (
        step_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES job_runs(job_id) ON DELETE CASCADE,
        step_name TEXT NOT NULL,
        attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
        status TEXT NOT NULL CHECK (status IN ('running','completed','degraded','failed','skipped')),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        duration_ms INTEGER,
        output_sha256 TEXT,
        detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json)),
        error_code TEXT,
        error_detail TEXT,
        UNIQUE (job_id, step_name, attempt)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS source_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        source_name TEXT NOT NULL,
        captured_at TEXT NOT NULL,
        artifact_path TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        freshness_seconds INTEGER NOT NULL CHECK (freshness_seconds >= 0),
        quality_status TEXT NOT NULL CHECK (quality_status IN ('valid','degraded','quarantined')),
        quality_json TEXT NOT NULL CHECK (json_valid(quality_json)),
        UNIQUE (source_name, payload_sha256)
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_source_snapshots_cycle ON source_snapshots(cycle_id, captured_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS research_signals (
        signal_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        player_element INTEGER,
        claim_type TEXT NOT NULL,
        claim_text TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_tier TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        published_at TEXT,
        expires_at TEXT NOT NULL,
        confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
        conflict_status TEXT NOT NULL CHECK (conflict_status IN ('none','unresolved','resolved')),
        content_sha256 TEXT NOT NULL,
        UNIQUE (cycle_id, player_element, claim_type, source_url, content_sha256)
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_research_signals_cycle ON research_signals(cycle_id, observed_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS team_state_snapshots (
        team_state_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        observed_at TEXT NOT NULL,
        source_name TEXT NOT NULL,
        squad_json TEXT NOT NULL CHECK (json_valid(squad_json)),
        free_transfers INTEGER NOT NULL CHECK (free_transfers BETWEEN 0 AND 5),
        bank_tenths INTEGER NOT NULL,
        chips_json TEXT NOT NULL CHECK (json_valid(chips_json)),
        fingerprint TEXT NOT NULL,
        UNIQUE (cycle_id, source_name, fingerprint)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS dataset_releases (
        dataset_id TEXT PRIMARY KEY,
        dataset_name TEXT NOT NULL,
        version TEXT NOT NULL,
        as_of_at TEXT NOT NULL,
        row_count INTEGER NOT NULL CHECK (row_count >= 0),
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        leakage_audit_json TEXT NOT NULL CHECK (json_valid(leakage_audit_json)),
        created_at TEXT NOT NULL,
        UNIQUE (dataset_name, version)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS model_releases (
        model_release_id TEXT PRIMARY KEY,
        model_name TEXT NOT NULL,
        version TEXT NOT NULL,
        dataset_id TEXT REFERENCES dataset_releases(dataset_id),
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        metrics_json TEXT NOT NULL CHECK (json_valid(metrics_json)),
        status TEXT NOT NULL CHECK (status IN ('candidate','shadow','approved','retired')),
        created_at TEXT NOT NULL,
        UNIQUE (model_name, version)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS projection_runs (
        projection_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        model_manifest_json TEXT NOT NULL CHECK (json_valid(model_manifest_json)),
        input_manifest_sha256 TEXT NOT NULL,
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        player_count INTEGER NOT NULL CHECK (player_count > 0),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS intervention_runs (
        intervention_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        policy_version TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        payload_sha256 TEXT NOT NULL,
        rationale TEXT NOT NULL,
        rationale_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_runs (
        decision_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        revision INTEGER NOT NULL CHECK (revision >= 1),
        mode TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        status TEXT NOT NULL,
        expected_points REAL,
        chip TEXT,
        fingerprint TEXT,
        manifest_sha256 TEXT,
        artifact_path TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (cycle_id, revision)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_players (
        decision_id TEXT NOT NULL REFERENCES decision_runs(decision_id) ON DELETE CASCADE,
        element INTEGER NOT NULL,
        squad_position INTEGER NOT NULL CHECK (squad_position BETWEEN 1 AND 15),
        role TEXT NOT NULL CHECK (role IN ('starter','bench')),
        is_captain INTEGER NOT NULL DEFAULT 0 CHECK (is_captain IN (0,1)),
        is_vice_captain INTEGER NOT NULL DEFAULT 0 CHECK (is_vice_captain IN (0,1)),
        transfer_direction TEXT CHECK (transfer_direction IN ('in','out')),
        expected_points REAL,
        PRIMARY KEY (decision_id, element),
        UNIQUE (decision_id, squad_position)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS chip_strategy_runs (
        strategy_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        window_name TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        inventory_json TEXT NOT NULL CHECK (json_valid(inventory_json)),
        recommended_chip TEXT,
        status TEXT NOT NULL,
        manifest_sha256 TEXT,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS chip_candidates (
        candidate_id TEXT PRIMARY KEY,
        strategy_id TEXT NOT NULL REFERENCES chip_strategy_runs(strategy_id) ON DELETE CASCADE,
        chip TEXT NOT NULL,
        gw INTEGER NOT NULL CHECK (gw BETWEEN 1 AND 38),
        expected_value REAL NOT NULL,
        p10 REAL,
        p50 REAL,
        p90 REAL,
        threshold REAL,
        schedule_confidence REAL CHECK (schedule_confidence IS NULL OR schedule_confidence BETWEEN 0 AND 1),
        action TEXT NOT NULL CHECK (action IN ('play','hold','blocked','unavailable')),
        reason TEXT NOT NULL,
        UNIQUE (strategy_id, chip, gw)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS web_executions (
        execution_id TEXT PRIMARY KEY,
        decision_id TEXT NOT NULL REFERENCES decision_runs(decision_id),
        action_level TEXT NOT NULL,
        envelope_sha256 TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        evidence_path TEXT,
        evidence_sha256 TEXT,
        error_code TEXT,
        error_detail TEXT,
        UNIQUE (decision_id, action_level)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS verification_checks (
        check_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES web_executions(execution_id) ON DELETE CASCADE,
        check_name TEXT NOT NULL,
        expected_json TEXT NOT NULL CHECK (json_valid(expected_json)),
        observed_json TEXT NOT NULL CHECK (json_valid(observed_json)),
        passed INTEGER NOT NULL CHECK (passed IN (0,1)),
        checked_at TEXT NOT NULL,
        UNIQUE (execution_id, check_name)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS health_samples (
        sample_id TEXT PRIMARY KEY,
        observed_at TEXT NOT NULL,
        service TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('ok','degraded','down')),
        memory_available_bytes INTEGER,
        disk_free_bytes INTEGER,
        load_1m REAL,
        sqlite_version TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json))
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_health_samples_observed ON health_samples(observed_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        event_id TEXT PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('debug','info','warning','error','critical')),
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL,
        correlation_id TEXT,
        cycle_id TEXT REFERENCES gameweek_cycles(cycle_id),
        job_id TEXT REFERENCES job_runs(job_id),
        subject_type TEXT,
        subject_id TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
        payload_sha256 TEXT NOT NULL
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_events_time ON audit_events(occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_correlation ON audit_events(correlation_id, occurred_at)",
    """
    CREATE TABLE IF NOT EXISTS incidents (
        incident_id TEXT PRIMARY KEY,
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        severity TEXT NOT NULL CHECK (severity IN ('P0','P1','P2','P3')),
        status TEXT NOT NULL CHECK (status IN ('open','acknowledged','resolved')),
        title TEXT NOT NULL,
        owner TEXT,
        correlation_id TEXT,
        cycle_id TEXT REFERENCES gameweek_cycles(cycle_id),
        job_id TEXT REFERENCES job_runs(job_id),
        detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json)),
        resolution TEXT
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_incidents_open ON incidents(status, severity, opened_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS outbox_events (
        outbox_id TEXT PRIMARY KEY,
        event_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        available_at TEXT NOT NULL,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending','sending','sent','acknowledged','dead')),
        attempts INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        sent_at TEXT,
        acknowledged_at TEXT,
        last_error TEXT
    ) STRICT
    """,
)

MIGRATION_002 = (
    "ALTER TABLE team_state_snapshots ADD COLUMN artifact_path TEXT",
    "ALTER TABLE team_state_snapshots ADD COLUMN manifest_sha256 TEXT",
    "ALTER TABLE team_state_snapshots ADD COLUMN quality_status TEXT "
    "CHECK (quality_status IN ('valid','degraded','quarantined'))",
)

MIGRATION_003 = (
    "ALTER TABLE team_state_snapshots RENAME TO team_state_snapshots_v1",
    """
    CREATE TABLE team_state_snapshots (
        team_state_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        observed_at TEXT NOT NULL,
        source_name TEXT NOT NULL,
        squad_json TEXT NOT NULL CHECK (json_valid(squad_json)),
        free_transfers INTEGER NOT NULL CHECK (free_transfers BETWEEN 0 AND 5),
        bank_tenths INTEGER NOT NULL,
        chips_json TEXT NOT NULL CHECK (json_valid(chips_json)),
        fingerprint TEXT NOT NULL,
        artifact_path TEXT,
        manifest_sha256 TEXT,
        quality_status TEXT CHECK (quality_status IN ('valid','degraded','quarantined')),
        UNIQUE (cycle_id, source_name, observed_at)
    ) STRICT
    """,
    """
    INSERT INTO team_state_snapshots(team_state_id,job_id,cycle_id,observed_at,source_name,
      squad_json,free_transfers,bank_tenths,chips_json,fingerprint,artifact_path,
      manifest_sha256,quality_status)
    SELECT team_state_id,job_id,cycle_id,observed_at,source_name,squad_json,free_transfers,
      bank_tenths,chips_json,fingerprint,artifact_path,manifest_sha256,quality_status
    FROM team_state_snapshots_v1
    """,
    "DROP TABLE team_state_snapshots_v1",
    "CREATE INDEX idx_team_state_cycle_observed "
    "ON team_state_snapshots(cycle_id, observed_at DESC)",
    "CREATE INDEX idx_team_state_fingerprint "
    "ON team_state_snapshots(cycle_id, fingerprint, observed_at DESC)",
)

MIGRATION_004 = (
    """
    CREATE TABLE IF NOT EXISTS gameweek_settlements (
        settlement_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        job_id TEXT NOT NULL REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        source_artifact_id TEXT NOT NULL,
        settled_at TEXT NOT NULL,
        entry_points INTEGER NOT NULL,
        entry_rank INTEGER,
        average_points INTEGER,
        bench_points INTEGER NOT NULL CHECK (bench_points >= 0),
        hit_cost INTEGER NOT NULL DEFAULT 0 CHECK (hit_cost >= 0),
        captain_points INTEGER NOT NULL,
        auto_subs_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(auto_subs_json)),
        official_json TEXT NOT NULL CHECK (json_valid(official_json)),
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        UNIQUE (cycle_id, source_artifact_id)
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_gameweek_settlements_cycle "
    "ON gameweek_settlements(cycle_id, settled_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS gameweek_reviews (
        review_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES job_runs(job_id),
        settlement_id TEXT NOT NULL REFERENCES gameweek_settlements(settlement_id),
        decision_id TEXT NOT NULL REFERENCES decision_runs(decision_id),
        review_type TEXT NOT NULL CHECK (review_type IN ('causal','retrospective')),
        causality_status TEXT NOT NULL CHECK (causality_status IN (
          'eligible','not_eligible_no_predeadline_batch','paired_intervention')),
        expected_points REAL NOT NULL,
        actual_points INTEGER NOT NULL,
        comparator_label TEXT,
        comparator_expected_points REAL,
        comparator_actual_points INTEGER,
        realized_delta INTEGER,
        metrics_json TEXT NOT NULL CHECK (json_valid(metrics_json)),
        findings_json TEXT NOT NULL CHECK (json_valid(findings_json)),
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (settlement_id, review_type)
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_gameweek_reviews_settlement "
    "ON gameweek_reviews(settlement_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS review_player_outcomes (
        review_id TEXT NOT NULL REFERENCES gameweek_reviews(review_id) ON DELETE CASCADE,
        scenario TEXT NOT NULL CHECK (scenario IN ('selected','comparator')),
        element INTEGER NOT NULL,
        player_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('starter','bench')),
        is_captain INTEGER NOT NULL DEFAULT 0 CHECK (is_captain IN (0,1)),
        expected_points REAL NOT NULL,
        p60 REAL CHECK (p60 IS NULL OR p60 BETWEEN 0 AND 1),
        actual_points INTEGER NOT NULL,
        minutes INTEGER NOT NULL CHECK (minutes >= 0),
        effective_points INTEGER NOT NULL,
        PRIMARY KEY (review_id, scenario, element)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS change_proposals (
        proposal_id TEXT PRIMARY KEY,
        review_id TEXT NOT NULL REFERENCES gameweek_reviews(review_id) ON DELETE CASCADE,
        category TEXT NOT NULL CHECK (category IN (
          'data','model','optimizer','research','strategy','execution','variance')),
        change_level TEXT NOT NULL CHECK (change_level IN ('C0','C1','C2','C3')),
        priority TEXT NOT NULL CHECK (priority IN ('P0','P1','P2','P3')),
        title TEXT NOT NULL,
        hypothesis TEXT NOT NULL,
        evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
        acceptance_json TEXT NOT NULL CHECK (json_valid(acceptance_json)),
        status TEXT NOT NULL CHECK (status IN ('proposed','testing','accepted','rejected')),
        created_at TEXT NOT NULL,
        UNIQUE (review_id, title)
    ) STRICT
    """,
)

MIGRATION_005 = (
    """
    CREATE TABLE IF NOT EXISTS season_plans (
        plan_id TEXT PRIMARY KEY,
        season TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        status TEXT NOT NULL CHECK (status IN ('draft','active','superseded')),
        horizon_start_gw INTEGER NOT NULL CHECK (horizon_start_gw BETWEEN 1 AND 38),
        horizon_end_gw INTEGER NOT NULL CHECK (
          horizon_end_gw BETWEEN horizon_start_gw AND 38),
        assumptions_json TEXT NOT NULL CHECK (json_valid(assumptions_json)),
        chip_windows_json TEXT NOT NULL CHECK (json_valid(chip_windows_json)),
        guardrails_json TEXT NOT NULL CHECK (json_valid(guardrails_json)),
        rationale TEXT NOT NULL,
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (season, revision)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_season_plans_active "
    "ON season_plans(season) WHERE status='active'",
    """
    CREATE TABLE IF NOT EXISTS cycle_manifests (
        manifest_id TEXT PRIMARY KEY,
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        revision INTEGER NOT NULL CHECK (revision >= 1),
        as_of_at TEXT NOT NULL,
        deadline_at TEXT NOT NULL,
        phase TEXT NOT NULL,
        team_state_id TEXT REFERENCES team_state_snapshots(team_state_id),
        plan_id TEXT REFERENCES season_plans(plan_id),
        source_manifest_json TEXT NOT NULL CHECK (json_valid(source_manifest_json)),
        analytics_manifest_json TEXT NOT NULL CHECK (json_valid(analytics_manifest_json)),
        research_summary_json TEXT NOT NULL CHECK (json_valid(research_summary_json)),
        artifact_path TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (cycle_id, revision),
        UNIQUE (cycle_id, content_sha256)
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_cycle_manifests_latest "
    "ON cycle_manifests(cycle_id, revision DESC)",
    """
    CREATE TABLE IF NOT EXISTS research_runs (
        research_run_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        manifest_id TEXT NOT NULL REFERENCES cycle_manifests(manifest_id),
        provider TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN (
          'queued','running','completed','imported','rejected','failed')),
        request_path TEXT NOT NULL,
        request_sha256 TEXT NOT NULL,
        result_path TEXT,
        result_sha256 TEXT,
        usage_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(usage_json)),
        error_code TEXT,
        error_detail TEXT,
        queued_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        imported_at TEXT,
        UNIQUE (cycle_id, manifest_id, provider, request_sha256)
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_research_runs_status "
    "ON research_runs(status, queued_at)",
    """
    CREATE TABLE IF NOT EXISTS research_documents (
        document_id TEXT PRIMARY KEY,
        research_run_id TEXT NOT NULL REFERENCES research_runs(research_run_id) ON DELETE CASCADE,
        source_url TEXT NOT NULL,
        title TEXT NOT NULL,
        publisher TEXT NOT NULL,
        published_at TEXT,
        observed_at TEXT NOT NULL,
        source_tier TEXT NOT NULL CHECK (source_tier IN ('official','tier1','tier2','other')),
        content_sha256 TEXT NOT NULL,
        UNIQUE (research_run_id, source_url)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS research_conflicts (
        conflict_id TEXT PRIMARY KEY,
        research_run_id TEXT NOT NULL REFERENCES research_runs(research_run_id) ON DELETE CASCADE,
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        subject TEXT NOT NULL,
        claim_type TEXT NOT NULL,
        description TEXT NOT NULL,
        source_urls_json TEXT NOT NULL CHECK (json_valid(source_urls_json)),
        status TEXT NOT NULL CHECK (status IN ('unresolved','resolved')),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    "ALTER TABLE research_signals ADD COLUMN research_run_id TEXT "
    "REFERENCES research_runs(research_run_id)",
    "ALTER TABLE research_signals ADD COLUMN subject_name TEXT",
    "ALTER TABLE research_signals ADD COLUMN direction TEXT "
    "CHECK (direction IS NULL OR direction IN ('positive','negative','neutral','uncertain'))",
    "ALTER TABLE research_signals ADD COLUMN validation_status TEXT "
    "CHECK (validation_status IS NULL OR validation_status IN ('accepted','candidate','rejected'))",
    "ALTER TABLE research_signals ADD COLUMN evidence_json TEXT CHECK "
    "(evidence_json IS NULL OR json_valid(evidence_json))",
    """
    CREATE TABLE IF NOT EXISTS cost_ledger (
        cost_id TEXT PRIMARY KEY,
        research_run_id TEXT REFERENCES research_runs(research_run_id),
        provider TEXT NOT NULL,
        model TEXT,
        input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
        output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
        estimated_cost_usd REAL CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
        subscription_usage INTEGER NOT NULL DEFAULT 0 CHECK (subscription_usage IN (0,1)),
        detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json)),
        occurred_at TEXT NOT NULL
    ) STRICT
    """,
)

MIGRATION_006 = (
    """
    UPDATE research_runs
    SET finished_at=COALESCE(imported_at, finished_at),
        error_code=NULL,
        error_detail=NULL
    WHERE status='imported'
      AND (error_code IS NOT NULL OR error_detail IS NOT NULL)
    """,
)

MIGRATION_007 = (
    """
    CREATE TABLE IF NOT EXISTS decision_envelopes (
        envelope_id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        decision_id TEXT NOT NULL UNIQUE REFERENCES decision_runs(decision_id) ON DELETE CASCADE,
        manifest_id TEXT NOT NULL REFERENCES cycle_manifests(manifest_id),
        schema_version TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('blocked','staged','superseded')),
        selected_candidate_key TEXT NOT NULL,
        content_sha256 TEXT NOT NULL UNIQUE,
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_decision_envelopes_cycle_created "
    "ON decision_envelopes(cycle_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS decision_candidates (
        envelope_id TEXT NOT NULL REFERENCES decision_envelopes(envelope_id) ON DELETE CASCADE,
        candidate_key TEXT NOT NULL,
        label TEXT NOT NULL,
        selected INTEGER NOT NULL CHECK (selected IN (0,1)),
        decision_json TEXT NOT NULL CHECK (json_valid(decision_json)),
        fingerprint TEXT NOT NULL,
        expected_points REAL NOT NULL,
        PRIMARY KEY (envelope_id, candidate_key)
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_validation_checks (
        check_id TEXT PRIMARY KEY,
        envelope_id TEXT NOT NULL REFERENCES decision_envelopes(envelope_id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('info','warning','block')),
        passed INTEGER NOT NULL CHECK (passed IN (0,1)),
        summary TEXT NOT NULL,
        detail_json TEXT NOT NULL CHECK (json_valid(detail_json)),
        created_at TEXT NOT NULL,
        UNIQUE (envelope_id, code)
    ) STRICT
    """,
)

MIGRATION_008 = (
    """
    CREATE TABLE IF NOT EXISTS decision_deliberations (
        deliberation_id TEXT PRIMARY KEY,
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        envelope_id TEXT NOT NULL UNIQUE REFERENCES decision_envelopes(envelope_id) ON DELETE CASCADE,
        manifest_id TEXT NOT NULL REFERENCES cycle_manifests(manifest_id),
        provider TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN (
          'queued','running','completed','accepted','review_required','blocked','rejected','failed')),
        request_path TEXT NOT NULL,
        request_sha256 TEXT NOT NULL UNIQUE,
        result_path TEXT,
        result_sha256 TEXT,
        preferred_candidate_key TEXT,
        critic_verdict TEXT CHECK (critic_verdict IS NULL OR critic_verdict IN (
          'accept','revise','block')),
        strategist_json TEXT CHECK (strategist_json IS NULL OR json_valid(strategist_json)),
        critic_json TEXT CHECK (critic_json IS NULL OR json_valid(critic_json)),
        intervention_json TEXT CHECK (intervention_json IS NULL OR json_valid(intervention_json)),
        intervention_sha256 TEXT,
        usage_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(usage_json)),
        error_code TEXT,
        error_detail TEXT,
        queued_at TEXT NOT NULL,
        finished_at TEXT,
        imported_at TEXT
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_decision_deliberations_cycle_queued "
    "ON decision_deliberations(cycle_id, queued_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS decision_deliberation_risks (
        risk_id TEXT PRIMARY KEY,
        deliberation_id TEXT NOT NULL REFERENCES decision_deliberations(deliberation_id)
          ON DELETE CASCADE,
        code TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('info','warning','block')),
        candidate_key TEXT,
        claim TEXT NOT NULL,
        mitigation TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (deliberation_id, code)
    ) STRICT
    """,
)

MIGRATION_009 = (
    """
    CREATE TABLE IF NOT EXISTS execution_plans (
        plan_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL UNIQUE REFERENCES job_runs(job_id),
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        envelope_id TEXT NOT NULL REFERENCES decision_envelopes(envelope_id),
        decision_id TEXT NOT NULL REFERENCES decision_runs(decision_id),
        policy_version TEXT NOT NULL,
        risk_class TEXT NOT NULL CHECK (risk_class IN ('R0','R2','R3')),
        required_action_level TEXT NOT NULL CHECK (required_action_level IN ('A0','A2','A3')),
        status TEXT NOT NULL CHECK (status IN ('blocked','authorized','noop','superseded')),
        idempotency_key TEXT NOT NULL UNIQUE,
        content_sha256 TEXT NOT NULL UNIQUE,
        artifact_path TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        expected_pre_fingerprint TEXT,
        expected_post_fingerprint TEXT NOT NULL,
        deadline_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_execution_plans_cycle_created "
    "ON execution_plans(cycle_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS execution_preflight_checks (
        check_id TEXT PRIMARY KEY,
        plan_id TEXT NOT NULL REFERENCES execution_plans(plan_id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('block')),
        passed INTEGER NOT NULL CHECK (passed IN (0,1)),
        summary TEXT NOT NULL,
        detail_json TEXT NOT NULL CHECK (json_valid(detail_json)),
        created_at TEXT NOT NULL,
        UNIQUE (plan_id, code)
    ) STRICT
    """,
)

MIGRATION_010 = (
    """
    CREATE TABLE IF NOT EXISTS execution_attempts (
        execution_id TEXT PRIMARY KEY,
        plan_id TEXT NOT NULL UNIQUE REFERENCES execution_plans(plan_id),
        job_id TEXT NOT NULL UNIQUE REFERENCES job_runs(job_id),
        idempotency_key TEXT NOT NULL UNIQUE,
        adapter TEXT NOT NULL CHECK (adapter IN ('disabled','fixture','browser')),
        command_path TEXT NOT NULL,
        command_sha256 TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN (
          'prepared','claimed','applying','ambiguous','verified','failed','blocked','expired'
        )),
        claim_token_sha256 TEXT UNIQUE,
        claimed_by TEXT,
        claimed_at TEXT,
        lease_expires_at TEXT,
        started_at TEXT,
        finished_at TEXT,
        expected_pre_fingerprint TEXT,
        observed_pre_fingerprint TEXT,
        expected_post_fingerprint TEXT NOT NULL,
        observed_post_fingerprint TEXT,
        evidence_path TEXT,
        evidence_sha256 TEXT,
        result_sha256 TEXT,
        error_code TEXT,
        error_detail TEXT,
        created_at TEXT NOT NULL,
        CHECK ((status = 'prepared' AND claim_token_sha256 IS NULL) OR status != 'prepared'),
        CHECK ((status IN ('verified','failed','ambiguous','blocked','expired')
          AND finished_at IS NOT NULL) OR status NOT IN (
          'verified','failed','ambiguous','blocked','expired'
        ))
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_execution_attempts_status_created "
    "ON execution_attempts(status, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS execution_attempt_events (
        attempt_event_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES execution_attempts(execution_id)
          ON DELETE CASCADE,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        from_status TEXT,
        to_status TEXT NOT NULL,
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json)),
        detail_sha256 TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        UNIQUE (execution_id, sequence)
    ) STRICT
    """,
)

MIGRATION_011 = (
    """
    CREATE TABLE IF NOT EXISTS change_proposal_evaluations (
        evaluation_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL REFERENCES change_proposals(proposal_id) ON DELETE CASCADE,
        idempotency_key TEXT NOT NULL UNIQUE,
        from_status TEXT NOT NULL CHECK (from_status IN (
          'proposed','testing','accepted','rejected')),
        to_status TEXT NOT NULL CHECK (to_status IN ('testing','accepted','rejected')),
        evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
        evidence_sha256 TEXT NOT NULL CHECK (length(evidence_sha256) = 64),
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_change_evaluations_proposal_created "
    "ON change_proposal_evaluations(proposal_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS lessons (
        lesson_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL UNIQUE REFERENCES change_proposals(proposal_id),
        review_id TEXT NOT NULL REFERENCES gameweek_reviews(review_id),
        category TEXT NOT NULL,
        statement TEXT NOT NULL,
        evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
        status TEXT NOT NULL CHECK (status IN ('validated','retired')),
        created_at TEXT NOT NULL,
        retired_at TEXT
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_lessons_status_created "
    "ON lessons(status, created_at DESC)",
)

MIGRATION_012 = (
    "ALTER TABLE cost_ledger ADD COLUMN cycle_id TEXT REFERENCES gameweek_cycles(cycle_id)",
    "ALTER TABLE cost_ledger ADD COLUMN subject_type TEXT CHECK "
    "(subject_type IS NULL OR subject_type IN ('research','deliberation'))",
    "ALTER TABLE cost_ledger ADD COLUMN subject_id TEXT",
    "ALTER TABLE cost_ledger ADD COLUMN category TEXT",
    "ALTER TABLE cost_ledger ADD COLUMN duration_ms INTEGER "
    "CHECK (duration_ms IS NULL OR duration_ms >= 0)",
    "ALTER TABLE cost_ledger ADD COLUMN search_requests INTEGER "
    "CHECK (search_requests IS NULL OR search_requests >= 0)",
    """
    UPDATE cost_ledger SET
      cycle_id=(SELECT cycle_id FROM research_runs r
                WHERE r.research_run_id=cost_ledger.research_run_id),
      subject_type='research', subject_id=research_run_id, category='news_research'
    WHERE research_run_id IS NOT NULL
    """,
    """
    UPDATE cost_ledger SET
      subject_type='deliberation',
      subject_id=json_extract(detail_json,'$.deliberation_id'),
      cycle_id=(SELECT cycle_id FROM decision_deliberations d
                WHERE d.deliberation_id=json_extract(cost_ledger.detail_json,
                                                      '$.deliberation_id')),
      category='strategy_critic'
    WHERE research_run_id IS NULL
      AND json_extract(detail_json,'$.deliberation_id') IS NOT NULL
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cost_ledger_subject "
    "ON cost_ledger(subject_type,subject_id) WHERE subject_id IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS agent_budget_reservations (
        reservation_id TEXT PRIMARY KEY,
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        subject_type TEXT NOT NULL CHECK (subject_type IN ('research','deliberation')),
        subject_id TEXT NOT NULL UNIQUE,
        provider TEXT NOT NULL,
        reserved_tokens INTEGER NOT NULL CHECK (reserved_tokens > 0),
        actual_tokens INTEGER CHECK (actual_tokens IS NULL OR actual_tokens >= 0),
        status TEXT NOT NULL CHECK (status IN ('reserved','charged','settled','released')),
        policy_json TEXT NOT NULL CHECK (json_valid(policy_json)),
        created_at TEXT NOT NULL,
        settled_at TEXT,
        released_at TEXT
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_budget_reservations_cycle_status "
    "ON agent_budget_reservations(cycle_id,status,created_at)",
)

MIGRATION_013 = (
    """
    CREATE TABLE IF NOT EXISTS model_bundle_releases (
        release_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL UNIQUE REFERENCES change_proposals(proposal_id),
        prepare_idempotency_key TEXT NOT NULL UNIQUE,
        candidate_manifest_json TEXT NOT NULL CHECK (json_valid(candidate_manifest_json)),
        baseline_manifest_json TEXT NOT NULL CHECK (json_valid(baseline_manifest_json)),
        promotion_policy_json TEXT NOT NULL CHECK (json_valid(promotion_policy_json)),
        status TEXT NOT NULL CHECK (status IN (
          'prepared','shadow','promoted','superseded','rolled_back')),
        content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) STRICT
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_bundle_single_shadow "
    "ON model_bundle_releases((1)) WHERE status='shadow'",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_bundle_single_promoted "
    "ON model_bundle_releases((1)) WHERE status='promoted'",
    """
    CREATE TABLE IF NOT EXISTS model_bundle_release_events (
        release_event_id TEXT PRIMARY KEY,
        release_id TEXT NOT NULL REFERENCES model_bundle_releases(release_id)
          ON DELETE CASCADE,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        idempotency_key TEXT NOT NULL UNIQUE,
        from_status TEXT CHECK (from_status IS NULL OR from_status IN (
          'prepared','shadow','promoted','superseded','rolled_back')),
        to_status TEXT NOT NULL CHECK (to_status IN (
          'prepared','shadow','promoted','superseded','rolled_back')),
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
        evidence_sha256 TEXT NOT NULL CHECK (length(evidence_sha256) = 64),
        occurred_at TEXT NOT NULL,
        UNIQUE (release_id, sequence)
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_model_bundle_events_release_time "
    "ON model_bundle_release_events(release_id,occurred_at DESC)",
)

MIGRATION_014 = (
    "ALTER TABLE cycle_manifests ADD COLUMN memory_summary_json TEXT NOT NULL "
    "DEFAULT '{}' CHECK (json_valid(memory_summary_json))",
)

MIGRATION_015 = (
    "ALTER TABLE research_runs ADD COLUMN result_schema TEXT NOT NULL "
    "DEFAULT 'mova-research-brief-v1'",
    "ALTER TABLE research_runs ADD COLUMN coverage_json TEXT NOT NULL "
    "DEFAULT '{}' CHECK (json_valid(coverage_json))",
    "ALTER TABLE research_runs ADD COLUMN coverage_status TEXT NOT NULL "
    "DEFAULT 'legacy_unmeasured' CHECK (coverage_status IN ("
    "'legacy_unmeasured','complete','partial','failed'))",
    "ALTER TABLE research_runs ADD COLUMN coverage_ratio REAL "
    "CHECK (coverage_ratio IS NULL OR coverage_ratio BETWEEN 0 AND 1)",
    "ALTER TABLE research_runs ADD COLUMN evidence_ratio REAL "
    "CHECK (evidence_ratio IS NULL OR evidence_ratio BETWEEN 0 AND 1)",
    "ALTER TABLE research_documents ADD COLUMN final_url TEXT",
    "ALTER TABLE research_documents ADD COLUMN fetch_status TEXT NOT NULL "
    "DEFAULT 'legacy_unverified' CHECK (fetch_status IN ("
    "'legacy_unverified','verified','failed'))",
    "ALTER TABLE research_documents ADD COLUMN http_status INTEGER",
    "ALTER TABLE research_documents ADD COLUMN content_type TEXT",
    "ALTER TABLE research_documents ADD COLUMN body_sha256 TEXT",
    "ALTER TABLE research_documents ADD COLUMN normalized_sha256 TEXT",
    "ALTER TABLE research_documents ADD COLUMN storage_mode TEXT",
    "ALTER TABLE research_documents ADD COLUMN locator_type TEXT",
    "ALTER TABLE research_documents ADD COLUMN locator TEXT",
    "ALTER TABLE research_documents ADD COLUMN excerpt TEXT",
    "ALTER TABLE research_documents ADD COLUMN excerpt_sha256 TEXT",
    "ALTER TABLE research_documents ADD COLUMN artifact_path TEXT",
    "ALTER TABLE research_documents ADD COLUMN artifact_sha256 TEXT",
    "ALTER TABLE research_documents ADD COLUMN fetch_error_code TEXT",
)

MIGRATION_016 = (
    """
    CREATE TABLE IF NOT EXISTS browser_rehearsals (
        rehearsal_id TEXT PRIMARY KEY,
        cycle_id TEXT NOT NULL REFERENCES gameweek_cycles(cycle_id),
        capability TEXT NOT NULL CHECK (capability IN ('captaincy','lineup','r3')),
        contract_version TEXT NOT NULL,
        evidence_mode TEXT NOT NULL CHECK (evidence_mode IN ('read_only_probe','validate_only')),
        status TEXT NOT NULL CHECK (status IN ('passed','failed')),
        writes_attempted INTEGER NOT NULL CHECK (writes_attempted = 0),
        checks_json TEXT NOT NULL CHECK (json_valid(checks_json)),
        evidence_path TEXT NOT NULL,
        evidence_sha256 TEXT NOT NULL CHECK (length(evidence_sha256) = 64),
        content_sha256 TEXT NOT NULL UNIQUE CHECK (length(content_sha256) = 64),
        idempotency_key TEXT NOT NULL UNIQUE,
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_browser_rehearsal_pass_once "
    "ON browser_rehearsals(cycle_id,capability,contract_version) WHERE status='passed'",
    "CREATE INDEX IF NOT EXISTS idx_browser_rehearsal_capability_time "
    "ON browser_rehearsals(capability,contract_version,observed_at DESC)",
)

MIGRATION_017 = (
    "ALTER TABLE decision_deliberations ADD COLUMN semantic_input_sha256 TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_deliberations_semantic_once "
    "ON decision_deliberations(cycle_id,provider,semantic_input_sha256) "
    "WHERE semantic_input_sha256 IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS decision_deliberation_bindings (
        envelope_id TEXT PRIMARY KEY REFERENCES decision_envelopes(envelope_id)
          ON DELETE CASCADE,
        deliberation_id TEXT NOT NULL REFERENCES decision_deliberations(deliberation_id)
          ON DELETE CASCADE,
        semantic_input_sha256 TEXT NOT NULL,
        binding_type TEXT NOT NULL CHECK (binding_type IN ('original','semantic_reuse')),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    "CREATE INDEX IF NOT EXISTS idx_deliberation_bindings_deliberation "
    "ON decision_deliberation_bindings(deliberation_id,created_at DESC)",
)

MIGRATIONS = (
    (1, "initial_ops_schema", MIGRATION_001),
    (2, "team_state_artifact_provenance", MIGRATION_002),
    (3, "team_state_observation_freshness", MIGRATION_003),
    (4, "gameweek_settlement_and_review", MIGRATION_004),
    (5, "strategic_context_and_research", MIGRATION_005),
    (6, "repair_imported_research_state", MIGRATION_006),
    (7, "typed_decision_envelopes", MIGRATION_007),
    (8, "bounded_strategy_deliberations", MIGRATION_008),
    (9, "execution_plans_and_preflight", MIGRATION_009),
    (10, "apply_once_execution_attempts", MIGRATION_010),
    (11, "continuous_improvement_gate", MIGRATION_011),
    (12, "agent_cost_budgets", MIGRATION_012),
    (13, "model_bundle_release_gate", MIGRATION_013),
    (14, "strategic_memory_snapshots", MIGRATION_014),
    (15, "sealed_research_evidence_and_coverage", MIGRATION_015),
    (16, "browser_rehearsal_evidence_ledger", MIGRATION_016),
    (17, "semantic_deliberation_idempotency", MIGRATION_017),
)

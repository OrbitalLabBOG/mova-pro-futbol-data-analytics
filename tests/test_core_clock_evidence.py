from experiments.data_ground_truth.core_clock_evidence import inspect_code, past_comparison


def test_exporter_consumer_assumption_is_scoped_and_never_executed():
    source = b"raise RuntimeError('must not execute')\ndef infer_gameweek(kickoff):\n return pd.to_datetime(kickoff, utc=True)\n"
    assert inspect_code(source)['infer_gameweek_uses_utc'] is True
    assert inspect_code(b'pd.to_datetime(kickoff, utc=True)')['infer_gameweek_uses_utc'] is False
    broken = inspect_code(b'def incomplete(')
    assert broken['parseable'] is False
    assert broken['infer_gameweek_uses_utc'] is None


def test_clock_comparison_excludes_either_future_and_aware_source():
    cutoff = '2025-09-01T00:00:00Z'
    assert past_comparison('2025-09-02T12:00:00', '2025-08-23T14:00:00Z', cutoff) is None
    assert past_comparison('2025-08-23T14:00:00', '2025-09-02T12:00:00Z', cutoff) is None
    assert past_comparison('2025-08-23T14:00:00Z', '2025-08-23T14:00:00Z', cutoff) is None
    assert past_comparison('2025-09-01T00:00:00', '2025-08-23T14:00:00Z', cutoff) is None


def test_clock_diagnostic_retains_residual_and_seasonal_offset():
    summer = past_comparison('2025-08-23T15:00:00', '2025-08-23T14:00:00Z', '2026-01-01T00:00:00Z')
    winter = past_comparison('2025-12-01T14:00:00', '2025-12-01T14:00:00Z', '2026-01-01T00:00:00Z')
    assert summer == {'delta_seconds': 3600, 'reference_uk_offset_seconds': 3600}
    assert winter == {'delta_seconds': 0, 'reference_uk_offset_seconds': 0}

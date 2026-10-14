from pathlib import Path

import pytest

from experiments.gw6_recovery.freeze import freeze


def test_freeze_is_immutable_and_marks_seen_evidence_as_development(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'result.json').write_text('{"points":44}')
    output = tmp_path / 'manifest.json'
    manifest = freeze(data, output)
    assert manifest['status'] == 'development_only'
    assert manifest['prospective_candidate_frozen'] is False
    assert manifest['protocol']['exposed_gameweeks']['2026-27'] == [2, 3, 4, 5, 6]
    assert len(manifest['evidence']['result.json']['sha256']) == 64
    with pytest.raises(FileExistsError):
        freeze(data, output)
    with pytest.raises(ValueError):
        freeze(data, data / 'recursive.json')

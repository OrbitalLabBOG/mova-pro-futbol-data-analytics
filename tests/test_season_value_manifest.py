import hashlib
import json
from pathlib import Path
import pytest
from mova_fpl.cli.season_value_shadow import load_manifest
from mova_fpl.ops.config import RuntimeConfig


def test_manifest_refuses_unsealed_or_executable_candidate(tmp_path):
    p = tmp_path / 'manifest.json'
    p.write_text(json.dumps({'schema': 'mova-season-value-shadow-v1', 'selected_for_execution': True}))
    with pytest.raises(ValueError, match='manifest and SHA'):
        load_manifest(p, None)
    with pytest.raises(ValueError, match='hash mismatch'):
        load_manifest(p, 'a' * 64)
    with pytest.raises(ValueError, match='authority'):
        load_manifest(p, hashlib.sha256(p.read_bytes()).hexdigest())


def test_manifest_cannot_escape_model_root(tmp_path):
    p = tmp_path / 'manifest.json'
    p.write_text(json.dumps({'schema': 'mova-season-value-shadow-v1', 'selected_for_execution': False,
                            'models': {'minutes': {'version': '../../file'}}}))
    with pytest.raises(ValueError, match='model version'):
        load_manifest(p, hashlib.sha256(p.read_bytes()).hexdigest())


def test_runtime_configuration_requires_explicit_manifest(monkeypatch):
    monkeypatch.delenv('MOVA_SEASON_VALUE_SHADOW_MANIFEST', raising=False)
    assert RuntimeConfig.from_env().season_value_shadow_manifest is None
    monkeypatch.setenv('MOVA_SEASON_VALUE_SHADOW_MANIFEST', '/artifacts/shadow.json')
    monkeypatch.setenv('MOVA_SEASON_VALUE_SHADOW_SHA256', 'b' * 64)
    c = RuntimeConfig.from_env()
    assert c.season_value_shadow_manifest == Path('/artifacts/shadow.json')
    assert c.season_value_shadow_sha256 == 'b' * 64
    assert c.enable_browser_writes is False

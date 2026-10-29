"""DR probe keeps transient evidence and rejects actual readiness failures."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def probe(monkeypatch):
    spec = importlib.util.spec_from_file_location('dr_probe', Path(__file__).parents[1] / 'deploy/bin/dr-preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    return module


def response(code=0, body='{"status":"ready"}'):
    return SimpleNamespace(returncode=code, stdout=body, stderr='SECRET_MUST_NOT_LEAK')


def test_transient_then_success_retains_failure(probe, monkeypatch):
    results = iter([response(28), response(7), response()])
    monkeypatch.setattr(probe.subprocess, 'run', lambda *a, **k: next(results))
    report = probe.api_ready()
    assert report['status'] == 'ready'
    assert [a['status'] for a in report['attempts']] == ['blocked', 'blocked', 'pass']
    assert 'SECRET' not in str(report)


@pytest.mark.parametrize('code,body', [(22, ''), (0, 'not-json'), (0, '{"status":"not_ready"}'), (0, '[]')])
def test_semantic_and_http_errors_fail_immediately(probe, monkeypatch, code, body):
    calls = []
    def run(*a, **k):
        calls.append(a)
        return response(code, body)
    monkeypatch.setattr(probe.subprocess, 'run', run)
    with pytest.raises(probe.ApiProbeError) as failure:
        probe.api_ready()
    assert len(calls) == 1
    assert 'SECRET' not in str(failure.value.detail)


def test_exhausted_transport_is_blocked_and_bounded(probe, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(args, 12, stderr='SECRET_MUST_NOT_LEAK')
    monkeypatch.setattr(probe.subprocess, 'run', run)
    with pytest.raises(probe.ApiProbeError) as failure:
        probe.api_ready()
    assert len(calls) == len(failure.value.detail['attempts']) == 3
    assert all(k['timeout'] == 12 for a, k in calls)
    assert all(a[-1] == 'http://127.0.0.1:8787/readyz' for a, k in calls)
    assert 'SECRET' not in str(failure.value.detail)

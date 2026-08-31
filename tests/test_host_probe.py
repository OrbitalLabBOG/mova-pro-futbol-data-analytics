from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _module():
    spec = importlib.util.spec_from_file_location(
        "mova_host_probe", Path("deploy/bin/host-probe.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configured(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "offsite-repository"
    password = tmp_path / "offsite-password"
    repository.write_text("s3:s3.example.test/mova-backups", encoding="utf-8")
    password.write_text("test-only-secret", encoding="utf-8")
    repository.chmod(0o600)
    password.chmod(0o600)
    config = tmp_path / "offsite-backup.json"
    config.write_text(
        '{"schema":"mova-offsite-backup-v1","enabled":true,'
        '"provider":"restic","owner":"operator",'
        f'"repository_file":"{repository}","password_file":"{password}"}}',
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config, repository


def test_offsite_probe_is_sanitized_and_requires_active_timer(tmp_path, monkeypatch):
    module = _module()
    config, repository = _configured(tmp_path)
    monkeypatch.setattr(module, "unit_state", lambda _name: {
        "load_state": "loaded", "active_state": "active", "unit_file_state": "enabled",
    })

    result = module.offsite_backup_status(
        config, credential_root=tmp_path, required_uid=os.getuid(),
    )

    assert result["status"] == "configured"
    assert result["configured"] is True and result["external"] is True
    assert len(result["destination_fingerprint"]) == 16
    rendered = str(result)
    assert str(tmp_path) not in rendered
    assert repository.read_text(encoding="utf-8") not in rendered
    assert "test-only-secret" not in rendered


def test_offsite_probe_rejects_local_repository_and_broad_permissions(tmp_path, monkeypatch):
    module = _module()
    config, repository = _configured(tmp_path)
    repository.write_text("/var/lib/mova-fpl/restic", encoding="utf-8")
    config.chmod(0o644)
    monkeypatch.setattr(module, "unit_state", lambda _name: {
        "load_state": "loaded", "active_state": "active", "unit_file_state": "enabled",
    })

    result = module.offsite_backup_status(
        config, credential_root=tmp_path, required_uid=os.getuid(),
    )

    assert result["status"] == "invalid"
    assert "repository_not_external" in result["reasons"]
    assert "config_permissions_too_broad" in result["reasons"]
    assert result["destination_fingerprint"] is None


def test_offsite_probe_missing_config_is_explicitly_unconfigured(tmp_path):
    module = _module()
    result = module.offsite_backup_status(tmp_path / "missing.json")
    assert result["status"] == "unconfigured"
    assert result["reasons"] == ["config_missing"]


def test_offsite_service_is_opt_in_and_excludes_runtime_secrets():
    install = Path("deploy/bin/install-systemd.sh").read_text(encoding="utf-8")
    script = Path("deploy/bin/offsite-backup.sh").read_text(encoding="utf-8")
    service = Path("deploy/systemd/mova-fpl-offsite-backup.service").read_text(
        encoding="utf-8"
    )
    assert "enable --now mova-fpl-offsite-backup.timer" not in install
    assert "RESTIC_REPOSITORY_FILE" in script and "RESTIC_PASSWORD_FILE" in script
    assert "backup-all.sh" in script and "postgres-shadow-backup.sh" in script
    assert "browser-profile" not in script and "codex-home" not in script
    assert "User=root" in service and "NoNewPrivileges=true" in service

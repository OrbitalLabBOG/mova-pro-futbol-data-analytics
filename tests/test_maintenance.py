from __future__ import annotations

import os
import time

from mova_fpl.ops.maintenance import cleanup


def test_cleanup_is_dry_run_by_default_and_preserves_evidence(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    transient = root / "fetch.partial"
    decision = root / "decision.json"
    transient.write_text("partial", encoding="utf-8")
    decision.write_text("evidence", encoding="utf-8")
    old = time.time() - 90000
    os.utime(transient, (old, old))
    os.utime(decision, (old, old))

    preview = cleanup(root)
    assert preview["mode"] == "dry-run"
    assert [item["path"] for item in preview["candidates"]] == ["fetch.partial"]
    assert transient.exists() and decision.exists()

    applied = cleanup(root, apply=True)
    assert applied["removed_count"] == 1
    assert not transient.exists()
    assert decision.read_text(encoding="utf-8") == "evidence"


def test_cleanup_ignores_symlinks_and_recent_transients(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.tmp"
    outside.write_text("keep", encoding="utf-8")
    (root / "linked.tmp").symlink_to(outside)
    (root / "recent.tmp").write_text("keep", encoding="utf-8")

    result = cleanup(root, older_than_seconds=3600, apply=True)
    assert result["candidate_count"] == 0
    assert outside.exists()

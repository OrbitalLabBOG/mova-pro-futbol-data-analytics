"""Sella protocolo y evidencia expuesta sin modificar sus archivos ni producción."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def freeze(evidence: Path, output: Path) -> dict:
    root = evidence.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('evidence debe ser un directorio')
    output = output.absolute()
    if output.is_relative_to(root):
        raise ValueError('manifest debe quedar fuera de la evidencia')
    protocol = Path(__file__).with_name('protocol.json')
    repo = Path(__file__).resolve().parents[2]
    paths = sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink())
    if not paths:
        raise ValueError('evidencia vacía')
    payload = {
        'schema': 'mova-gw6-recovery-manifest-v1',
        'registered_at': datetime.now(timezone.utc).isoformat(),
        'status': 'development_only',
        'prospective_candidate_frozen': False,
        'protocol': json.loads(protocol.read_text()),
        'protocol_sha256': digest(protocol),
        'git_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                           text=True).strip(),
        'working_tree_dirty': bool(subprocess.check_output(
            ['git', 'status', '--porcelain'], cwd=repo, text=True).strip()),
        'source_files': {str(p.relative_to(repo)): digest(p)
                         for folder in ('mova_fpl', 'experiments/gw6_recovery')
                         for p in sorted((repo / folder).rglob('*.py'))},
        'evidence_root': str(root),
        'evidence': {str(p.relative_to(root)): {'sha256': digest(p),
                                                'bytes': p.stat().st_size}
                     for p in paths},
    }
    # Exclusive creation: an opened experiment cannot silently be rewritten.
    with output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write('\n')
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = freeze(args.evidence_dir, args.output)
    print(json.dumps({'status': result['status'], 'files': len(result['evidence']),
                      'output': str(args.output)}))

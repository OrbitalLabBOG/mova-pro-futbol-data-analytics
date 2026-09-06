"""Measure PL archive completeness and ID namespaces independently of provider claims."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import re
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.decoding import read_csv_bytes
from experiments.data_ground_truth.raw import digest


def audit_archive(root: Path) -> dict:
    records = json.loads((root / 'manifest.json').read_text())['records']
    groups = defaultdict(list)
    events, failures = {}, []
    for r in records:
        if not r['repository'].startswith('imadeddine-belkat/') or not r['path'].startswith('pl_stats/'):
            continue
        if not re.match(r'\d{4}-\d{2}_', Path(r['path']).name):
            continue
        if '/_merged/players_match_stats/' in r['path']:
            continue
        if '/players_match_stats/' not in r['path'] and '/_merged/events/' not in r['path']:
            continue
        data = (root / 'objects' / r['sha256']).read_bytes()
        if digest(data) != r['sha256']:
            raise ValueError('checksum mismatch')
        try:
            df, encoding = read_csv_bytes(data)
        except (ValueError, UnicodeDecodeError, pd.errors.ParserError) as exc:
            failures.append(dict(path=r['path'], error=type(exc).__name__))
            continue
        season = Path(r['path']).name[:7]
        if '/_merged/events/' in r['path']:
            events[season] = df
        else:
            groups[season].append(df)
    report = dict(version='pl-archive-audit-v1', failures=failures, seasons={})
    for season in sorted(set(groups) | set(events)):
        frames = groups.get(season, [])
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        matches = events.get(season, pd.DataFrame())
        entry = dict(player_rows=len(frame), club_files=len(frames), fixture_rows=len(matches))
        if not matches.empty:
            entry.update(unique_fixtures=int(matches.matchId.nunique()),
                duplicate_fixture_ids=int(matches.matchId.duplicated().sum()),
                missing_kickoff=int(pd.to_datetime(matches.kickoff, errors='coerce', format='mixed', utc=True).isna().sum()))
        if not frame.empty:
            missing_keys = frame[['matchId','playerId']].isna().any(axis=1)
            native_ids = set(frame.matchId.dropna())
            entry.update(native_player_match_ids=len(native_ids),
                missing_keys=int(missing_keys.sum()),
                duplicate_native_keys=int(frame.duplicated(['matchId','playerId']).sum()),
                native_match_ids_in_event_table=len(native_ids & set(matches.matchId)) if not matches.empty else 0,
                player_id_equals_opta_code=int(frame.playerId.eq(frame.pl_code).sum()),
                opta_code_rows=int(frame.pl_code.notna().sum()),
                observed_minutes_rows=int(frame.minutesPlayed.notna().sum()),
                invalid_minutes_rows=int(((frame.minutesPlayed < 0) | (frame.minutesPlayed > 90)).sum()),
                column_coverage={c:int(frame[c].notna().sum()) for c in frame.columns},
                training_status='quarantined_pending_fixture_and_identity_reconciliation')
        report['seasons'][season] = entry
    (root / 'archive-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    args = ap.parse_args()
    result = audit_archive(args.root)
    print(json.dumps({**result, 'seasons': {s:{k:v for k,v in d.items() if k!='column_coverage'} for s,d in result['seasons'].items()}}, indent=2))


if __name__ == '__main__':
    main()

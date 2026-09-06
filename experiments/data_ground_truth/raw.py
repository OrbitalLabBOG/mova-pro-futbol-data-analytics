"""Pinned public GitHub acquisition; immutable bytes and conservative time semantics."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote

from mova_fpl.data.sources import _get

REPOS = ('vaastav/Fantasy-Premier-League', 'olbauday/FPL-Core-Insights',
         'imadeddine-belkat/Premier-League-Stats', 'TopMarxFPL/fpl-mirror', 'durtal/fantasysocceR',
         'prathmesh/Fantasy-Premier-League-Points-Predictor', 'clwatkins/fantasy_premier_league',
         'mvbfontes/premierleaguedatasets', 'sjp4/differentialfpl',
         'darrenvong/fpl-data-visualiser', 'Randdalf/fplcache', 'Schwetche/fpl_project', 'hudl/open-data', 'lifebeyondfife/FantasyFootball', 'keithxm23/fplPlayer', 'keithxm23/fplassistant', 'keithxm23/fplassistantv2', 'barryedmund/gaffer')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture(root: Path, repo: str, revision: str, path: str) -> dict:
    if repo not in REPOS or not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('allowlisted repository and full commit required')
    if PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts:
        raise ValueError('unsafe source path')
    url = f'https://raw.githubusercontent.com/{repo}/{revision}/{quote(path, safe="/")}'
    key = digest(url.encode())
    record_path = root / 'records' / f'{key}.json'
    if record_path.exists():
        record = json.loads(record_path.read_text())
        blob = root / 'objects' / record['sha256']
        if digest(blob.read_bytes()) != record['sha256']:
            raise ValueError(f'corrupt raw object: {key}')
        return record
    data = _get(url)
    sha = digest(data)
    blob = root / 'objects' / sha
    blob.parent.mkdir(parents=True, exist_ok=True)
    # Publish complete bytes atomically; parallel paths may contain identical data.
    with tempfile.NamedTemporaryFile(dir=blob.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temporary, blob)
        except FileExistsError:
            if digest(blob.read_bytes()) != sha:
                raise ValueError('content-addressed object collision or corruption')
    finally:
        temporary.unlink()
    record = dict(repository=repo, revision=revision, path=path, url=url,
                  sha256=sha, bytes=len(data), fetched_at=datetime.now(timezone.utc).isoformat(),
                  available_at=None, time_semantics='retrospective_unknown_publication',
                  eligible_predeadline=False)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = record_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(record, indent=2) + '\n')
    tmp.replace(record_path)
    return record


def select(repo: str, path: str) -> bool:
    if path in ('README.md', 'LICENSE', 'DATA_INTEGRATION_REVIEW.md'):
        return True
    if repo == 'barryedmund/gaffer':
        return path == 'lib/tasks/get_player_data.rake' or bool(re.fullmatch(r'public/player_data/2015_16_[0-9]+\.json', path))
    if repo == 'keithxm23/fplPlayer':
        return path in {'data.json', 'fplplayers.py'}
    if repo in {'keithxm23/fplassistant', 'keithxm23/fplassistantv2'}:
        return path in {'data.json', 'README.rdoc', 'db/schema.rb'}
    if repo == 'lifebeyondfife/FantasyFootball':
        return path == 'LICENCE.txt' or path in {
            'Fantasy Football Team Selector 13-14.xlsm',
            'Fantasy Football Team Selector 14-15.xlsm',
            'Fantasy Football Team Selector Official 2012-13/Fantasy Football Team Selector 12-13.xlsm',
        }
    if repo == REPOS[9]:
        return bool(re.fullmatch(r'dump/players/(?:current_gw|gw[0-9]+)\.(?:bson|metadata\.json)',path))
    if repo == REPOS[8]:
        return path in {
            'README.MD', 'LICENCE.txt',
            'Differential/Database/DiffGen_11_37.db3',
            'Differential/Database/DiffGen_13.db3',
            'Differential/Database/DiffGen_14.db3',
            'Differential/Database/diffgen14b.db3',
            'Differential/Database/DiffGen_15.db3',
            'Differential/Database/DiffGen_15a.db3',
            'Differential/Database/diffgen15_final.db3',
            'Differential/Database/diffgen16.db3',
            'Differential/Database/release_prep.sql',
            'Differential/Database/DiffGenTestData_11_38.sql',
            'Differential/src/com/pennas/fpl/scrape/ScrapeMatchScoresCatchup.java',
            'Differential/src/com/pennas/fpl/scrape/ScrapeMatchScores_New.java',
            'Differential/src/com/pennas/fpl/util/DbGen.java',
            'Differential/src/com/pennas/fpl/process/ProcessPlayer.java',
        }
    if repo == REPOS[7]:
        return bool(re.fullmatch(r'PlayersInfo/[0-9]+\.json', path))
    if repo == REPOS[5]:
        return path == 'Data/dec15_players.csv'
    if repo == REPOS[6]:
        return path == 'Data/FPL_API_Dump.json'
    if repo == REPOS[0]:
        return bool(re.fullmatch(r'data/20(?:1[6-9]|2[0-5])-\d{2}/(?:gws/merged_gw|players_raw|fixtures|teams)\.csv', path))
    if repo == REPOS[2]:
        return bool(re.fullmatch(r'(?:pl_stats/(?:_merged/events/[^/]+|[^/]+/(?:players_match_stats|squad)/[^/]+)|fpl_scraper/fpl_stats/_merged/players/[^/]+)\.csv', path))
    if repo == REPOS[4]:
        return path == 'DESCRIPTION' or path.startswith('man/') or bool(re.fullmatch(r'data/[^/]+\.RData', path))
    if repo == REPOS[3]:
        return bool(re.fullmatch(r'data/\d{4}/csv/(?:fixtures|gameweeks|players|teams)\.csv', path))
    if path.startswith('data/2024-2025/'):
        return bool(re.fullmatch(r'data/2024-2025/(?:(matches|playermatchstats)/GW\d+/[^/]+|(players|teams)/[^/]+)\.csv', path))
    return bool(re.fullmatch(r'data/202[56]-202[67]/(?:By Gameweek/GW\d+/(?:matches|playermatchstats|players|player_gameweek_stats)|gameweek_summaries|players|teams)\.csv', path))


def acquire(root: Path, pins: dict[str, str]) -> dict:
    records, errors = [], []
    for repo, revision in pins.items():
        if repo not in REPOS or not re.fullmatch('[0-9a-f]{40}', revision):
            raise ValueError('invalid pin')
        inventory = root / 'inventories' / (repo.split('/')[0] + '-' + revision + '.json')
        if inventory.exists():
            tree = json.loads(inventory.read_text())
        else:
            tree = json.loads(_get(f'https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1'))
        if tree.get('sha') != revision or tree.get('truncated'):
            raise ValueError('incomplete or mismatched source inventory')
        # Reuse a previously captured inventory when the public metadata API is unavailable.
        inventory.parent.mkdir(parents=True, exist_ok=True)
        if not inventory.exists():
            inventory.write_text(json.dumps(tree, indent=2) + '\n')
        paths = [x['path'] for x in tree['tree'] if x['type'] == 'blob' and select(repo, x['path'])]
        def one(path):
            try:
                return capture(root, repo, revision, path), None
            except Exception as exc:
                return None, dict(repository=repo, path=path, error=type(exc).__name__)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for record, error in pool.map(one, paths):
                if error:
                    errors.append(error)
                else:
                    records.append(record)
        print(f'{repo}: {len(paths)} selected files', flush=True)
    report = dict(schema_version=1, pins=pins, records=sorted(records, key=lambda x: x['url']), errors=errors)
    (root / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    args = parser.parse_args()
    report = acquire(args.root, json.loads(args.pins.read_text()))
    print(json.dumps(dict(files=len(report['records']), bytes=sum(r['bytes'] for r in report['records']), errors=report['errors'])))
    if report['errors']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()

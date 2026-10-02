"""Seal and compare every PostgreSQL table using the dump's exported snapshot.

Runs on the host via the provisioned container's local socket. Never emits rows,
connection strings or credential values. Restore can target a fresh container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import select
from pathlib import Path
from datetime import datetime, timezone

SCHEMA = "mova-postgres-backup-v2"
REQUIRED_SCHEMAS = {"mova_meta", "raw", "analytics", "game", "research", "agent", "ops"}
TABLES_SQL = """
SELECT json_build_object('schema', table_schema, 'name', table_name,
 'columns', json_agg(json_build_object('name', column_name, 'type', udt_schema || '.' || udt_name,
 'nullable', is_nullable, 'position', ordinal_position, 'default', column_default,
 'max_length', character_maximum_length, 'precision', numeric_precision, 'scale', numeric_scale,
 'datetime_precision', datetime_precision, 'identity', identity_generation,
 'generated', generation_expression, 'collation', collation_name) ORDER BY ordinal_position))
FROM information_schema.columns
WHERE table_schema NOT LIKE 'pg_%' AND table_schema <> 'information_schema'
 AND (table_schema,table_name) IN (SELECT table_schema,table_name FROM information_schema.tables
 WHERE table_type='BASE TABLE')
GROUP BY table_schema,table_name ORDER BY table_schema,table_name;
"""


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def content_sql(tables: list[dict]) -> str:
    parts = []
    for table in tables:
        name = identifier(table['schema']) + '.' + identifier(table['name'])
        parts.append(
            "SELECT json_build_object('schema', " + literal(table['schema'])
            + ", 'name', " + literal(table['name'])
            + ", 'rows', count(*), 'content_sha256', encode(sha256(convert_to(coalesce(string_agg(row_hash, '' "
            "ORDER BY row_hash COLLATE \"C\"), ''), 'UTF8')), 'hex')) FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text, 'UTF8')), 'hex') row_hash FROM "
            + name + " t) hashed"
        )
    if not parts:
        raise ValueError("PostgreSQL backup has no application tables")
    return ' UNION ALL '.join(parts) + ';'


class Client:
    def __init__(self, database: str, user: str, container: str | None = None):
        self.prefix = ['docker', 'exec', '-i', container] if container else [
            'docker', 'compose', 'exec', '-T', 'postgres']
        self.args = ['--username=' + user, '--dbname=' + database]

    def query(self, query: str, snapshot: str | None = None) -> list[dict]:
        transaction = "SET timezone='UTC'; SET datestyle='ISO, YMD'; SET intervalstyle='postgres';\n"
        transaction += 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n'
        if snapshot:
            if not re.fullmatch(r'[0-9A-Fa-f-]+', snapshot):
                raise ValueError('invalid exported snapshot')
            transaction += 'SET TRANSACTION SNAPSHOT ' + literal(snapshot) + ';\n'
        result = subprocess.run(self.prefix + ['psql', '-w', '-XAtq', '-v', 'ON_ERROR_STOP=1'] + self.args,
                                input=transaction + query + '\nCOMMIT;', text=True,
                                capture_output=True, timeout=900)
        if result.returncode:
            raise RuntimeError('PostgreSQL read-only inventory failed')
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def inventory(self, snapshot: str | None = None) -> dict:
        tables = self.query(TABLES_SQL, snapshot)
        if not REQUIRED_SCHEMAS <= {item['schema'] for item in tables}:
            raise ValueError('required PostgreSQL schemas missing')
        rows = self.query(content_sql(tables), snapshot)
        contents = {(item['schema'], item['name']): item for item in rows}
        return {'schema': 'mova-postgres-content-v1', 'tables': [
            {**item, **contents[(item['schema'], item['name'])]} for item in tables]}

    def backup(self, directory: Path, revision: str) -> None:
        keeper = subprocess.Popen(
            self.prefix + ['psql', '-w', '-XAtq', '-v', 'ON_ERROR_STOP=1'] + self.args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            # Inventory and dump each have a 900 s client timeout. Keep their
            # shared snapshot alive beyond that bounded window even when the
            # server's normal idle transaction limit is much shorter.
            keeper.stdin.write("SET idle_in_transaction_session_timeout = '35min';\n"
                               'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT pg_export_snapshot();\n')
            keeper.stdin.flush()
            if not select.select([keeper.stdout], [], [], 30)[0]:
                raise RuntimeError('PostgreSQL snapshot export timed out')
            snapshot = keeper.stdout.readline().strip()
            if not re.fullmatch(r'[0-9A-Fa-f-]+', snapshot):
                raise RuntimeError('could not export PostgreSQL snapshot')
            inventory = self.inventory(snapshot)
            dump = directory / 'postgres-shadow.dump'
            with dump.open('wb') as handle:
                result = subprocess.run(self.prefix + ['pg_dump', '-w', '--format=custom', '--no-owner',
                                        '--no-acl', '--snapshot=' + snapshot] + self.args,
                                        stdout=handle, stderr=subprocess.DEVNULL, timeout=900)
            if result.returncode:
                raise RuntimeError('PostgreSQL snapshot dump failed')
            with dump.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            manifest = {'schema': SCHEMA, 'created_at': datetime.now(timezone.utc).isoformat(), 'git_sha': revision, 'database': self.args[-1].split('=', 1)[1],
                        'dump': {'name': dump.name, 'sha256': digest, 'bytes': dump.stat().st_size},
                        'inventory': inventory}
            (directory / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')
        finally:
            if keeper.poll() is None:
                keeper.terminate()
            keeper.communicate(timeout=10)


def verify_inventory(expected: dict, observed: dict) -> None:
    if expected.get('schema') != 'mova-postgres-content-v1' or not expected.get('tables'):
        raise ValueError('sealed PostgreSQL content inventory required; renew legacy backup')
    if expected != observed:
        raise ValueError('restored PostgreSQL tables, columns, row counts or content differ')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('backup', 'verify'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--database', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--container')
    parser.add_argument('--revision', default='unknown')
    args = parser.parse_args()
    client = Client(args.database, args.user, args.container)
    if args.command == 'backup':
        client.backup(args.directory, args.revision)
    else:
        manifest = json.loads((args.directory / 'manifest.json').read_text())
        if manifest.get('schema') != SCHEMA:
            raise ValueError('content-sealed v2 PostgreSQL backup required')
        verify_inventory(manifest.get('inventory') or {}, client.inventory())
        print(json.dumps({'status': 'pass', 'tables': len(manifest['inventory']['tables'])}))


if __name__ == '__main__':
    main()

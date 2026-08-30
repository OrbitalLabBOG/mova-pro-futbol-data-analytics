"""Adapters de lectura para demostrar paridad SQLite/PostgreSQL.

El runtime continúa escribiendo en SQLite. Estos adapters leen la fotografía
inmutable usada por un import y su mirror PostgreSQL, normalizan tipos y
producen hashes de contenido independientes del orden físico de las filas.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from psycopg import sql

ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


class TableMapping(Protocol):
    source_db: str
    source_table: str
    target_table: str
    renames: dict[str, str]
    json_columns: frozenset[str]
    bool_columns: frozenset[str]
    include_rowid: bool


@dataclass(frozen=True, slots=True)
class ContentSnapshot:
    row_count: int
    content_sha256: str
    columns: tuple[str, ...]


def _timestamp(value: str) -> str | None:
    if not ISO_TIMESTAMP.match(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def normalize(value):
    """Convierte tipos equivalentes de ambos engines a JSON canónico."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return _timestamp(value) or value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    raise TypeError(f"tipo no normalizable para paridad: {type(value).__name__}")


def _canonical_row(row: dict) -> str:
    return json.dumps(
        normalize(row), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _snapshot(rows: list[dict], *, columns: tuple[str, ...] | None = None) -> ContentSnapshot:
    canonical = sorted(_canonical_row(row) for row in rows)
    digest = hashlib.sha256()
    for row in canonical:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    resolved_columns = tuple(sorted(rows[0])) if rows else tuple(sorted(columns or ()))
    return ContentSnapshot(
        row_count=len(canonical), content_sha256=digest.hexdigest(),
        columns=resolved_columns,
    )


class SQLiteReadRepository:
    def __init__(self, paths: dict[str, Path]):
        self.paths = paths

    def table(self, mapping: TableMapping) -> ContentSnapshot:
        con = sqlite3.connect(
            f"file:{self.paths[mapping.source_db]}?mode=ro", uri=True
        )
        con.row_factory = sqlite3.Row
        try:
            columns = [str(row[1]) for row in con.execute(
                f"pragma table_info([{mapping.source_table}])"
            )]
            if not columns:
                raise RuntimeError(
                    f"tabla SQLite ausente: {mapping.source_db}.{mapping.source_table}"
                )
            selected = ["source_row_id"] + columns if mapping.include_rowid else columns
            query = (
                f"select rowid as source_row_id,* from [{mapping.source_table}]"
                if mapping.include_rowid else f"select * from [{mapping.source_table}]"
            )
            rows = []
            for raw in con.execute(query):
                item = {}
                for column in selected:
                    value = raw[column]
                    if column in mapping.json_columns and isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            pass
                    if column in mapping.bool_columns and value is not None:
                        value = bool(value)
                    item[mapping.renames.get(column, column)] = value
                rows.append(item)
            target_columns = tuple(mapping.renames.get(column, column) for column in selected)
            return _snapshot(rows, columns=target_columns)
        finally:
            con.close()


class PostgresReadRepository:
    def __init__(self, connection):
        self.connection = connection

    def table(self, mapping: TableMapping,
              columns: tuple[str, ...] | None = None) -> ContentSnapshot:
        schema_name, table_name = mapping.target_table.split(".", 1)
        source_columns = list(columns or ())
        if not source_columns:
            exists = self.connection.execute(
                "select 1 as present from information_schema.tables "
                "where table_schema=%s and table_name=%s",
                (schema_name, table_name),
            ).fetchone()
            if not exists:
                raise RuntimeError(f"tabla PostgreSQL ausente: {mapping.target_table}")
            return _snapshot([], columns=())
        statement = sql.SQL("select {} from {}").format(
            sql.SQL(",").join(sql.Identifier(column) for column in source_columns),
            sql.Identifier(schema_name, table_name),
        )
        return _snapshot(
            [dict(row) for row in self.connection.execute(statement).fetchall()],
            columns=tuple(source_columns),
        )


def compare_exact(mapping: TableMapping, sqlite_repo: SQLiteReadRepository,
                  postgres_repo: PostgresReadRepository) -> dict:
    source = sqlite_repo.table(mapping)
    target = postgres_repo.table(mapping, source.columns)
    passed = (
        source.row_count == target.row_count
        and source.content_sha256 == target.content_sha256
    )
    return {
        "content_checked": True,
        "content_mode": "exact_rows",
        "content_status": "pass" if passed else "fail",
        "source_content_sha256": source.content_sha256,
        "target_content_sha256": target.content_sha256,
        "source_rows": source.row_count,
        "target_rows": target.row_count,
    }


def summary(details: list[dict]) -> dict:
    checked = [item for item in details if item.get("content_checked")]
    failed = [item for item in checked if item.get("content_status") != "pass"]
    body = {
        "schema": "mova-postgres-read-parity-v1",
        "status": "pass" if checked and not failed else "fail",
        "checked_tables": len(checked),
        "exact_tables": sum(item.get("content_mode") == "exact_rows" for item in checked),
        "aggregate_tables": sum(
            item.get("content_mode") == "aggregate_invariants" for item in checked
        ),
        "failed_tables": len(failed),
    }
    evidence = [{
        "mode": item.get("content_mode"),
        "status": item.get("content_status"),
        "source": item.get("source_content_sha256"),
        "target": item.get("target_content_sha256"),
    } for item in checked]
    evidence.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return {**body, "content_sha256": hashlib.sha256(json.dumps(
        {"summary": body, "evidence": evidence}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()}

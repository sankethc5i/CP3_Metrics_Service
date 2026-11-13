"""Load YAML safely and verify catalog references against a read-only database."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import yaml

from app.config import AS_OF_DATE, CATALOG_PATH, DATABASE_PATH
from app.db.connection import connect_readonly
from app.semantic.models import Catalog, DimensionSource
from app.sql.validation import validate_select


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*",value):
        raise ValueError(f"Invalid catalog identifier: {value}")
    return value


def _column(db: sqlite3.Connection, value: str) -> tuple[str,str]:
    parts = value.split(".")
    if len(parts) != 2:
        raise ValueError("Columns must be table-qualified")
    table, column = map(_identifier,parts)
    columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
    if column not in columns:
        raise ValueError(f"Unknown column: {value}")
    return table,column


def dimension_join_sql(db: sqlite3.Connection, base: str, source: DimensionSource) -> str:
    """Validate declared FK paths and return a trusted, fan-out-free FROM clause."""
    base = _identifier(base)
    available = {base}
    sql = f'FROM "{base}"'
    for join in source.joins:
        source_table,source_column = _column(db,join.source)
        target_table,target_column = _column(db,join.target)
        if source_table not in available or target_table in available:
            raise ValueError("Disconnected or cyclic dimension path")
        fks = db.execute(f'PRAGMA foreign_key_list("{source_table}")').fetchall()
        # A declared FK edge plus an individually unique target proves many-to-one.
        # This also permits session_id from the composite session/customer FK.
        matching = [r for r in fks if r[2] == target_table and r[3] == source_column and r[4] == target_column]
        if not matching:
            raise ValueError("Dimension path must follow a foreign key")
        info = db.execute(f'PRAGMA table_info("{target_table}")').fetchall()
        primary = [r[1] for r in info if r[5]]
        unique_keys = [primary]
        for index in db.execute(f'PRAGMA index_list("{target_table}")'):
            if index[2] and not index[4]:
                name = index[1].replace('"','""')
                unique_keys.append([r[2] for r in db.execute(f'PRAGMA index_info("{name}")')])
        if [target_column] not in unique_keys:
            raise ValueError("Dimension target must be individually unique")
        sql += f' JOIN "{target_table}" ON "{source_table}"."{source_column}"="{target_table}"."{target_column}"'
        available.add(target_table)
    table,_ = _column(db,source.column)
    if table not in available:
        raise ValueError("Dimension column not reachable from base table")
    return sql


def load_catalog(path: Path = CATALOG_PATH, database: Path = DATABASE_PATH) -> Catalog:
    """Validate Pydantic metadata, SQL references, and safe dimension join paths."""
    catalog = Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if catalog.as_of_date != AS_OF_DATE.isoformat():
        raise ValueError("Catalog AS_OF_DATE differs from frozen configuration")
    with closing(connect_readonly(database)) as db:
        relations = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")}
        dimensions = {d.id:d for d in catalog.dimensions}
        for dimension in catalog.dimensions:
            for base,source in dimension.sources.items():
                if base not in relations:
                    raise ValueError("Unknown dimension base table")
                dimension_join_sql(db,base,source)
        for metric in catalog.metrics:
            if metric.base_table not in relations:
                raise ValueError("Unknown metric base table")
            for dimension_id in metric.allowed_dimensions:
                if metric.base_table not in dimensions[dimension_id].sources:
                    raise ValueError(f"Unjoinable dimension {dimension_id} for {metric.id}")
            for sql in (metric.formula,metric.numerator,metric.denominator):
                if sql is None:
                    continue
                validate_select(sql,relations)
                try:
                    # SQLite's resolver checks every real column and CTE/view reference.
                    db.execute("EXPLAIN " + sql,{"as_of_date":catalog.as_of_date})
                except sqlite3.Error as error:
                    raise ValueError(f"Invalid SQL references for {metric.id}: {error}") from error
    return catalog

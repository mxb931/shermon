#!/usr/bin/env python3
"""One-time data migration from SQLite to MySQL for SherMon.

Usage examples:
  python scripts/migrate_sqlite_to_mysql.py \
    --source sqlite:////absolute/path/to/monitor.db \
    --target mysql+pymysql://user:pass@host:3306/xstore_monitor?charset=utf8mb4 \
    --dry-run

  python scripts/migrate_sqlite_to_mysql.py \
    --source sqlite:////absolute/path/to/monitor.db \
    --target mysql+pymysql://user:pass@host:3306/xstore_monitor?charset=utf8mb4
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models import Base

BATCH_SIZE = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time SQLite -> MySQL migration")
    parser.add_argument("--source", required=True, help="SQLite URL (sqlite:////path/to/file.db)")
    parser.add_argument("--target", required=True, help="MySQL URL (mysql+pymysql://...)")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Rows per insert batch (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and count rows without writing to target",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Do not clear target tables before inserting",
    )
    return parser.parse_args()


def _validate_urls(source_url: str, target_url: str) -> None:
    if not source_url.startswith("sqlite"):
        raise ValueError("--source must be a sqlite URL")
    if not target_url.startswith("mysql"):
        raise ValueError("--target must be a mysql URL")


def _chunked_rows(rows: Iterator[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _reflect_metadata(source_engine: Engine) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=source_engine)
    return metadata


def _truncate_target(connection: Connection, metadata: MetaData) -> None:
    # Disable FK checks while truncating to avoid ordering issues.
    connection.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    try:
        for table in reversed(metadata.sorted_tables):
            connection.execute(text(f"TRUNCATE TABLE `{table.name}`"))
    finally:
        connection.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def migrate(source_engine: Engine, target_engine: Engine, batch_size: int, dry_run: bool, no_truncate: bool) -> None:
    source_metadata = _reflect_metadata(source_engine)

    if not source_metadata.sorted_tables:
        print("No tables found in source database. Nothing to migrate.")
        return

    # Ensure the destination schema exists before truncation/inserts.
    Base.metadata.create_all(bind=target_engine)
    target_metadata = MetaData()
    target_metadata.reflect(bind=target_engine)

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        if not dry_run and not no_truncate:
            print("Clearing target tables...")
            _truncate_target(target_conn, target_metadata)

        for source_table in source_metadata.sorted_tables:
            target_table = target_metadata.tables.get(source_table.name)
            if target_table is None:
                print(f"Skipping {source_table.name}: table not found in target schema")
                continue

            result = source_conn.execute(select(source_table)).mappings()

            copied = 0
            if dry_run:
                for _ in result:
                    copied += 1
                print(f"[dry-run] {source_table.name}: {copied} rows")
                continue

            for batch in _chunked_rows((dict(row) for row in result), batch_size):
                target_conn.execute(target_table.insert(), batch)
                copied += len(batch)

            print(f"{source_table.name}: copied {copied} rows")


def main() -> int:
    args = parse_args()
    try:
        _validate_urls(args.source, args.target)

        source_engine = create_engine(args.source)
        target_engine = create_engine(args.target)

        migrate(
            source_engine=source_engine,
            target_engine=target_engine,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            no_truncate=args.no_truncate,
        )

        if args.dry_run:
            print("Dry-run completed successfully.")
        else:
            print("Migration completed successfully.")
        return 0
    except (ValueError, SQLAlchemyError) as exc:
        print(f"Migration failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

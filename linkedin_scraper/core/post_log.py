"""Helpers for writing publish events into the NeedleBit SQLite post log."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_LOG_DB = Path(
    os.environ.get(
        "NEEDLEBIT_POST_LOG_DB",
        r"C:\git\needlebit-marketing\core\post_log.sqlite",
    )
)
DEFAULT_LOG_SCHEMA = Path(
    os.environ.get(
        "NEEDLEBIT_POST_LOG_SCHEMA",
        r"C:\git\needlebit-marketing\core\post_log_schema.sql",
    )
)


def resolve_post_log_paths(
    db_path: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Resolve SQLite log paths from explicit args, env vars, or canonical defaults."""
    db = Path(db_path) if db_path else DEFAULT_LOG_DB
    schema = Path(schema_path) if schema_path else DEFAULT_LOG_SCHEMA
    return db, schema


def ensure_post_log(db_path: str | Path, schema_path: str | Path) -> None:
    """Create the SQLite post log and apply schema if needed."""
    db = Path(db_path)
    schema = Path(schema_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    script = schema.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(script)
        conn.commit()
    finally:
        conn.close()


def insert_post_row(
    db_path: str | Path,
    *,
    channel: str,
    target: str,
    topic: str,
    body: str,
    angle: Optional[str] = None,
    title: Optional[str] = None,
    status: str = "posted",
    posted_at: Optional[str] = None,
    external_id: Optional[str] = None,
    external_url: Optional[str] = None,
    source_file: Optional[str] = None,
    notes: Optional[str] = None,
    cooldown_until: Optional[str] = None,
) -> int:
    """Insert one post row and return the created row id."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            """
            INSERT INTO posts (
                channel, target, topic, angle, title, body, status,
                posted_at, external_id, external_url, source_file, notes, cooldown_until
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                channel,
                target,
                topic,
                angle,
                title,
                body,
                status,
                posted_at,
                external_id,
                external_url,
                source_file,
                notes,
                cooldown_until,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def extract_external_id(url: Optional[str]) -> Optional[str]:
    """Best-effort extraction of LinkedIn URN/activity id from a URL."""
    if not url:
        return None
    marker = "/feed/update/"
    if marker not in url:
        return None
    tail = url.split(marker, 1)[1]
    tail = tail.split("?", 1)[0].strip("/")
    return tail or None

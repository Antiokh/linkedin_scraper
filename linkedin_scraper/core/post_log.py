"""Helpers for the NeedleBit source-post plus channel-entity SQLite log."""

from __future__ import annotations

import json
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

ENTITY_COLUMN_MAP = {
    "telegram": "telegram_id",
    "linkedin_company": "linkedin_corp_id",
    "linkedin_personal": "linkedin_personal_id",
    "x": "xcom_id",
    "threads": "threads_id",
}


def resolve_post_log_paths(
    db_path: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Resolve SQLite log paths from explicit args, env vars, or canonical defaults."""
    db = Path(db_path) if db_path else DEFAULT_LOG_DB
    schema = Path(schema_path) if schema_path else DEFAULT_LOG_SCHEMA
    return db, schema


def ensure_post_log(db_path: str | Path, schema_path: str | Path) -> None:
    """Create the SQLite post log, migrating the legacy flat schema when needed."""
    db = Path(db_path)
    schema = Path(schema_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    script = schema.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db))
    try:
        if _is_legacy_schema(conn):
            _migrate_legacy_schema(conn, script)
        else:
            conn.executescript(script)
            conn.commit()
    finally:
        conn.close()


def create_source_post(
    db_path: str | Path,
    *,
    original_text: str,
    content_plan_id: Optional[str] = None,
    notes: Optional[str] = None,
    created_at: Optional[str] = None,
    all_networks_done: bool = False,
) -> int:
    """Insert one source-row and return its id."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            """
            INSERT INTO posts (
                content_plan_id, created_at, original_text, notes, all_networks_done
            ) VALUES (
                ?, COALESCE(?, datetime('now')), ?, ?, ?
            )
            """,
            (
                content_plan_id,
                created_at,
                original_text,
                notes,
                1 if all_networks_done else 0,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def insert_post_entity(
    db_path: str | Path,
    *,
    source_post_id: int,
    entity_type: str,
    content: str,
    post_id: Optional[str] = None,
    post_link: Optional[str] = None,
    posted_date: Optional[str] = None,
    status: str = "posted",
    response_json: Optional[str] = None,
) -> int:
    """Insert a channel-specific entity row and return its id."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            """
            INSERT INTO post_entities (
                source_post_id, type, content, post_id, post_link,
                posted_date, status, response_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_post_id,
                entity_type,
                content,
                post_id,
                post_link,
                posted_date,
                status,
                response_json,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def attach_entity_to_source(
    db_path: str | Path,
    *,
    source_post_id: int,
    entity_id: int,
    entity_type: str,
) -> None:
    """Update the source row pointer for the given channel entity type."""
    column = ENTITY_COLUMN_MAP.get(entity_type)
    if not column:
        return
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"UPDATE posts SET {column} = ? WHERE id = ?",
            (entity_id, source_post_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_all_networks_done(
    db_path: str | Path,
    *,
    source_post_id: int,
    done: bool,
) -> None:
    """Set the completion flag on the source row."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE posts SET all_networks_done = ? WHERE id = ?",
            (1 if done else 0, source_post_id),
        )
        conn.commit()
    finally:
        conn.close()


def insert_source_with_entities(
    db_path: str | Path,
    *,
    original_text: str,
    entities: list[dict],
    content_plan_id: Optional[str] = None,
    notes: Optional[str] = None,
    created_at: Optional[str] = None,
    all_networks_done: bool = False,
) -> int:
    """Create one source row plus all linked entity rows."""
    source_post_id = create_source_post(
        db_path,
        original_text=original_text,
        content_plan_id=content_plan_id,
        notes=notes,
        created_at=created_at,
        all_networks_done=False,
    )
    for entity in entities:
        entity_id = insert_post_entity(
            db_path,
            source_post_id=source_post_id,
            entity_type=entity["entity_type"],
            content=entity["content"],
            post_id=entity.get("post_id"),
            post_link=entity.get("post_link"),
            posted_date=entity.get("posted_date"),
            status=entity.get("status", "posted"),
            response_json=entity.get("response_json"),
        )
        attach_entity_to_source(
            db_path,
            source_post_id=source_post_id,
            entity_id=entity_id,
            entity_type=entity["entity_type"],
        )
    set_all_networks_done(db_path, source_post_id=source_post_id, done=all_networks_done)
    return source_post_id


def infer_entity_type(channel: str, target: Optional[str] = None) -> str:
    """Map legacy channel/target combinations to the new entity type names."""
    channel_norm = (channel or "").strip().lower()
    target_norm = (target or "").strip().lower()
    if channel_norm == "telegram":
        return "telegram"
    if channel_norm == "linkedin":
        if "company" in target_norm or "corp" in target_norm:
            return "linkedin_company"
        return "linkedin_personal"
    if channel_norm in {"x", "xcom", "twitter"}:
        return "x"
    if channel_norm == "threads":
        return "threads"
    return channel_norm


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


def _is_legacy_schema(conn: sqlite3.Connection) -> bool:
    columns = _get_columns(conn, "posts")
    return bool(columns) and "channel" in columns and "original_text" not in columns


def _get_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {row[1] for row in rows}


def _migrate_legacy_schema(conn: sqlite3.Connection, schema_script: str) -> None:
    """Convert the older one-row-per-channel schema into the new source/entity layout."""
    legacy_rows = conn.execute(
        """
        SELECT
            id, channel, target, topic, angle, title, body, status,
            created_at, scheduled_for, posted_at, external_id, external_url,
            source_file, notes, cooldown_until
        FROM posts
        ORDER BY created_at ASC, id ASC
        """
    ).fetchall()

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ALTER TABLE posts RENAME TO posts_legacy")
    conn.executescript(schema_script)

    groups: dict[tuple[str, str], list[sqlite3.Row | tuple]] = {}
    for row in legacy_rows:
        topic = (row[3] or "").strip()
        created_at = (row[8] or "").strip()
        key = (topic, created_at)
        groups.setdefault(key, []).append(row)

    for rows in groups.values():
        preferred_source = _pick_source_row(rows)
        source_notes = _merge_notes(rows)
        created_at = preferred_source[8] or None
        cursor = conn.execute(
            """
            INSERT INTO posts (
                content_plan_id, created_at, original_text, notes, all_networks_done
            ) VALUES (?, COALESCE(?, datetime('now')), ?, ?, ?)
            """,
            (
                None,
                created_at,
                preferred_source[6],
                source_notes,
                0,
            ),
        )
        source_post_id = int(cursor.lastrowid)

        seen_types: set[str] = set()
        for row in rows:
            entity_type = infer_entity_type(row[1], row[2])
            response_json = json.dumps(
                {
                    "legacy_row_id": row[0],
                    "legacy_channel": row[1],
                    "legacy_target": row[2],
                    "legacy_topic": row[3],
                    "legacy_angle": row[4],
                    "legacy_title": row[5],
                    "legacy_source_file": row[13],
                    "legacy_notes": row[14],
                    "legacy_cooldown_until": row[15],
                    "legacy_scheduled_for": row[9],
                },
                ensure_ascii=False,
            )
            entity_cursor = conn.execute(
                """
                INSERT INTO post_entities (
                    source_post_id, type, content, post_id, post_link,
                    posted_date, status, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_post_id,
                    entity_type,
                    row[6],
                    row[11],
                    row[12],
                    row[10],
                    row[7] or "posted",
                    response_json,
                ),
            )
            entity_id = int(entity_cursor.lastrowid)
            column = ENTITY_COLUMN_MAP.get(entity_type)
            if column:
                conn.execute(
                    f"UPDATE posts SET {column} = ? WHERE id = ?",
                    (entity_id, source_post_id),
                )
            seen_types.add(entity_type)

        conn.execute(
            "UPDATE posts SET all_networks_done = ? WHERE id = ?",
            (0, source_post_id),
        )

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _pick_source_row(rows: list[tuple]) -> tuple:
    """Prefer the living human version as the source text for migrated rows."""
    for row in rows:
        if infer_entity_type(row[1], row[2]) == "telegram":
            return row
    for row in rows:
        if infer_entity_type(row[1], row[2]) == "linkedin_personal":
            return row
    return rows[0]


def _merge_notes(rows: list[tuple]) -> Optional[str]:
    notes = []
    for row in rows:
        topic = row[3]
        angle = row[4]
        source_file = row[13]
        raw_note = row[14]
        bits = [bit for bit in [raw_note, f"Legacy topic: {topic}" if topic else None, f"Legacy angle: {angle}" if angle else None, f"Legacy source file: {source_file}" if source_file else None] if bit]
        if bits:
            notes.append(" | ".join(bits))
    if not notes:
        return None
    deduped = list(dict.fromkeys(notes))
    return "\n".join(deduped)

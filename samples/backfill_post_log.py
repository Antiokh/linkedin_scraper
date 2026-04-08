#!/usr/bin/env python3
"""Backfill known publish events into the NeedleBit SQLite post log."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from linkedin_scraper.core.post_log import (
    ensure_post_log,
    extract_external_id,
    insert_post_row,
    resolve_post_log_paths,
)


def main() -> None:
    default_log_db, default_log_schema = resolve_post_log_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=str(default_log_db),
        help="Path to post_log.sqlite. Defaults to the canonical path or NEEDLEBIT_POST_LOG_DB.",
    )
    parser.add_argument(
        "--schema",
        default=str(default_log_schema),
        help="Path to post_log_schema.sql. Defaults to the canonical path or NEEDLEBIT_POST_LOG_SCHEMA.",
    )
    parser.add_argument("--channel", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--angle")
    parser.add_argument("--title")
    parser.add_argument("--status", default="posted")
    parser.add_argument("--posted-at")
    parser.add_argument("--external-url")
    parser.add_argument("--external-id")
    parser.add_argument("--source-file")
    parser.add_argument("--notes")
    parser.add_argument("--cooldown-until")
    args = parser.parse_args()

    log_db, log_schema = resolve_post_log_paths(args.db, args.schema)
    ensure_post_log(log_db, log_schema)
    external_id = args.external_id or extract_external_id(args.external_url)
    row_id = insert_post_row(
        log_db,
        channel=args.channel,
        target=args.target,
        topic=args.topic,
        body=args.body,
        angle=args.angle,
        title=args.title,
        status=args.status,
        posted_at=args.posted_at,
        external_id=external_id,
        external_url=args.external_url,
        source_file=args.source_file,
        notes=args.notes,
        cooldown_until=args.cooldown_until,
    )
    print({"row_id": row_id, "external_id": external_id})


if __name__ == "__main__":
    main()

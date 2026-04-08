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
    insert_source_with_entities,
    infer_entity_type,
    resolve_post_log_paths,
)


def build_source_notes(*parts: str | None) -> str | None:
    values = [part.strip() for part in parts if part and part.strip()]
    if not values:
        return None
    return "\n".join(values)


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
    parser.add_argument("--original-text", help="Original source thought for the source-row. Defaults to --body.")
    parser.add_argument("--content-plan-id")
    parser.add_argument("--angle")
    parser.add_argument("--title")
    parser.add_argument("--status", default="posted")
    parser.add_argument("--posted-at")
    parser.add_argument("--external-url")
    parser.add_argument("--external-id")
    parser.add_argument("--source-file")
    parser.add_argument("--notes")
    parser.add_argument("--cooldown-until")
    parser.add_argument("--all-networks-done", action="store_true")
    args = parser.parse_args()

    log_db, log_schema = resolve_post_log_paths(args.db, args.schema)
    ensure_post_log(log_db, log_schema)
    external_id = args.external_id or extract_external_id(args.external_url)
    entity_type = infer_entity_type(args.channel, args.target)
    row_id = insert_source_with_entities(
        log_db,
        original_text=args.original_text or args.body,
        content_plan_id=args.content_plan_id,
        notes=build_source_notes(
            f"Topic: {args.topic}" if args.topic else None,
            f"Angle: {args.angle}" if args.angle else None,
            f"Title: {args.title}" if args.title else None,
            f"Source file: {args.source_file}" if args.source_file else None,
            f"Cooldown until: {args.cooldown_until}" if args.cooldown_until else None,
            args.notes,
        ),
        created_at=args.posted_at,
        all_networks_done=args.all_networks_done,
        entities=[
            {
                "entity_type": entity_type,
                "content": args.body,
                "post_id": external_id,
                "post_link": args.external_url,
                "posted_date": args.posted_at,
                "status": args.status,
                "response_json": None,
            }
        ],
    )
    print({"source_post_id": row_id, "entity_type": entity_type, "external_id": external_id})


if __name__ == "__main__":
    main()

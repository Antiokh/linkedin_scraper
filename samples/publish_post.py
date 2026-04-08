#!/usr/bin/env python3
"""
Example: Prepare or publish a LinkedIn post as a person or company.

Company posting is reliable through the admin share route. Personal posting
works via UI automation. Native reposts from a personal profile are supported
when you provide the source post URL.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.core.post_log import (
    ensure_post_log,
    extract_external_id,
    insert_post_row,
    resolve_post_log_paths,
)
from linkedin_scraper.scrapers.publisher import PostPublisher


async def main() -> None:
    default_log_db, default_log_schema = resolve_post_log_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--actor", choices=["person", "company", "person-repost"], required=True)
    parser.add_argument("--company-url", help="LinkedIn company URL for company posts")
    parser.add_argument("--source-post-url", help="LinkedIn post URL to native-repost from a personal profile")
    parser.add_argument("--text", required=True, help="Post text")
    parser.add_argument("--topic", help="Topic label for SQLite logging")
    parser.add_argument("--angle", help="Angle/summary for SQLite logging")
    parser.add_argument(
        "--log-db",
        default=str(default_log_db),
        help="Path to NeedleBit post_log.sqlite. Defaults to the canonical path or NEEDLEBIT_POST_LOG_DB.",
    )
    parser.add_argument(
        "--log-schema",
        default=str(default_log_schema),
        help="Path to post_log_schema.sql. Defaults to the canonical path or NEEDLEBIT_POST_LOG_SCHEMA.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Actually click Post. Omit this flag to run in dry-run mode.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless. For debugging personal posting, omit this flag.",
    )
    args = parser.parse_args()

    async with BrowserManager(headless=args.headless) as browser:
        await browser.load_session(args.session)
        publisher = PostPublisher(browser.page)

        if args.actor == "company":
            if not args.company_url:
                raise SystemExit("--company-url is required for --actor company")
            result = await publisher.publish_company_post(
                company_url=args.company_url,
                text=args.text,
                dry_run=not args.publish,
            )
        elif args.actor == "person":
            result = await publisher.publish_person_post(
                text=args.text,
                dry_run=not args.publish,
            )
        else:
            if not args.source_post_url:
                raise SystemExit("--source-post-url is required for --actor person-repost")
            result = await publisher.publish_person_repost(
                source_post_url=args.source_post_url,
                text=args.text,
                dry_run=not args.publish,
            )

        if args.publish:
            target = "company page" if args.actor == "company" else "personal profile"
            default_topic = {
                "company": "LinkedIn company post",
                "person": "LinkedIn personal post",
                "person-repost": "LinkedIn personal repost",
            }[args.actor]
            log_db, log_schema = resolve_post_log_paths(args.log_db, args.log_schema)
            ensure_post_log(log_db, log_schema)
            insert_post_row(
                log_db,
                channel="linkedin",
                target=target,
                topic=args.topic or default_topic,
                angle=args.angle,
                body=args.text,
                status="posted",
                external_id=extract_external_id(result.post_url),
                external_url=result.post_url,
                source_file=__file__,
                notes="Logged by publish_post.py",
            )

        print(result.to_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

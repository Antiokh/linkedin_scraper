#!/usr/bin/env python3
"""
Publish a coordinated LinkedIn pair:
1. Company post in English
2. Native personal repost in Russian with commentary
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
    insert_source_with_entities,
    resolve_post_log_paths,
)
from linkedin_scraper.scrapers.publisher import PostPublisher


def build_source_notes(*parts: str | None) -> str | None:
    values = [part.strip() for part in parts if part and part.strip()]
    if not values:
        return None
    return "\n".join(values)


async def main() -> None:
    default_log_db, default_log_schema = resolve_post_log_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--company-url", required=True, help="LinkedIn company URL or admin share URL")
    parser.add_argument("--company-text", required=True, help="English company post text")
    parser.add_argument("--personal-text", required=True, help="Russian personal repost commentary")
    parser.add_argument("--original-text", help="Original source thought for the shared source-row. Defaults to --personal-text.")
    parser.add_argument("--content-plan-id", help="Optional content plan id for the source-row.")
    parser.add_argument("--topic", help="Shared topic label for SQLite logging")
    parser.add_argument("--company-angle", help="Angle for the company post row")
    parser.add_argument("--personal-angle", help="Angle for the personal repost row")
    parser.add_argument("--notes", help="Optional source-row notes for SQLite logging")
    parser.add_argument(
        "--source-post-url",
        help="Existing company post URL to use for the native repost. Useful in dry-run mode.",
    )
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
        help="Actually publish both posts. Omit this flag to run in dry-run mode.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless. Omit for easier debugging.",
    )
    args = parser.parse_args()

    async with BrowserManager(headless=args.headless) as browser:
        await browser.load_session(args.session)
        publisher = PostPublisher(browser.page)

        company_result = await publisher.publish_company_post(
            company_url=args.company_url,
            text=args.company_text,
            dry_run=not args.publish,
        )

        source_post_url = args.source_post_url or company_result.post_url
        if not source_post_url:
            raise SystemExit(
                "Company post did not produce a usable source post URL. "
                "Pass --source-post-url for dry-run tests."
            )

        personal_result = await publisher.publish_person_repost(
            source_post_url=source_post_url,
            text=args.personal_text,
            dry_run=not args.publish,
        )

        if args.publish:
            log_db, log_schema = resolve_post_log_paths(args.log_db, args.log_schema)
            ensure_post_log(log_db, log_schema)
            insert_source_with_entities(
                log_db,
                original_text=args.original_text or args.personal_text,
                content_plan_id=args.content_plan_id,
                notes=build_source_notes(
                    f"Topic: {args.topic}" if args.topic else None,
                    f"Company angle: {args.company_angle}" if args.company_angle else None,
                    f"Personal angle: {args.personal_angle}" if args.personal_angle else None,
                    args.notes,
                    "Logged by publish_linkedin_pair.py",
                ),
                all_networks_done=True,
                entities=[
                    {
                        "entity_type": "linkedin_company",
                        "content": args.company_text,
                        "post_id": extract_external_id(company_result.post_url),
                        "post_link": company_result.post_url,
                        "status": "posted",
                        "response_json": company_result.to_json(),
                    },
                    {
                        "entity_type": "linkedin_personal",
                        "content": args.personal_text,
                        "post_id": extract_external_id(personal_result.post_url),
                        "post_link": personal_result.post_url,
                        "status": "posted",
                        "response_json": personal_result.to_json(),
                    },
                ],
            )

        print(
            {
                "company": company_result.to_dict(),
                "personal_repost": personal_result.to_dict(),
            }
        )


if __name__ == "__main__":
    asyncio.run(main())

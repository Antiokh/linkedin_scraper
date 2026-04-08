#!/usr/bin/env python3
"""
Publish a coordinated LinkedIn pair:
1. Company post in English
2. Native personal repost in Russian with commentary
"""

import argparse
import asyncio

from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.core.post_log import ensure_post_log, extract_external_id, insert_post_row
from linkedin_scraper.scrapers.publisher import PostPublisher


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--company-url", required=True, help="LinkedIn company URL or admin share URL")
    parser.add_argument("--company-text", required=True, help="English company post text")
    parser.add_argument("--personal-text", required=True, help="Russian personal repost commentary")
    parser.add_argument("--topic", help="Shared topic label for SQLite logging")
    parser.add_argument("--company-angle", help="Angle for the company post row")
    parser.add_argument("--personal-angle", help="Angle for the personal repost row")
    parser.add_argument(
        "--source-post-url",
        help="Existing company post URL to use for the native repost. Useful in dry-run mode.",
    )
    parser.add_argument("--log-db", help="Path to NeedleBit post_log.sqlite")
    parser.add_argument("--log-schema", help="Path to post_log_schema.sql")
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

        if args.log_db and args.log_schema and args.publish:
            ensure_post_log(args.log_db, args.log_schema)
            shared_topic = args.topic or "LinkedIn pair"
            insert_post_row(
                args.log_db,
                channel="linkedin",
                target="company page",
                topic=shared_topic,
                angle=args.company_angle,
                body=args.company_text,
                status="posted",
                external_id=extract_external_id(company_result.post_url),
                external_url=company_result.post_url,
                source_file=__file__,
                notes="Logged by publish_linkedin_pair.py",
            )
            insert_post_row(
                args.log_db,
                channel="linkedin",
                target="personal profile",
                topic=shared_topic,
                angle=args.personal_angle,
                body=args.personal_text,
                status="posted",
                external_id=extract_external_id(personal_result.post_url),
                external_url=personal_result.post_url,
                source_file=__file__,
                notes="Logged by publish_linkedin_pair.py",
            )

        print(
            {
                "company": company_result.to_dict(),
                "personal_repost": personal_result.to_dict(),
            }
        )


if __name__ == "__main__":
    asyncio.run(main())

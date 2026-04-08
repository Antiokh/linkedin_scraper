#!/usr/bin/env python3
"""
Publish a coordinated LinkedIn pair:
1. Company post in English
2. Native personal repost in Russian with commentary
"""

import argparse
import asyncio

from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.scrapers.publisher import PostPublisher


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--company-url", required=True, help="LinkedIn company URL or admin share URL")
    parser.add_argument("--company-text", required=True, help="English company post text")
    parser.add_argument("--personal-text", required=True, help="Russian personal repost commentary")
    parser.add_argument(
        "--source-post-url",
        help="Existing company post URL to use for the native repost. Useful in dry-run mode.",
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

        print(
            {
                "company": company_result.to_dict(),
                "personal_repost": personal_result.to_dict(),
            }
        )


if __name__ == "__main__":
    asyncio.run(main())

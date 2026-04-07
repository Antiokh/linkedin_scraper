#!/usr/bin/env python3
"""
Example: Prepare or publish a LinkedIn post as a person or company.

Company posting is the more reliable path at the moment because LinkedIn exposes
an admin share route directly. Personal posting is implemented as best-effort
UI automation and may fail if LinkedIn changes the feed composer flow.
"""

import argparse
import asyncio

from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.scrapers.publisher import PostPublisher


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--actor", choices=["person", "company"], required=True)
    parser.add_argument("--company-url", help="LinkedIn company URL for company posts")
    parser.add_argument("--text", required=True, help="Post text")
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
        else:
            result = await publisher.publish_person_post(
                text=args.text,
                dry_run=not args.publish,
            )

        print(result.to_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

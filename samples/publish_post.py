#!/usr/bin/env python3
"""
Example: Prepare or publish a LinkedIn post as a person or company.

Company posting is reliable through the admin share route. Personal posting
works via UI automation. Native reposts from a personal profile are supported
when you provide the source post URL.
"""

import argparse
import asyncio

from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.scrapers.publisher import PostPublisher


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--actor", choices=["person", "company", "person-repost"], required=True)
    parser.add_argument("--company-url", help="LinkedIn company URL for company posts")
    parser.add_argument("--source-post-url", help="LinkedIn post URL to native-repost from a personal profile")
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

        print(result.to_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())

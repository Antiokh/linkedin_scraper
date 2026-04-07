#!/usr/bin/env python3
"""
Small headed-browser playground for learning Playwright actions on LinkedIn.

This script is intentionally simple:
1. Opens a visible browser window
2. Navigates to a chosen LinkedIn URL
3. Waits so you can interact manually
4. Optionally saves the current authenticated session
"""

import argparse
import asyncio
from pathlib import Path

from linkedin_scraper import BrowserManager, is_logged_in


async def main() -> None:
    parser = argparse.ArgumentParser(description="Open a visible browser for LinkedIn automation practice")
    parser.add_argument(
        "--url",
        default="https://www.linkedin.com/login",
        help="URL to open in the browser",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=60,
        help="How long to keep the browser open for manual interaction",
    )
    parser.add_argument(
        "--save-session",
        default="",
        help="Save Playwright storage state to this file before exit",
    )
    args = parser.parse_args()

    async with BrowserManager(headless=False, slow_mo=250) as browser:
        await browser.page.goto(args.url, wait_until="domcontentloaded")

        print(f"Opened: {browser.page.url}")
        print(f"Title: {await browser.page.title()}")
        print(f"Waiting {args.wait_seconds} seconds for manual interaction...")

        await asyncio.sleep(args.wait_seconds)

        logged_in = await is_logged_in(browser.page)
        print(f"Logged in: {logged_in}")

        if args.save_session:
            session_path = Path(args.save_session)
            await browser.save_session(str(session_path))
            print(f"Session saved to: {session_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())

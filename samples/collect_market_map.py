#!/usr/bin/env python3
"""
Collect a small LinkedIn market map for hashtag and keyword research.

Outputs:
- leaders.json / leaders.csv
- builders.json / builders.csv

Leaders are collected from hashtag content search.
Builders are collected from people and company search.
"""

import argparse
import asyncio
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from urllib.parse import quote

from linkedin_scraper import BrowserManager, CompanyScraper, is_logged_in


LEADER_TAGS = ["mvp", "bubble", "nocode", "startup"]
LEADER_PEOPLE_QUERIES = [
    "startup founder",
    "startup advisor",
    "bubble founder",
    "bubble expert",
    "no-code founder",
    "nocode consultant",
    "mvp consultant",
]
PEOPLE_QUERIES = [
    "bubble developer",
    "bubble.io developer",
    "no-code developer",
    "nocode developer",
    "mvp developer",
    "startup developer",
]
COMPANY_QUERIES = [
    "bubble agency",
    "bubble.io agency",
    "no-code agency",
    "nocode agency",
    "mvp development",
    "startup studio",
]


def clean_text(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def split_lines(value: str) -> list[str]:
    lines = []
    for raw_line in value.splitlines():
        line = clean_text(raw_line)
        if line:
            lines.append(line)
    return lines


def normalize_linkedin_url(url: str) -> str:
    clean = url.split("?")[0].strip()
    if clean.endswith("/"):
        return clean
    return f"{clean}/"


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def parse_person_result(text: str) -> dict[str, Any]:
    lines = split_lines(text)
    if not lines:
        return {}

    first = lines[0]
    name = clean_text(first.split("•")[0])
    connection_degree = None
    if "•" in first:
        connection_degree = clean_text(first.split("•", 1)[1])

    remaining = lines[1:]
    if remaining and remaining[0].startswith("•"):
        connection_degree = clean_text(remaining[0].replace("•", "", 1))
        remaining = remaining[1:]

    filtered = []
    for line in remaining:
        if line.startswith("•"):
            continue
        filtered.append(line)

    headline = None
    location = None
    extra_lines = []

    for line in filtered:
        lower = line.lower()
        if "mutual connection" in lower:
            continue
        if line in {"Message", "Follow", "Connect", "Pending"}:
            continue
        if headline is None:
            headline = line
            continue
        if location is None and not lower.startswith("past:") and not lower.startswith("present:"):
            location = line
            continue
        extra_lines.append(line)

    return {
        "display_name": name or None,
        "headline": headline,
        "location": location,
        "connection_degree": connection_degree,
        "extra_summary": " | ".join(extra_lines[:3]) if extra_lines else None,
    }


def parse_content_author_result(text: str) -> dict[str, Any]:
    lines = split_lines(text)
    if not lines:
        return {}

    name = clean_text(lines[0].split("•")[0])
    connection_degree = None
    remaining = lines[1:]

    if "•" in lines[0]:
        connection_degree = clean_text(lines[0].split("•", 1)[1])
    elif remaining and remaining[0].startswith("•"):
        connection_degree = clean_text(remaining[0].replace("•", "", 1))
        remaining = remaining[1:]

    headline = None
    post_meta = []
    for line in remaining:
        lower = line.lower()
        if line in {"Follow", "Connect", "Message", "Book an appointment"}:
            post_meta.append(line)
            continue
        if "•" in line or re.search(r"\b(\d+h|\d+d|\d+w)\b", lower):
            post_meta.append(line)
            continue
        if headline is None:
            headline = line
            continue
        post_meta.append(line)

    return {
        "display_name": name or None,
        "headline": headline,
        "connection_degree": connection_degree,
        "post_meta": " | ".join(post_meta[:3]) if post_meta else None,
    }


def is_informative(value: Any) -> bool:
    if not value:
        return False
    if not isinstance(value, str):
        return True
    stripped = clean_text(value)
    if not stripped:
        return False
    if stripped.startswith("•"):
        return False
    return len(stripped) >= 4


def prefer_richer(current: Any, candidate: Any) -> Any:
    if is_informative(candidate) and not is_informative(current):
        return candidate
    if is_informative(candidate) and is_informative(current):
        if isinstance(candidate, str) and isinstance(current, str) and len(candidate) > len(current):
            return candidate
    return current


def prefer_display_name(current: Any, candidate: Any) -> Any:
    if not is_informative(candidate):
        return current
    if not is_informative(current):
        return candidate
    current_text = clean_text(str(current))
    candidate_text = clean_text(str(candidate))
    if "follow this page" in candidate_text.lower():
        return current
    if "follow this page" in current_text.lower():
        return candidate
    if len(candidate_text) < len(current_text):
        return candidate
    return current


def is_relevant_builder_person(text: str) -> bool:
    value = text.lower()
    primary = ["bubble", "bubble.io", "no-code", "nocode", "mvp", "startup"]
    role = ["developer", "builder", "engineer", "founder", "consultant", "agency", "automation"]
    return any(word in value for word in primary) and any(word in value for word in role)


def is_relevant_leader_person(text: str) -> bool:
    value = text.lower()
    primary = ["startup", "bubble", "bubble.io", "no-code", "nocode", "mvp"]
    role = ["founder", "creator", "advisor", "entrepreneur", "consultant", "speaker", "builder", "investor"]
    return any(word in value for word in primary) and any(word in value for word in role)


def is_relevant_builder_company(text: str) -> bool:
    value = text.lower()
    primary = ["bubble", "bubble.io", "no-code", "nocode", "mvp", "startup"]
    role = ["agency", "studio", "development", "developer", "software", "automation", "product"]
    return any(word in value for word in primary) and any(word in value for word in role)


def parse_company_result(text: str) -> dict[str, Any]:
    lines = split_lines(text)
    if not lines:
        return {}

    name = lines[0]
    industry = lines[1] if len(lines) > 1 else None
    location = lines[2] if len(lines) > 2 else None

    description_parts = []
    for line in lines[3:]:
        if line in {"Follow", "Following"}:
            continue
        description_parts.append(line)

    return {
        "display_name": name,
        "industry": industry,
        "location": location,
        "description": " | ".join(description_parts[:4]) if description_parts else None,
    }


def score_leader(item: dict[str, Any]) -> int:
    text = " ".join(
        [
            item.get("display_name") or "",
            item.get("headline") or "",
            item.get("extra_summary") or "",
        ]
    ).lower()
    score = len(item.get("source_tags", [])) * 5 + len(item.get("source_queries", [])) * 3
    for keyword in ["founder", "startup", "creator", "advisor", "bubble", "nocode", "no-code", "mvp"]:
        if keyword in text:
            score += 2
    return score


def score_builder(item: dict[str, Any]) -> int:
    text = " ".join(
        [
            item.get("display_name") or "",
            item.get("headline") or "",
            item.get("industry") or "",
            item.get("description") or "",
        ]
    ).lower()
    score = len(item.get("source_queries", [])) * 5
    for keyword in ["bubble", "bubble.io", "nocode", "no-code", "mvp", "software", "automation", "startup", "agency", "studio"]:
        if keyword in text:
            score += 2
    if item.get("website"):
        score += 2
    return score


async def safe_pause(seconds: float = 1.5) -> None:
    await asyncio.sleep(seconds)


async def goto_with_retry(page, url: str, attempts: int = 3) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return True
        except Exception:
            if attempt == attempts:
                return False
            await safe_pause(2.0 * attempt)
    return False


async def collect_anchor_payloads(page, selector: str) -> list[dict[str, str]]:
    script = """
    els => els.map(a => ({
      href: a.href || '',
      text: (a.innerText || a.textContent || '').trim()
    }))
    """
    anchors = await page.locator(selector).evaluate_all(script)
    results = []
    for item in anchors:
        href = item.get("href", "").strip()
        text = item.get("text", "").strip()
        if not href:
            continue
        if not text:
            continue
        results.append({"href": href, "text": text})
    return results


async def collect_leaders(browser: BrowserManager, per_tag_pages: int, target_count: int) -> list[dict[str, Any]]:
    page = browser.page
    results: dict[str, dict[str, Any]] = {}

    for tag in LEADER_TAGS:
        for page_num in range(1, per_tag_pages + 1):
            url = (
                "https://www.linkedin.com/search/results/content/"
                f"?keywords={quote('#' + tag)}&origin=SWITCH_SEARCH_VERTICAL&page={page_num}"
            )
            if not await goto_with_retry(page, url):
                continue
            try:
                await page.wait_for_selector('a[href*="/in/"]', timeout=20000)
            except Exception:
                continue
            await safe_pause(1.5)

            anchors = await collect_anchor_payloads(page, 'a[href*="/in/"]')
            for anchor in anchors:
                linkedin_url = normalize_linkedin_url(anchor["href"])
                parsed = parse_content_author_result(anchor["text"])
                if not parsed.get("display_name"):
                    continue

                item = results.setdefault(
                    linkedin_url,
                    {
                        "category": "leader",
                        "entity_type": "person",
                        "linkedin_url": linkedin_url,
                        "display_name": parsed.get("display_name"),
                        "headline": parsed.get("headline"),
                        "location": None,
                        "connection_degree": parsed.get("connection_degree"),
                        "extra_summary": parsed.get("post_meta"),
                        "source_tags": [],
                        "source_queries": [],
                    },
                )
                item["display_name"] = prefer_display_name(item.get("display_name"), parsed.get("display_name"))
                item["headline"] = prefer_richer(item.get("headline"), parsed.get("headline"))
                item["connection_degree"] = prefer_richer(item.get("connection_degree"), parsed.get("connection_degree"))
                item["extra_summary"] = prefer_richer(item.get("extra_summary"), parsed.get("post_meta"))
                item["source_tags"] = dedupe_preserve_order(item["source_tags"] + [tag])
                item["source_queries"] = dedupe_preserve_order(item["source_queries"] + [f"#{tag}"])

            if len(results) >= target_count:
                break
        if len(results) >= target_count:
            break

    if len(results) < target_count:
        for query in LEADER_PEOPLE_QUERIES:
            for page_num in range(1, per_tag_pages + 1):
                url = (
                    "https://www.linkedin.com/search/results/people/"
                    f"?keywords={quote(query)}&page={page_num}"
                )
                if not await goto_with_retry(page, url):
                    continue
                try:
                    await page.wait_for_selector('a[href*="/in/"]', timeout=20000)
                except Exception:
                    continue
                await safe_pause(1.0)

                anchors = await collect_anchor_payloads(page, 'a[href*="/in/"]')
                for anchor in anchors:
                    if not is_relevant_leader_person(anchor["text"]):
                        continue
                    linkedin_url = normalize_linkedin_url(anchor["href"])
                    parsed = parse_person_result(anchor["text"])
                    if not parsed.get("display_name"):
                        continue

                    item = results.setdefault(
                        linkedin_url,
                        {
                            "category": "leader",
                            "entity_type": "person",
                            "linkedin_url": linkedin_url,
                            "display_name": parsed.get("display_name"),
                            "headline": parsed.get("headline"),
                            "location": parsed.get("location"),
                            "connection_degree": parsed.get("connection_degree"),
                            "extra_summary": parsed.get("extra_summary"),
                            "source_tags": [],
                            "source_queries": [],
                        },
                    )
                    item["display_name"] = prefer_display_name(item.get("display_name"), parsed.get("display_name"))
                    item["headline"] = prefer_richer(item.get("headline"), parsed.get("headline"))
                    item["location"] = prefer_richer(item.get("location"), parsed.get("location"))
                    item["connection_degree"] = prefer_richer(item.get("connection_degree"), parsed.get("connection_degree"))
                    item["extra_summary"] = prefer_richer(item.get("extra_summary"), parsed.get("extra_summary"))
                    item["source_queries"] = dedupe_preserve_order(item["source_queries"] + [query])

                if len(results) >= target_count:
                    break
            if len(results) >= target_count:
                break

    ranked = sorted(results.values(), key=score_leader, reverse=True)
    return ranked[:target_count]


async def collect_people_builders(browser: BrowserManager, pages_per_query: int) -> list[dict[str, Any]]:
    page = browser.page
    results: dict[str, dict[str, Any]] = {}

    for query in PEOPLE_QUERIES:
        for page_num in range(1, pages_per_query + 1):
            url = (
                "https://www.linkedin.com/search/results/people/"
                f"?keywords={quote(query)}&page={page_num}"
            )
            if not await goto_with_retry(page, url):
                continue
            try:
                await page.wait_for_selector('a[href*="/in/"]', timeout=20000)
            except Exception:
                continue
            await safe_pause(1.0)

            anchors = await collect_anchor_payloads(page, 'a[href*="/in/"]')
            for anchor in anchors:
                if not is_relevant_builder_person(anchor["text"]):
                    continue
                linkedin_url = normalize_linkedin_url(anchor["href"])
                parsed = parse_person_result(anchor["text"])
                if not parsed.get("display_name"):
                    continue

                item = results.setdefault(
                    linkedin_url,
                    {
                        "category": "builder",
                        "entity_type": "person",
                        "linkedin_url": linkedin_url,
                        "display_name": parsed.get("display_name"),
                        "headline": parsed.get("headline"),
                        "location": parsed.get("location"),
                        "connection_degree": parsed.get("connection_degree"),
                        "extra_summary": parsed.get("extra_summary"),
                        "source_queries": [],
                        "source_tags": [],
                        "website": None,
                        "industry": None,
                        "description": None,
                    },
                )
                item["display_name"] = prefer_display_name(item.get("display_name"), parsed.get("display_name"))
                item["headline"] = prefer_richer(item.get("headline"), parsed.get("headline"))
                item["location"] = prefer_richer(item.get("location"), parsed.get("location"))
                item["connection_degree"] = prefer_richer(item.get("connection_degree"), parsed.get("connection_degree"))
                item["extra_summary"] = prefer_richer(item.get("extra_summary"), parsed.get("extra_summary"))
                item["source_queries"] = dedupe_preserve_order(item["source_queries"] + [query])

    return list(results.values())


async def collect_company_builders(browser: BrowserManager, pages_per_query: int) -> list[dict[str, Any]]:
    page = browser.page
    results: dict[str, dict[str, Any]] = {}

    for query in COMPANY_QUERIES:
        for page_num in range(1, pages_per_query + 1):
            url = (
                "https://www.linkedin.com/search/results/companies/"
                f"?keywords={quote(query)}&page={page_num}"
            )
            if not await goto_with_retry(page, url):
                continue
            try:
                await page.wait_for_selector('a[href*="/company/"]', timeout=20000)
            except Exception:
                continue
            await safe_pause(1.0)

            anchors = await collect_anchor_payloads(page, 'a[href*="/company/"]')
            for anchor in anchors:
                if not is_relevant_builder_company(anchor["text"]):
                    continue
                linkedin_url = normalize_linkedin_url(anchor["href"])
                parsed = parse_company_result(anchor["text"])
                if not parsed.get("display_name"):
                    continue

                item = results.setdefault(
                    linkedin_url,
                    {
                        "category": "builder",
                        "entity_type": "company",
                        "linkedin_url": linkedin_url,
                        "display_name": parsed.get("display_name"),
                        "headline": None,
                        "location": parsed.get("location"),
                        "connection_degree": None,
                        "extra_summary": None,
                        "source_queries": [],
                        "source_tags": [],
                        "website": None,
                        "industry": parsed.get("industry"),
                        "description": parsed.get("description"),
                    },
                )
                item["display_name"] = prefer_display_name(item.get("display_name"), parsed.get("display_name"))
                item["location"] = prefer_richer(item.get("location"), parsed.get("location"))
                item["industry"] = prefer_richer(item.get("industry"), parsed.get("industry"))
                item["description"] = prefer_richer(item.get("description"), parsed.get("description"))
                item["source_queries"] = dedupe_preserve_order(item["source_queries"] + [query])

    return list(results.values())


async def enrich_companies(browser: BrowserManager, items: list[dict[str, Any]], max_count: int) -> None:
    scraper = CompanyScraper(browser.page)
    enriched = 0

    for item in items:
        if enriched >= max_count:
            break
        if item.get("entity_type") != "company":
            continue

        try:
            company = await scraper.scrape(item["linkedin_url"])
            item["website"] = company.website
            item["industry"] = item.get("industry") or company.industry
            item["description"] = item.get("description") or company.about_us

            if not item.get("website"):
                about_url = item["linkedin_url"].rstrip("/") + "/about/"
                if not await goto_with_retry(browser.page, about_url):
                    continue
                await browser.page.wait_for_selector('a[href]', timeout=15000)
                links = await collect_anchor_payloads(browser.page, 'a[href]')
                for link in links:
                    href = link["href"]
                    if href.startswith("http") and "linkedin.com" not in href and "bing.com/maps" not in href:
                        item["website"] = href
                        break

            enriched += 1
            await safe_pause(1.0)
        except Exception:
            continue


def flatten_for_csv(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        row = dict(item)
        row["source_tags"] = "; ".join(item.get("source_tags", []))
        row["source_queries"] = "; ".join(item.get("source_queries", []))
        rows.append(row)
    return rows


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Collect LinkedIn leaders and builders into structured files")
    parser.add_argument("--session", default="linkedin_session.json", help="Path to Playwright storage_state JSON")
    parser.add_argument("--leaders-target", type=int, default=100, help="Number of leader profiles to keep")
    parser.add_argument("--builders-target", type=int, default=100, help="Number of builders to keep")
    parser.add_argument("--leader-pages", type=int, default=6, help="Pages per hashtag content search")
    parser.add_argument("--people-pages", type=int, default=4, help="Pages per people query")
    parser.add_argument("--company-pages", type=int, default=4, help="Pages per company query")
    parser.add_argument("--enrich-companies", type=int, default=40, help="How many companies to enrich with websites")
    parser.add_argument("--output-dir", default="data/linkedin_market_map", help="Directory for JSON/CSV outputs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with BrowserManager(headless=True, slow_mo=100) as browser:
        await browser.load_session(args.session)
        if not await goto_with_retry(browser.page, "https://www.linkedin.com/feed/"):
            raise RuntimeError("Could not open LinkedIn feed with current session")
        if not await is_logged_in(browser.page):
            raise RuntimeError("LinkedIn session is not authenticated")

        leaders = await collect_leaders(browser, args.leader_pages, args.leaders_target)

        people_builders = await collect_people_builders(browser, args.people_pages)
        company_builders = await collect_company_builders(browser, args.company_pages)
        builders_map = {item["linkedin_url"]: item for item in people_builders + company_builders}
        builders = sorted(builders_map.values(), key=score_builder, reverse=True)
        builders = builders[: args.builders_target]

        await enrich_companies(browser, builders, args.enrich_companies)
        builders = sorted(builders, key=score_builder, reverse=True)

    metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "leader_tags": LEADER_TAGS,
        "leader_people_queries": LEADER_PEOPLE_QUERIES,
        "people_queries": PEOPLE_QUERIES,
        "company_queries": COMPANY_QUERIES,
        "leaders_count": len(leaders),
        "builders_count": len(builders),
    }

    save_json(output_dir / "metadata.json", metadata)
    save_json(output_dir / "leaders.json", leaders)
    save_json(output_dir / "builders.json", builders)
    save_csv(output_dir / "leaders.csv", flatten_for_csv(leaders))
    save_csv(output_dir / "builders.csv", flatten_for_csv(builders))

    print(json.dumps(metadata, indent=2))
    print(f"Saved outputs to: {output_dir.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())

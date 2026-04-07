#!/usr/bin/env python3
"""
Enrich collected leaders with engagement-based influence signals.
"""

import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from urllib.parse import quote

from linkedin_scraper import BrowserManager, is_logged_in


CONTENT_QUERIES = [
    "#mvp",
    "#bubble",
    "#nocode",
    "#startup",
    "bubble founder",
    "bubble expert",
    "startup founder",
    "startup advisor",
    "no-code founder",
    "mvp consultant",
]


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_linkedin_url(url: str) -> str:
    clean = url.split("?")[0].strip()
    return clean if clean.endswith("/") else f"{clean}/"


def safe_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    text = str(value).replace(",", "").strip()
    if text.isdigit():
        return int(text)
    return 0


def parse_count_from_text(label: str, text: str) -> int:
    text = clean_text(text)
    m = re.search(rf"(\d[\d,]*)\s+{label}", text, re.IGNORECASE)
    if m:
        return safe_int(m.group(1))
    return 0


def parse_reactions_from_text(text: str) -> int:
    text = clean_text(text)
    direct = parse_count_from_text("reactions?", text)
    if direct:
        return direct

    others = re.search(r"and\s+(\d[\d,]*)\s+others\s+reacted", text, re.IGNORECASE)
    if others:
        return safe_int(others.group(1)) + 1
    return 0


def classify_post(text: str) -> list[str]:
    value = text.lower()
    tags = []
    if any(k in value for k in ["how to", "step-by-step", "guide", "tips", "lessons", "framework", "here's how"]):
        tags.append("educational")
    if any(k in value for k in ["i built", "we built", "built a", "launch", "launched", "introducing", "plugin", "tool", "product hunt"]):
        tags.append("build_in_public")
    if any(k in value for k in ["client", "case study", "result", "grew", "increased", "reduced", "our solution"]):
        tags.append("case_study")
    if any(k in value for k in ["message me", "dm me", "book a call", "connect or message", "looking for", "open to", "available for"]):
        tags.append("service_pitch")
    if any(k in value for k in ["bubble", "nocode", "no-code", "automation", "ai", "mvp", "startup"]):
        tags.append("topic_fit")
    if any(k in value for k in ["opinion", "hot take", "i think", "my take", "unpopular"]):
        tags.append("opinion")
    return sorted(set(tags))


def recency_score(posted_date: str | None) -> int:
    if not posted_date:
        return 0
    value = posted_date.lower()
    m = re.search(r"(\d+)\s*([hdwmy])", value)
    if not m:
        return 0
    qty = int(m.group(1))
    unit = m.group(2)
    if unit == "h":
        return max(0, 20 - qty)
    if unit == "d":
        return max(0, 14 - qty)
    if unit == "w":
        return max(0, 8 - qty * 2)
    if unit == "m":
        return max(0, 6 - qty)
    return 0


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
            await safe_pause(2 * attempt)
    return False


async def extract_content_cards(page) -> list[dict[str, Any]]:
    script = """
() => {
  const authorAnchors = Array.from(document.querySelectorAll('main a[href]'));
  const out = [];
  const seen = new Set();

  for (const anchor of authorAnchors) {
    const href = anchor.href || '';
    if (!href.includes('/in/') && !href.includes('/company/')) continue;
    const authorText = (anchor.innerText || anchor.textContent || '').trim();
    if (!authorText || authorText.length < 12) continue;
    const authorName = authorText.split('\\n').map(x => x.trim()).filter(Boolean)[0] || '';

    let node = anchor;
    let chosenText = '';
    for (let i = 0; i < 12 && node; i++) {
      const text = (node.innerText || '').trim();
      const hasCounts = text.includes(' reactions') || text.includes(' reaction') || text.includes(' comments') || text.includes(' reposts') || text.includes('Like\\nComment\\nRepost\\nSend');
      if (text && authorName && text.includes(authorName) && hasCounts) {
        chosenText = text;
        break;
      }
      node = node.parentElement;
    }

    if (!chosenText) continue;
    const feedParts = chosenText.split('Feed post');
    if (feedParts.length > 2) {
      chosenText = 'Feed post' + feedParts[1];
    }

    const key = href.split('?')[0] + '|' + chosenText.slice(0, 200);
    if (seen.has(key)) continue;
    seen.add(key);

    out.push({
      author_url: href,
      author_text: authorText,
      block_text: chosenText.slice(0, 3500)
    });
  }
  return out;
}
"""
    return await page.evaluate(script)


def build_post_record(card: dict[str, Any], query: str) -> dict[str, Any]:
    author_url = normalize_linkedin_url(card["author_url"])
    author_text = clean_text(card["author_text"])
    block_text = clean_text(card["block_text"])

    author_lines = [line.strip() for line in card["author_text"].splitlines() if clean_text(line.strip())]
    author_name = clean_text(author_lines[0]) if author_lines else None
    post_text = block_text
    if "Follow" in post_text:
        post_text = post_text.split("Follow", 1)[1]
    if "Like Comment Repost Send" in post_text:
        post_text = post_text.split("Like Comment Repost Send", 1)[0]
    if author_name and author_name in post_text:
        post_text = post_text.split(author_name, 1)[-1]
    post_text = clean_text(post_text)

    reactions = parse_reactions_from_text(block_text)
    comments = parse_count_from_text("comments?", block_text)
    reposts = parse_count_from_text("reposts?", block_text)

    posted_date = None
    date_match = re.search(r"\b(\d+\s*[hdwmy])\b", block_text, re.IGNORECASE)
    if date_match:
        posted_date = clean_text(date_match.group(1))

    return {
        "author_url": author_url,
        "author_name": author_name,
        "query": query,
        "author_text": author_text,
        "post_text": post_text[:1600],
        "posted_date": posted_date,
        "reactions": reactions,
        "comments": comments,
        "reposts": reposts,
        "engagement": reactions + comments * 2 + reposts * 3,
        "promotion_styles": classify_post(post_text),
    }


async def collect_posts(browser: BrowserManager, pages_per_query: int) -> list[dict[str, Any]]:
    page = browser.page
    posts: list[dict[str, Any]] = []

    for query in CONTENT_QUERIES:
        encoded = quote(query)
        for page_num in range(1, pages_per_query + 1):
            url = f"https://www.linkedin.com/search/results/content/?keywords={encoded}&origin=GLOBAL_SEARCH_HEADER&page={page_num}"
            if not await goto_with_retry(page, url):
                continue
            try:
                await page.wait_for_selector('main a[href*="/in/"], main a[href*="/company/"]', timeout=20000)
            except Exception:
                continue
            await safe_pause(1.5)

            cards = await extract_content_cards(page)
            for card in cards:
                posts.append(build_post_record(card, query))

    return posts


def score_leader(posts: list[dict[str, Any]], source_queries: list[str]) -> dict[str, Any]:
    engagements = [p["engagement"] for p in posts]
    reactions = [p["reactions"] for p in posts]
    comments = [p["comments"] for p in posts]
    reposts = [p["reposts"] for p in posts]
    style_counter = Counter()
    for post in posts:
        style_counter.update(post["promotion_styles"])

    total_engagement = sum(engagements)
    avg_engagement = round(total_engagement / len(posts), 2) if posts else 0
    max_engagement = max(engagements) if engagements else 0
    avg_reactions = round(sum(reactions) / len(posts), 2) if posts else 0
    avg_comments = round(sum(comments) / len(posts), 2) if posts else 0
    avg_reposts = round(sum(reposts) / len(posts), 2) if posts else 0
    recency = sum(recency_score(p.get("posted_date")) for p in posts)
    multi_query_bonus = len(set(source_queries)) * 4
    style_bonus = len(style_counter) * 2
    influence_score = round(total_engagement + max_engagement * 1.5 + recency + multi_query_bonus + style_bonus, 2)

    return {
        "post_mentions": len(posts),
        "queries_seen_in": sorted(set(source_queries)),
        "total_engagement": total_engagement,
        "avg_engagement": avg_engagement,
        "max_engagement": max_engagement,
        "avg_reactions": avg_reactions,
        "avg_comments": avg_comments,
        "avg_reposts": avg_reposts,
        "promotion_styles": [name for name, _ in style_counter.most_common()],
        "style_counts": dict(style_counter),
        "influence_score": influence_score,
    }


def merge_leaders(base_leaders: list[dict[str, Any]], posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    posts_by_author: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        posts_by_author[normalize_linkedin_url(post["author_url"])].append(post)

    enriched = []
    for leader in base_leaders:
        leader_url = normalize_linkedin_url(leader["linkedin_url"])
        author_posts = posts_by_author.get(leader_url, [])
        metrics = score_leader(author_posts, leader.get("source_queries", []))
        item = dict(leader)
        item.update(metrics)
        item["sample_posts"] = sorted(author_posts, key=lambda p: p["engagement"], reverse=True)[:3]
        enriched.append(item)

    ranked = sorted(
        enriched,
        key=lambda x: (
            x.get("influence_score", 0),
            x.get("post_mentions", 0),
            x.get("avg_engagement", 0),
        ),
        reverse=True,
    )
    return ranked


async def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich leaders with engagement-based influence metrics")
    parser.add_argument("--session", default="linkedin_session.json")
    parser.add_argument("--leaders", default="data/linkedin_market_map_core_v2/leaders.json")
    parser.add_argument("--pages-per-query", type=int, default=3)
    parser.add_argument("--output-dir", default="data/linkedin_leader_influence")
    args = parser.parse_args()

    leaders_path = Path(args.leaders)
    leaders = json.loads(leaders_path.read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with BrowserManager(headless=True, slow_mo=80) as browser:
        await browser.load_session(args.session)
        if not await goto_with_retry(browser.page, "https://www.linkedin.com/feed/"):
            raise RuntimeError("Could not open LinkedIn feed")
        if not await is_logged_in(browser.page):
            raise RuntimeError("LinkedIn session is not authenticated")
        posts = await collect_posts(browser, args.pages_per_query)

    enriched = merge_leaders(leaders, posts)
    metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "leaders_source": str(leaders_path.resolve()),
        "content_queries": CONTENT_QUERIES,
        "pages_per_query": args.pages_per_query,
        "raw_posts_collected": len(posts),
        "leaders_enriched": len(enriched),
    }

    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "leader_posts_raw.json").write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "leaders_ranked.json").write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")

    top20 = enriched[:20]
    (output_dir / "leaders_top20.json").write_text(json.dumps(top20, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(metadata, indent=2))
    print(f"Saved outputs to: {output_dir.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())

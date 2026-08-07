"""
╔══════════════════════════════════════════════════════════════════╗
║           Reddit Source — Strategy Implementation                ║
║           Architecture Roadmap · Phase 3 — Asynchronous          ║
║           Processing                                              ║
╚══════════════════════════════════════════════════════════════════╝

Second IContentSource, added specifically to prove ExtractionPipeline's
concurrent, multi-source asyncio.gather() fetching with more than one
real strategy in the registry.

THIS SOURCE IS CURRENTLY SIMULATED, not live — flagged deliberately
rather than silently. Reddit's public *.json endpoints (e.g.
reddit.com/r/technology/top.json) have become unreliable for
unauthenticated access since Reddit's 2023 API policy changes; real
usage now generally needs a registered Reddit app and OAuth2 token.
extract() below returns realistic articles after an artificial delay
that mimics real network latency — enough to make a sequential-vs-
concurrent benchmark against HackerNewsSource genuinely meaningful.
Swap the body of extract() for a real httpx call once you have OAuth
credentials; source_id, the constructor, and everything calling this
class stay identical.
"""

import asyncio
import logging

from core.protocols import Article, IContentSource

logger = logging.getLogger(__name__)


class RedditSource(IContentSource):
    """
    IContentSource strategy for Reddit (currently simulated — see
    module docstring). Structured identically to HackerNewsSource so a
    real implementation later is a drop-in change, not a rewrite.
    """

    _SOURCE_ID: str = "reddit"

    # Simulated articles, standing in for a real r/technology top.json
    # response until OAuth credentials are wired up.
    _SIMULATED_ARTICLES: list[dict] = [
        {"title": "Rust adoption in the Linux kernel crosses 15% of new commits", "link": "https://reddit.com/r/technology/comments/example1", "points": 4821, "comments": 612, "posted_by": "kernel_watcher"},
        {"title": "Show HN alternative: I built a self-hosted Notion in Go", "link": "https://reddit.com/r/technology/comments/example2", "points": 3390, "comments": 445, "posted_by": "gopher_dev"},
        {"title": "EU's new AI liability directive takes effect next quarter", "link": "https://reddit.com/r/technology/comments/example3", "points": 2977, "comments": 891, "posted_by": "policy_nerd"},
        {"title": "Postgres 18 benchmarks show 40% faster vacuum on large tables", "link": "https://reddit.com/r/technology/comments/example4", "points": 2654, "comments": 203, "posted_by": "db_internals"},
        {"title": "WebAssembly GC proposal reaches Stage 4 in all major browsers", "link": "https://reddit.com/r/technology/comments/example5", "points": 2210, "comments": 178, "posted_by": "wasm_fan"},
    ]

    def __init__(self, simulated_latency_seconds: float = 1.8) -> None:
        """
        Args:
            simulated_latency_seconds: Artificial delay standing in for
                real network round-trip time — close to a realistic API
                response time so a sequential-vs-concurrent benchmark
                against HackerNewsSource measures the network model
                honestly, rather than racing the CPU.
        """
        self._simulated_latency = simulated_latency_seconds

    @property
    def source_id(self) -> str:
        return self._SOURCE_ID

    async def extract(self, limit: int = 20) -> list[Article]:
        """
        Returns simulated Reddit articles after an artificial network delay.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            Simulated articles, capped at `limit`.

        Note:
            A real implementation would raise ScrapingError here on
            request failure or empty/unparseable responses, exactly
            like HTTPClient.get() and HackerNewsSource._parse() do —
            omitted here because a hardcoded list has no failure mode
            to simulate honestly.
        """
        logger.info(
            f"[SIMULATED] Fetching r/technology "
            f"(~{self._simulated_latency}s simulated latency)..."
        )
        await asyncio.sleep(self._simulated_latency)

        articles = [
            Article(
                rank=i,
                title=item["title"],
                link=item["link"],
                points=item["points"],
                comments=item["comments"],
                posted_by=item["posted_by"],
            )
            for i, item in enumerate(self._SIMULATED_ARTICLES[:limit], start=1)
        ]

        logger.info(f"[SIMULATED] Returned {len(articles)} article(s) from r/technology.")
        return articles
"""
╔══════════════════════════════════════════════════════════════════╗
║           Hacker News Source — Strategy Implementation           ║
║           Architecture Roadmap · Phase 3 — Asynchronous          ║
║           Processing                                              ║
╚══════════════════════════════════════════════════════════════════╝

Concrete IContentSource implementation for news.ycombinator.com.
extract() is now async, awaiting the network fetch — but HTML parsing
stays fully synchronous, since it's CPU-bound work with no I/O and
gains nothing from being async.
"""

import logging
from typing import Optional

from bs4 import BeautifulSoup, Tag

from core.exceptions import ScrapingError
from core.protocols import Article, IContentSource
from infrastructure.sources.base import HTTPClient

logger = logging.getLogger(__name__)


class HackerNewsSource(IContentSource):
    """
    IContentSource strategy for Hacker News (news.ycombinator.com).

    Hacker News DOM layout (simplified):
        <tr class="athing" id="...">
            <td class="title">
                <span class="titleline"><a href="...">TITLE</a></span>
            </td>
        </tr>
        <tr>  ← sibling row (subtext)
            <td class="subtext">
                <span class="score">NNN points</span>
                <a class="hnuser">AUTHOR</a>
                ...
                <a>NNN comments</a>
            </td>
        </tr>
    """

    _SOURCE_ID: str = "hacker_news"
    _BASE_URL: str = "https://news.ycombinator.com"
    _TARGET_URL: str = "https://news.ycombinator.com/"

    def __init__(self, http_client: Optional[HTTPClient] = None) -> None:
        """
        Args:
            http_client: Optional pre-configured HTTPClient. Defaults to
                        a new instance. Accepting one as a parameter
                        makes this class easy to unit test with a fake
                        client, and lets a caller share one client
                        across multiple sources if desired.
        """
        self._client = http_client or HTTPClient(timeout=15, max_retries=3)
        self._owns_client = http_client is None

    @property
    def source_id(self) -> str:
        return self._SOURCE_ID

    async def extract(self, limit: int = 20) -> list[Article]:
        """
        Fetches the Hacker News front page and parses it into articles.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            Parsed articles in front-page rank order.

        Raises:
            ScrapingError: If the page cannot be fetched, or cannot be
                          parsed into at least one article.
        """
        try:
            html = await self._client.get(self._TARGET_URL)
        finally:
            # Only close a client this instance created itself — an
            # injected client may be shared/reused by its owner.
            if self._owns_client:
                await self._client.close()

        return self._parse(html, limit=limit)

    # ── Private parsing helpers (synchronous — pure CPU-bound work) ──────────

    def _parse(self, html: str, limit: int) -> list[Article]:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            raise ScrapingError(f"BeautifulSoup failed to parse HTML: {exc}") from exc

        article_rows: list[Tag] = soup.select("tr.athing")
        if not article_rows:
            raise ScrapingError(
                "Selector 'tr.athing' matched 0 rows — Hacker News's page "
                "structure may have changed."
            )

        articles: list[Article] = []
        for rank, row in enumerate(article_rows[:limit], start=1):
            try:
                article = self._parse_article_row(rank, row)
                if article is not None:
                    articles.append(article)
            except Exception as exc:
                logger.warning(f"Rank {rank}: Skipped due to unexpected parse error — {exc}")

        if not articles:
            raise ScrapingError(
                f"Parsed 0 usable articles out of {len(article_rows)} rows found."
            )

        logger.info(f"Parsed {len(articles)}/{min(limit, len(article_rows))} articles successfully.")
        return articles

    def _parse_article_row(self, rank: int, row: Tag) -> Optional[Article]:
        title_anchor: Optional[Tag] = row.select_one("span.titleline > a")
        if title_anchor is None:
            logger.debug(f"Rank {rank}: No title anchor found, skipping row.")
            return None

        title: str = title_anchor.get_text(strip=True)
        raw_href: str = title_anchor.get("href", "")
        link: str = (
            f"{self._BASE_URL}/{raw_href}"
            if raw_href.startswith("item?")
            else raw_href
        )

        points: Optional[int] = None
        comments: Optional[int] = None
        posted_by: Optional[str] = None

        subtext_row: Optional[Tag] = row.find_next_sibling("tr")
        if subtext_row:
            subtext: Optional[Tag] = subtext_row.select_one("td.subtext")
            if subtext:
                points = self._extract_points(subtext)
                posted_by = self._extract_author(subtext)
                comments = self._extract_comments(subtext)

        return Article(
            rank=rank,
            title=title,
            link=link,
            points=points,
            comments=comments,
            posted_by=posted_by,
        )

    @staticmethod
    def _extract_points(subtext: Tag) -> Optional[int]:
        score_tag: Optional[Tag] = subtext.select_one("span.score")
        if score_tag:
            try:
                return int(score_tag.get_text(strip=True).split()[0])
            except (ValueError, IndexError) as exc:
                logger.debug(f"Could not parse points: {exc}")
        return None

    @staticmethod
    def _extract_author(subtext: Tag) -> Optional[str]:
        author_tag: Optional[Tag] = subtext.select_one("a.hnuser")
        return author_tag.get_text(strip=True) if author_tag else None

    @staticmethod
    def _extract_comments(subtext: Tag) -> Optional[int]:
        for anchor in reversed(subtext.find_all("a")):
            text: str = anchor.get_text(strip=True).lower()
            if "comment" in text:
                try:
                    return int(text.split()[0])
                except (ValueError, IndexError):
                    return 0
            if text == "discuss":
                return 0
        return None
"""
╔══════════════════════════════════════════════════════════════════╗
║           AI Tech Briefing Engine — Core Protocols                ║
║           Architecture Roadmap · Phase 2 — Strategy Pattern      ║
╚══════════════════════════════════════════════════════════════════╝

Defines the Article data contract and the IContentSource protocol that
every extraction strategy (Hacker News, Reddit, Bloomberg, ...) must
implement.

This module belongs to core/: it defines *what* an extraction strategy
looks like, never *how* any specific one works. Concrete implementations
live in infrastructure/sources/ and import from here — never the other
way around. That is the Dependency Inversion this roadmap phase
introduces: application code (ExtractionPipeline) and infrastructure
code (HackerNewsSource) both depend on this abstraction; neither
depends on the other directly.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class Article:
    """
    Immutable value object representing a single extracted article,
    independent of which source produced it.

    `points`, `comments`, and `posted_by` default to None because not
    every source exposes all three (a Bloomberg RSS item has no upvote
    count; a Hacker News job posting has no comment count). None means
    "not applicable to this source"; 0 means "applicable, and the value
    is zero" — sources should preserve that distinction rather than
    collapsing "not applicable" down to a numeric zero.
    """

    rank: int
    title: str
    link: str
    points: Optional[int] = None
    comments: Optional[int] = None
    posted_by: Optional[str] = None

    def __str__(self) -> str:
        return (
            f"[{self.rank:>2}] {self.title[:60]:<60} | "
            f"{str(self.points):>6} pts | "
            f"{str(self.comments):>4} comments"
        )


@runtime_checkable
class IContentSource(Protocol):
    """
    Contract for any content extraction strategy.

    Every concrete source (HackerNewsSource, and future strategies such
    as a RedditSource or BloombergRSSSource) implements this protocol.
    ExtractionPipeline depends on this abstraction only — it never
    imports a concrete source class — so adding a new source never
    requires modifying the pipeline itself.

    `@runtime_checkable` enables isinstance() checks, which
    SourceRegistry.register() uses to reject any object that does not
    actually satisfy this contract before it ever reaches the pipeline.
    """

    @property
    def source_id(self) -> str:
        """
        Stable, machine-readable identifier for this source.

        Used as the SourceRegistry lookup key, in log messages, and to
        tag exported CSV filenames. Examples: "hacker_news",
        "reddit_programming", "bloomberg_rss". Should be lowercase,
        snake_case, and never change once a source ships, since it may
        end up embedded in saved filenames.
        """
        ...

    def extract(self, limit: int = 20) -> list[Article]:
        """
        Fetches and parses articles from this source.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            Parsed articles, ordered by the source's own ranking. May
            return fewer than `limit` items if the source has fewer
            available.

        Raises:
            ScrapingError: If the source cannot be reached (network,
                          timeout, non-2xx HTTP status) or if its
                          response cannot be parsed into Article objects.
        """
        ...
"""
╔══════════════════════════════════════════════════════════════════╗
║           AI Tech Briefing Engine — Core Protocols                ║
║           Architecture Roadmap · Phase 3 — Asynchronous           ║
║           Processing                                              ║
╚══════════════════════════════════════════════════════════════════╝

Defines the Article data contract and the IContentSource protocol.
extract() is now a coroutine so ExtractionPipeline can fetch every
registered source concurrently via asyncio.gather() instead of
sequentially, one at a time.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class Article:
    """
    Immutable value object representing a single extracted article,
    independent of which source produced it.

    `source_id` is set by ExtractionPipeline after extraction (not by
    the source itself) — see smart_data_extractor.py — so that once
    multiple sources' results are merged into one list, each row still
    records which source it came from. `points`, `comments`, and
    `posted_by` default to None because not every source exposes all
    three; None means "not applicable to this source," 0 means
    "applicable, and the value is zero."
    """

    rank: int
    title: str
    link: str
    points: Optional[int] = None
    comments: Optional[int] = None
    posted_by: Optional[str] = None
    source_id: Optional[str] = None

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

    extract() is a coroutine: ExtractionPipeline awaits every registered
    source concurrently via asyncio.gather(), so a slow or high-latency
    source never adds to the others' wait time. @runtime_checkable still
    works correctly here — Protocol's isinstance() check is a structural
    "does this attribute/method exist by name" check, not a signature or
    sync/async inspection, so SourceRegistry.register()'s isinstance()
    guard needs no changes for this to keep working.
    """

    @property
    def source_id(self) -> str:
        """
        Stable, machine-readable identifier for this source.

        Used as the SourceRegistry lookup key, in log messages, and
        stamped onto every Article this source produces once merged by
        the pipeline. Should be lowercase, snake_case, and never change
        once a source ships.
        """
        ...

    async def extract(self, limit: int = 20) -> list[Article]:
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
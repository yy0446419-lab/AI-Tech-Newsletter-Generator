"""
╔══════════════════════════════════════════════════════════════════╗
║           Smart Data Extractor — Phase 1                        ║
║           Target: Hacker News (news.ycombinator.com)            ║
║           Extracts: Top 20 articles (Title, Link, Points,       ║
║                     Comments, Author)                           ║
╚══════════════════════════════════════════════════════════════════╝
"""

import csv
import logging
import sys
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

# ─────────────────────────────────────────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("extractor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Article:
    """Immutable value object representing a single scraped article."""

    rank: int
    title: str
    link: str
    points: Optional[int]
    comments: Optional[int]
    posted_by: Optional[str]

    def __str__(self) -> str:
        return (
            f"[{self.rank:>2}] {self.title[:60]:<60} | "
            f"{str(self.points):>6} pts | "
            f"{str(self.comments):>4} comments"
        )


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Client
# ─────────────────────────────────────────────────────────────────────────────
class HTTPClient:
    """
    Manages a persistent requests.Session with retry logic,
    custom headers, and configurable timeouts.
    """

    _DEFAULT_HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    def __init__(self, timeout: int = 15, max_retries: int = 3) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(self._DEFAULT_HEADERS)

    def get(self, url: str) -> str:
        """
        Performs a GET request with retry logic.

        Args:
            url: The target URL to fetch.

        Returns:
            The raw HTML content as a string.

        Raises:
            RuntimeError: If all retry attempts are exhausted.
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(f"GET {url!r}  (attempt {attempt}/{self._max_retries})")
                response = self._session.get(url, timeout=self._timeout)
                response.raise_for_status()
                logger.info(
                    f"Response: HTTP {response.status_code} | "
                    f"{len(response.content) / 1024:.1f} KB"
                )
                return response.text

            except requests.exceptions.Timeout:
                logger.warning(f"Attempt {attempt}: Request timed out after {self._timeout}s.")
            except requests.exceptions.ConnectionError as exc:
                logger.warning(f"Attempt {attempt}: Connection error — {exc}")
            except requests.exceptions.HTTPError as exc:
                logger.error(f"HTTP error (non-retryable): {exc}")
                raise RuntimeError(f"HTTP error fetching {url!r}: {exc}") from exc
            except requests.exceptions.RequestException as exc:
                logger.error(f"Unexpected request exception: {exc}")
                raise RuntimeError(f"Request failed for {url!r}: {exc}") from exc

        raise RuntimeError(
            f"All {self._max_retries} attempts failed for URL: {url!r}"
        )

    def close(self) -> None:
        """Closes the underlying HTTP session and releases resources."""
        self._session.close()
        logger.debug("HTTP session closed.")

    # Context manager support
    def __enter__(self) -> "HTTPClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
# HTML Parser
# ─────────────────────────────────────────────────────────────────────────────
class HackerNewsParser:
    """
    Parses Hacker News HTML into a list of Article objects.

    Hacker News DOM layout (simplified):
        <tr class="athing" id="...">
            <td class="title">
                <span class="titleline">
                    <a href="...">TITLE</a>
                </span>
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

    _BASE_URL: str = "https://news.ycombinator.com"

    def parse(self, html: str, limit: int = 20) -> list[Article]:
        """
        Parses raw HTML and returns a list of scraped Article objects.

        Args:
            html:  Raw HTML string from the target page.
            limit: Maximum number of articles to return.

        Returns:
            A list of Article dataclass instances.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            raise ValueError(f"BeautifulSoup failed to parse HTML: {exc}") from exc

        article_rows: list[Tag] = soup.select("tr.athing")
        if not article_rows:
            logger.warning("Selector 'tr.athing' matched 0 rows — page structure may have changed.")

        articles: list[Article] = []

        for rank, row in enumerate(article_rows[:limit], start=1):
            try:
                article = self._parse_article_row(rank, row)
                if article is not None:
                    articles.append(article)
            except Exception as exc:
                logger.warning(f"Rank {rank}: Skipped due to unexpected parse error — {exc}")

        logger.info(f"Parsed {len(articles)}/{min(limit, len(article_rows))} articles successfully.")
        return articles

    def _parse_article_row(self, rank: int, row: Tag) -> Optional[Article]:
        """
        Extracts all fields from a single article row + its subtext sibling.

        Args:
            rank: 1-based article position.
            row:  The <tr class="athing"> Tag object.

        Returns:
            An Article dataclass, or None if the title tag is absent.
        """
        # ── Title & Link ──────────────────────────────────────────────────────
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

        # ── Subtext Row ───────────────────────────────────────────────────────
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
        """Parses 'NNN points' from the score span."""
        score_tag: Optional[Tag] = subtext.select_one("span.score")
        if score_tag:
            try:
                return int(score_tag.get_text(strip=True).split()[0])
            except (ValueError, IndexError) as exc:
                logger.debug(f"Could not parse points: {exc}")
        return None

    @staticmethod
    def _extract_author(subtext: Tag) -> Optional[str]:
        """Parses the submitting username from the hnuser link."""
        author_tag: Optional[Tag] = subtext.select_one("a.hnuser")
        return author_tag.get_text(strip=True) if author_tag else None

    @staticmethod
    def _extract_comments(subtext: Tag) -> Optional[int]:
        """
        Parses comment count from the last anchor in subtext.
        Handles 'NNN comments', '1 comment', and 'discuss' (= 0 comments).
        """
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


# ─────────────────────────────────────────────────────────────────────────────
# CSV Exporter
# ─────────────────────────────────────────────────────────────────────────────
class CSVExporter:
    """
    Serialises a list of Article objects into a UTF-8 CSV file
    with a timestamped filename inside a configurable output directory.
    """

    _FILENAME_TEMPLATE: str = "hacker_news_{timestamp}.csv"

    def __init__(self, output_dir: str = "output") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, articles: list[Article]) -> Path:
        """
        Writes articles to a CSV file.

        Args:
            articles: Non-empty list of Article objects to serialise.

        Returns:
            The resolved Path of the created CSV file.

        Raises:
            ValueError: If the articles list is empty.
            IOError:    If the file cannot be written.
        """
        if not articles:
            raise ValueError("Cannot export: the articles list is empty.")

        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath: Path = self._output_dir / self._FILENAME_TEMPLATE.format(
            timestamp=timestamp
        )
        column_names: list[str] = [f.name for f in fields(Article)]

        try:
            with filepath.open(mode="w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=column_names,
                    extrasaction="ignore",
                )
                writer.writeheader()
                for article in articles:
                    writer.writerow(
                        {col: getattr(article, col) for col in column_names}
                    )

            logger.info(f"CSV exported → {filepath.resolve()}")
            return filepath

        except IOError as exc:
            logger.error(f"Failed to write CSV: {exc}")
            raise


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator  (Facade / Pipeline Controller)
# ─────────────────────────────────────────────────────────────────────────────
class SmartDataExtractor:
    """
    Top-level orchestrator that wires together the three pipeline stages:

        Stage 1 │ HTTPClient       — Fetch raw HTML
        Stage 2 │ HackerNewsParser — Parse HTML → Article objects
        Stage 3 │ CSVExporter      — Serialise → CSV file
    """

    _TARGET_URL: str = "https://news.ycombinator.com/"
    _ARTICLE_LIMIT: int = 20

    def __init__(self, output_dir: str = "output") -> None:
        self._client = HTTPClient(timeout=15, max_retries=3)
        self._parser = HackerNewsParser()
        self._exporter = CSVExporter(output_dir=output_dir)

    # ── Public API ────────────────────────────────────────────────────────────
    def run(self) -> None:
        """Executes the full ETL pipeline: Extract → Transform → Load (CSV)."""
        self._print_banner()

        try:
            # Stage 1 — Fetch
            html: str = self._client.get(self._TARGET_URL)

            # Stage 2 — Parse
            articles: list[Article] = self._parser.parse(html, limit=self._ARTICLE_LIMIT)
            if not articles:
                logger.warning("No articles parsed. The site structure may have changed.")
                sys.exit(1)

            # Stage 3 — Preview + Export
            self._preview(articles)
            output_path: Path = self._exporter.export(articles)

            logger.info("─" * 66)
            logger.info(
                f"  ✔  Pipeline complete — {len(articles)} articles "
                f"saved to: {output_path.name}"
            )
            logger.info("─" * 66)

        except RuntimeError as exc:
            logger.critical(f"Pipeline aborted (network failure): {exc}")
            sys.exit(1)
        except ValueError as exc:
            logger.critical(f"Pipeline aborted (data error): {exc}")
            sys.exit(1)
        except KeyboardInterrupt:
            logger.warning("Interrupted by user.")
            sys.exit(0)
        except Exception as exc:
            logger.critical(f"Pipeline aborted (unexpected): {exc}", exc_info=True)
            sys.exit(1)
        finally:
            self._client.close()

    # ── Private Helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _print_banner() -> None:
        logger.info("═" * 66)
        logger.info("  Smart Data Extractor — Phase 1 │ Hacker News")
        logger.info("═" * 66)

    @staticmethod
    def _preview(articles: list[Article]) -> None:
        """Prints a formatted table of scraped articles to stdout."""
        separator = "─" * 66
        print(f"\n{separator}")
        print(f"  {'RK':>2}  {'TITLE':<45}  {'PTS':>6}  {'CMT':>5}")
        print(separator)
        for article in articles:
            pts = str(article.points) if article.points is not None else "N/A"
            cmt = str(article.comments) if article.comments is not None else "N/A"
            print(
                f"  {article.rank:>2}  {article.title[:45]:<45}  "
                f"{pts:>6}  {cmt:>5}"
            )
        print(f"{separator}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    extractor = SmartDataExtractor(output_dir="output")
    extractor.run()

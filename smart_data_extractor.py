"""
╔══════════════════════════════════════════════════════════════════╗
║           Extraction Pipeline — Asynchronous, Multi-Source        ║
║           Architecture Roadmap · Phase 3 — Asynchronous           ║
║           Processing                                              ║
║                                                                    ║
║           Concurrently fetches every registered IContentSource    ║
║           via asyncio.gather(), merges the results (tagging each ║
║           Article with its source_id for provenance), and        ║
║           exports the combined set to a single CSV. A source     ║
║           that fails does not take down the others — the         ║
║           pipeline only fails if every source fails.             ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import csv
import dataclasses
import logging
import sys
from datetime import datetime
from pathlib import Path

from core.exceptions import BriefingEngineError, RepositoryError, ScrapingError
from core.protocols import Article, IContentSource
from infrastructure.sources.hacker_news import HackerNewsSource
from infrastructure.sources.reddit import RedditSource
from infrastructure.sources.registry import SourceRegistry

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
# Source Registration
# ─────────────────────────────────────────────────────────────────────────────
# Every available IContentSource strategy is registered here, once, at
# import time. Adding a third source means one new file in
# infrastructure/sources/ and one new line here — ExtractionPipeline
# below never changes.
SourceRegistry.register(HackerNewsSource())
SourceRegistry.register(RedditSource())


# ─────────────────────────────────────────────────────────────────────────────
# CSV Exporter
# ─────────────────────────────────────────────────────────────────────────────
class CSVExporter:
    """
    Serialises a merged, multi-source list of Article objects into a
    single UTF-8 CSV file. Each row's `source_id` column preserves
    which source it came from.
    """

    _FILENAME_TEMPLATE: str = "briefing_articles_{timestamp}.csv"

    def __init__(self, output_dir: str = "output") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, articles: list[Article]) -> Path:
        """
        Writes articles to a CSV file.

        Args:
            articles: Non-empty list of Article objects, typically
                     merged from multiple sources.

        Returns:
            The resolved Path of the created CSV file.

        Raises:
            ValueError:      If the articles list is empty (caller
                             contract violation — unreachable in the
                             current pipeline).
            RepositoryError: If the file cannot be written.
        """
        if not articles:
            raise ValueError("Cannot export: the articles list is empty.")

        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath: Path = self._output_dir / self._FILENAME_TEMPLATE.format(
            timestamp=timestamp
        )
        column_names: list[str] = [f.name for f in dataclasses.fields(Article)]

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
            raise RepositoryError(f"Failed to write CSV to '{filepath}': {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Pipeline  (Strategy Context — concurrent, multi-source)
# ─────────────────────────────────────────────────────────────────────────────
class ExtractionPipeline:
    """
    Concurrently fetches every registered IContentSource, merges the
    results, and exports them to a single CSV.

        Stage 1 │ SourceRegistry.available_ids() — discover all sources
        Stage 2 │ asyncio.gather(*extract calls)  — fetch concurrently
        Stage 3 │ merge + tag with source_id       — preserve provenance
        Stage 4 │ CSVExporter.export(merged)        — persist to CSV

    A single failing source does not fail the whole run — partial
    results from the sources that succeeded are still exported. The
    pipeline only raises if every registered source fails. Never calls
    sys.exit(); every failure raises a typed exception from
    core.exceptions and the caller decides what to do with it.
    """

    _ARTICLE_LIMIT: int = 20

    def __init__(self, output_dir: str = "output") -> None:
        self._output_dir = output_dir

    async def run(self) -> None:
        """
        Executes the full pipeline: fetch every source concurrently →
        merge → export.

        Raises:
            ScrapingError:        No sources are registered, or every
                                  registered source failed to extract.
            RepositoryError:      The CSV file cannot be written.
            BriefingEngineError:  Wraps any other unexpected failure.
        """
        source_ids = SourceRegistry.available_ids()
        self._print_banner(source_ids)

        try:
            if not source_ids:
                raise ScrapingError("No content sources are registered.")

            sources = [SourceRegistry.get(sid) for sid in source_ids]

            results = await asyncio.gather(
                *(self._extract_from_source(s) for s in sources),
                return_exceptions=True,
            )

            all_articles: list[Article] = []
            failures: list[tuple[str, BaseException]] = []

            for source, result in zip(sources, results):
                if isinstance(result, BaseException):
                    failures.append((source.source_id, result))
                    logger.warning(f"Source '{source.source_id}' failed: {result}")
                else:
                    all_articles.extend(result)
                    logger.info(f"Source '{source.source_id}': {len(result)} article(s).")

            if not all_articles:
                raise ScrapingError(
                    f"All {len(sources)} registered source(s) failed. "
                    f"Failures: {[(sid, str(exc)) for sid, exc in failures]}"
                )

            if failures:
                logger.warning(
                    f"{len(failures)}/{len(sources)} source(s) failed; "
                    f"proceeding with {len(all_articles)} articles from the "
                    f"{len(sources) - len(failures)} source(s) that succeeded."
                )

            self._preview(all_articles)
            output_path = CSVExporter(output_dir=self._output_dir).export(all_articles)

            logger.info("─" * 66)
            logger.info(
                f"  ✔  Pipeline complete — {len(all_articles)} articles "
                f"from {len(sources) - len(failures)}/{len(sources)} source(s) "
                f"saved to: {output_path.name}"
            )
            logger.info("─" * 66)

        except ScrapingError as exc:
            logger.critical(f"[SCRAPING ERROR] {exc}")
            raise
        except RepositoryError as exc:
            logger.critical(f"[DATA ERROR] {exc}")
            raise
        except KeyboardInterrupt:
            logger.warning("Pipeline interrupted by user.")
            raise
        except Exception as exc:
            logger.critical(f"[UNEXPECTED ERROR] {exc}", exc_info=True)
            raise BriefingEngineError(
                f"Unexpected extraction pipeline failure: {exc}"
            ) from exc

    # ── Private Helpers ───────────────────────────────────────────────────────
    async def _extract_from_source(self, source: IContentSource) -> list[Article]:
        """
        Extracts from a single source and tags each returned Article with
        that source's source_id, so the merged CSV preserves per-row
        provenance without requiring every source implementation to set
        this field itself.
        """
        articles = await source.extract(limit=self._ARTICLE_LIMIT)
        return [dataclasses.replace(a, source_id=source.source_id) for a in articles]

    @staticmethod
    def _print_banner(source_ids: list[str]) -> None:
        logger.info("═" * 66)
        logger.info("  Extraction Pipeline │ Concurrent Multi-Source Fetch")
        logger.info(f"  Sources: {', '.join(source_ids) or '(none registered)'}")
        logger.info("═" * 66)

    @staticmethod
    def _preview(articles: list[Article]) -> None:
        """Prints a formatted table of extracted articles to stdout."""
        separator = "─" * 66
        print(f"\n{separator}")
        print(f"  {'RK':>2}  {'SOURCE':<12}  {'TITLE':<38}  {'PTS':>6}")
        print(separator)
        for article in articles:
            pts = str(article.points) if article.points is not None else "N/A"
            src = (article.source_id or "?")[:12]
            print(
                f"  {article.rank:>2}  {src:<12}  {article.title[:38]:<38}  {pts:>6}"
            )
        print(f"{separator}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(ExtractionPipeline(output_dir="output").run())
    except BriefingEngineError as exc:
        logger.critical(f"Pipeline terminated: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)
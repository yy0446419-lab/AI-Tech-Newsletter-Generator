"""
╔══════════════════════════════════════════════════════════════════╗
║           Extraction Pipeline                                     ║
║           Architecture Roadmap · Phase 2 — Strategy Pattern      ║
║                                                                    ║
║           Generic orchestrator: resolves a content source by     ║
║           source_id from SourceRegistry, extracts articles, and  ║
║           exports them to CSV. Adding a new source never         ║
║           requires modifying this file — see the registration    ║
║           block below.                                           ║
╚══════════════════════════════════════════════════════════════════╝
"""

import csv
import logging
import sys
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from core.exceptions import BriefingEngineError, RepositoryError, ScrapingError
from core.protocols import Article, IContentSource
from infrastructure.sources.hacker_news import HackerNewsSource
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
# import time — both the CLI entry point below and any external caller
# (e.g. app.py) that imports this module get a fully populated registry.
# Adding Reddit or Bloomberg later means one new file in
# infrastructure/sources/ and one new line here. Nothing else changes.
SourceRegistry.register(HackerNewsSource())


# ─────────────────────────────────────────────────────────────────────────────
# CSV Exporter
# ─────────────────────────────────────────────────────────────────────────────
class CSVExporter:
    """
    Serialises a list of Article objects into a UTF-8 CSV file, with a
    filename tagged by source and timestamp, inside a configurable
    output directory.
    """

    _FILENAME_TEMPLATE: str = "{source_id}_{timestamp}.csv"

    def __init__(self, output_dir: str = "output") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, articles: list[Article], source_id: str) -> Path:
        """
        Writes articles to a CSV file.

        Args:
            articles:  Non-empty list of Article objects to serialise.
            source_id: The source_id these articles came from — embedded
                      in the filename so multiple sources' exports never
                      collide and stay identifiable at a glance.

        Returns:
            The resolved Path of the created CSV file.

        Raises:
            ValueError:      If the articles list is empty (caller
                             contract violation — unreachable in the
                             current pipeline, since ExtractionPipeline
                             raises ScrapingError before an empty list
                             could reach this method).
            RepositoryError: If the file cannot be written.
        """
        if not articles:
            raise ValueError("Cannot export: the articles list is empty.")

        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath: Path = self._output_dir / self._FILENAME_TEMPLATE.format(
            source_id=source_id, timestamp=timestamp
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
            raise RepositoryError(f"Failed to write CSV to '{filepath}': {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Pipeline  (Strategy Context)
# ─────────────────────────────────────────────────────────────────────────────
class ExtractionPipeline:
    """
    Generic orchestrator for any registered IContentSource strategy.

        Stage 1 │ SourceRegistry.get(source_id) — resolve the strategy
        Stage 2 │ source.extract(limit)         — fetch + parse articles
        Stage 3 │ CSVExporter.export(articles)   — persist to CSV

    This class has no knowledge of Hacker News, Reddit, or any other
    specific source — that is the entire point of the Strategy pattern.
    It depends only on the IContentSource abstraction and the registry
    that resolves concrete implementations by string ID. Never calls
    sys.exit(); every failure raises a typed exception from
    core.exceptions and the caller decides what to do with it.
    """

    _ARTICLE_LIMIT: int = 20

    def __init__(self, source_id: str, output_dir: str = "output") -> None:
        self._source_id = source_id
        self._output_dir = output_dir

    def run(self) -> None:
        """
        Executes the full pipeline: resolve source → extract → export.

        Raises:
            ScrapingError:        source_id is not registered, or the
                                  source's extract() call fails.
            RepositoryError:      The CSV file cannot be written.
            BriefingEngineError:  Wraps any other unexpected failure.
        """
        self._print_banner()

        try:
            source: IContentSource = SourceRegistry.get(self._source_id)
            articles = source.extract(limit=self._ARTICLE_LIMIT)

            if not articles:
                raise ScrapingError(
                    f"Source '{self._source_id}' returned zero articles."
                )

            self._preview(articles)
            output_path = CSVExporter(output_dir=self._output_dir).export(
                articles, source_id=self._source_id
            )

            logger.info("─" * 66)
            logger.info(
                f"  ✔  Pipeline complete — {len(articles)} articles "
                f"from '{self._source_id}' saved to: {output_path.name}"
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
    def _print_banner(self) -> None:
        logger.info("═" * 66)
        logger.info(f"  Extraction Pipeline │ Source: {self._source_id!r}")
        logger.info(f"  Registered sources: {', '.join(SourceRegistry.available_ids())}")
        logger.info("═" * 66)

    @staticmethod
    def _preview(articles: list[Article]) -> None:
        """Prints a formatted table of extracted articles to stdout."""
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
    try:
        ExtractionPipeline(source_id="hacker_news", output_dir="output").run()
    except BriefingEngineError as exc:
        logger.critical(f"Pipeline terminated: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)
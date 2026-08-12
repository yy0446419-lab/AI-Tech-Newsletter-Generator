"""
Core pipeline tests.

Covers the two orchestrators end to end:
  - ExtractionPipeline    (smart_data_extractor.py) — async, multi-source
  - AINewsletterGenerator (ai_newsletter.py)         — sync, calls Gemini

Every external boundary is mocked: IContentSource implementations are
FakeContentSource test doubles (no real HTTP), and the Gemini SDK client
is mocked via the mock_gemini_client fixture (no real API calls). Real
temp files (via tmp_path) stand in for the CSV/.env/output filesystem.
"""

import time

import pytest

from ai_newsletter import AINewsletterGenerator
from core.exceptions import (
    ConfigurationError,
    LLMQuotaExceededError,
    LLMServiceUnavailableError,
    RepositoryError,
    ScrapingError,
)
from core.protocols import Article
from infrastructure.sources.registry import SourceRegistry
from google.genai import errors as genai_errors
from smart_data_extractor import ExtractionPipeline

from .conftest import make_gemini_response


# ─────────────────────────────────────────────────────────────────────────
# ExtractionPipeline
# ─────────────────────────────────────────────────────────────────────────

async def test_extraction_pipeline_merges_all_sources(tmp_path, make_fake_source, make_article):
    """All sources succeed → their articles are merged and each is tagged with its source_id."""
    SourceRegistry.register(
        make_fake_source("source_a", articles=[make_article(rank=1), make_article(rank=2)])
    )
    SourceRegistry.register(
        make_fake_source("source_b", articles=[make_article(rank=1)])
    )

    await ExtractionPipeline(output_dir=str(tmp_path)).run()

    csv_files = list(tmp_path.glob("*.csv"))
    assert len(csv_files) == 1

    content = csv_files[0].read_text(encoding="utf-8")
    assert content.count("\n") - 1 == 3  # header + 3 article rows
    assert "source_a" in content
    assert "source_b" in content


async def test_extraction_pipeline_tolerates_partial_failure(tmp_path, make_fake_source, make_article):
    """One source fails, one succeeds → no exception; CSV has just the successful source's articles."""
    SourceRegistry.register(
        make_fake_source("flaky_source", error=ScrapingError("simulated network failure"))
    )
    SourceRegistry.register(
        make_fake_source("reliable_source", articles=[make_article(rank=1)])
    )

    await ExtractionPipeline(output_dir=str(tmp_path)).run()  # must not raise

    csv_files = list(tmp_path.glob("*.csv"))
    content = csv_files[0].read_text(encoding="utf-8")
    assert "reliable_source" in content
    assert "flaky_source" not in content


async def test_extraction_pipeline_raises_when_every_source_fails(tmp_path, make_fake_source):
    SourceRegistry.register(make_fake_source("a", error=ScrapingError("down")))
    SourceRegistry.register(make_fake_source("b", error=ScrapingError("also down")))

    with pytest.raises(ScrapingError, match="All 2 registered source"):
        await ExtractionPipeline(output_dir=str(tmp_path)).run()

    assert list(tmp_path.glob("*.csv")) == []


async def test_extraction_pipeline_raises_when_no_sources_registered(tmp_path):
    with pytest.raises(ScrapingError, match="No content sources are registered"):
        await ExtractionPipeline(output_dir=str(tmp_path)).run()


async def test_extraction_pipeline_fetches_concurrently(tmp_path, make_fake_source, make_article):
    """
    Two sources that each take ~0.3s should complete in ~0.3s total, not
    ~0.6s — proving asyncio.gather() actually runs them concurrently
    rather than ExtractionPipeline silently awaiting them one at a time.
    """
    delay = 0.3
    SourceRegistry.register(make_fake_source("slow_a", articles=[make_article()], delay=delay))
    SourceRegistry.register(make_fake_source("slow_b", articles=[make_article()], delay=delay))

    start = time.perf_counter()
    await ExtractionPipeline(output_dir=str(tmp_path)).run()
    elapsed = time.perf_counter() - start

    assert elapsed < delay * 1.8, (
        f"Took {elapsed:.2f}s for two {delay}s sources — looks sequential, not concurrent."
    )


# ─────────────────────────────────────────────────────────────────────────
# AINewsletterGenerator
# ─────────────────────────────────────────────────────────────────────────

def _write_valid_csv(directory) -> None:
    (directory / "articles.csv").write_text(
        "rank,title,link\n"
        "1,First Test Article,https://example.com/1\n"
        "2,Second Test Article,https://example.com/2\n",
        encoding="utf-8",
    )


def test_newsletter_generator_full_success(tmp_path, monkeypatch, mock_gemini_client):
    source_dir = tmp_path / "output"
    output_dir = tmp_path / "newsletters"
    source_dir.mkdir()
    _write_valid_csv(source_dir)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    mock_gemini_client.models.generate_content.return_value = make_gemini_response(
        text="# Daily Briefing\n\nGenerated content here."
    )

    AINewsletterGenerator(
        source_dir=str(source_dir),
        output_dir=str(output_dir),
        env_file=str(tmp_path / "nonexistent.env"),  # unused: key is in os.environ
    ).run()  # must not raise

    md_files = list(output_dir.glob("*.md"))
    assert len(md_files) == 1
    assert "Generated content here." in md_files[0].read_text(encoding="utf-8")


def test_newsletter_generator_raises_configuration_error_with_no_key_anywhere(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError):
        AINewsletterGenerator(
            source_dir=str(tmp_path / "output"),
            output_dir=str(tmp_path / "newsletters"),
            env_file=str(tmp_path / "nonexistent.env"),
        ).run()


def test_newsletter_generator_raises_repository_error_with_no_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    empty_source_dir = tmp_path / "output"
    empty_source_dir.mkdir()

    with pytest.raises(RepositoryError):
        AINewsletterGenerator(
            source_dir=str(empty_source_dir),
            output_dir=str(tmp_path / "newsletters"),
            env_file=str(tmp_path / "nonexistent.env"),
        ).run()


def test_newsletter_generator_propagates_quota_exceeded(tmp_path, monkeypatch, mock_gemini_client):
    source_dir = tmp_path / "output"
    source_dir.mkdir()
    _write_valid_csv(source_dir)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")

    mock_gemini_client.models.generate_content.side_effect = genai_errors.ClientError(
        code=429, response_json={"error": {"message": "quota exceeded"}}, response=None
    )

    with pytest.raises(LLMQuotaExceededError):
        AINewsletterGenerator(
            source_dir=str(source_dir),
            output_dir=str(tmp_path / "newsletters"),
            env_file=str(tmp_path / "nonexistent.env"),
        ).run()


def test_newsletter_generator_propagates_service_unavailable(tmp_path, monkeypatch, mock_gemini_client):
    source_dir = tmp_path / "output"
    source_dir.mkdir()
    _write_valid_csv(source_dir)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")

    mock_gemini_client.models.generate_content.side_effect = genai_errors.ServerError(
        code=503, response_json={"error": {"message": "overloaded"}}, response=None
    )

    with pytest.raises(LLMServiceUnavailableError):
        AINewsletterGenerator(
            source_dir=str(source_dir),
            output_dir=str(tmp_path / "newsletters"),
            env_file=str(tmp_path / "nonexistent.env"),
        ).run()
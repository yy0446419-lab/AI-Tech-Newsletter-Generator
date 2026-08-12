"""
Shared pytest fixtures for the AI Tech Briefing Engine test suite.

Everything here exists to make the pipeline tests hermetic: no real HTTP
requests, no real Gemini API calls, no state leaking between tests.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

# Importing these triggers each module's own module-level side effects
# (logging.basicConfig, and smart_data_extractor also registers the real
# HackerNewsSource/RedditSource into SourceRegistry). The autouse fixture
# below wipes that registration before every test, so it never leaks in.
import ai_newsletter
from core.protocols import Article
from infrastructure.sources.registry import SourceRegistry


@pytest.fixture(autouse=True)
def reset_source_registry():
    """
    SourceRegistry._sources is a class-level dict — shared and mutated by
    every test in the session. Without this, a source registered in one
    test leaks into every test that runs after it, causing order-dependent
    failures. Runs before AND after each test so a failure mid-test can't
    leave the registry dirty for the next one either.
    """
    SourceRegistry._sources.clear()
    yield
    SourceRegistry._sources.clear()


class FakeContentSource:
    """
    Minimal, fully controllable IContentSource test double.

    Satisfies the protocol (source_id property + async extract()) without
    touching the network — used in place of HackerNewsSource/RedditSource
    so pipeline tests exercise ExtractionPipeline's own orchestration logic
    (concurrency, partial-failure tolerance, merging) in isolation.
    """

    def __init__(
        self,
        source_id: str,
        articles: list[Article] | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self._source_id = source_id
        self._articles = articles or []
        self._error = error
        self._delay = delay

    @property
    def source_id(self) -> str:
        return self._source_id

    async def extract(self, limit: int = 20) -> list[Article]:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._articles[:limit]


@pytest.fixture
def make_fake_source():
    """Factory fixture: make_fake_source(source_id, articles=..., error=..., delay=...)."""
    return FakeContentSource


@pytest.fixture
def make_article():
    """Factory fixture for quick Article construction with sensible defaults."""

    def _make(rank: int = 1, title: str = "Test Article", **kwargs) -> Article:
        return Article(rank=rank, title=title, link=f"https://example.com/{rank}", **kwargs)

    return _make


@pytest.fixture
def mock_gemini_client(monkeypatch):
    """
    Patches ai_newsletter.genai.Client so GeminiClient never constructs a
    real SDK client or makes a real network call.

    Yields the mock *instance* genai.Client(...) would have returned —
    configure mock_gemini_client.models.generate_content.return_value (or
    .side_effect) per test to control what GeminiClient.generate() sees.
    """
    mock_instance = MagicMock()
    mock_client_cls = MagicMock(return_value=mock_instance)
    monkeypatch.setattr(ai_newsletter.genai, "Client", mock_client_cls)
    return mock_instance


def make_gemini_response(text: str = "Generated newsletter content."):
    """
    Builds a MagicMock shaped like a successful genai response: one
    candidate, finish_reason=STOP (so GeminiClient.generate()'s warning
    branch doesn't fire), and the given text.
    """
    candidate = MagicMock()
    candidate.finish_reason = ai_newsletter.genai_types.FinishReason.STOP

    response = MagicMock()
    response.candidates = [candidate]
    response.text = text
    return response
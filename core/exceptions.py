"""
╔══════════════════════════════════════════════════════════════════╗
║           AI Tech Briefing Engine — Domain Exceptions            ║
║           Architecture Roadmap · Phase 1 — Stabilize              ║
╚══════════════════════════════════════════════════════════════════╝

This module is the single source of truth for pipeline failure semantics.

Rationale (see ARCHITECTURE_ROADMAP.md, Part 3):
    Both `ai_newsletter.py` and `smart_data_extractor.py` previously called
    `sys.exit()` on failure. That is fatal in any host other than a bare CLI
    script — it kills a Streamlit server thread's script run and would kill
    an entire FastAPI/ASGI worker process outright. Domain exceptions let
    every pipeline stay a pure function of "succeed or raise," leaving the
    decision of *what to do about it* (exit a CLI, show a Streamlit error,
    return an HTTP status code) entirely to the caller.

Hierarchy:

    BriefingEngineError                 (base — catch this to handle "any
    │                                     pipeline failure" generically)
    ├── ScrapingError                   (extraction layer; reserved — wired
    │                                     up in Phase 2 when
    │                                     smart_data_extractor.py becomes a
    │                                     Strategy-pattern IContentSource)
    ├── LLMError                        (AI generation layer)
    │   ├── LLMQuotaExceededError       (HTTP 429 — rate limit / quota)
    │   └── LLMServiceUnavailableError  (HTTP 503 — provider overloaded)
    ├── ConfigurationError              (missing/invalid config, e.g. API keys)
    └── RepositoryError                 (storage read/write failure — CSV
                                          files, Markdown files, etc.)
"""


class BriefingEngineError(Exception):
    """
    Base class for every domain-level exception raised by this engine.

    Catching this (rather than the built-in `Exception`) signals "I am
    specifically handling a known pipeline failure mode," as opposed to
    swallowing arbitrary, unanticipated errors.
    """


class ScrapingError(BriefingEngineError):
    """
    Raised when a content source cannot be reached, times out, or returns
    a response that cannot be parsed into structured data.

    Reserved for the extraction layer. Not yet raised anywhere in the
    codebase — `smart_data_extractor.py` still calls `sys.exit()` directly
    and is intentionally untouched in Phase 1. This class exists now so the
    full exception vocabulary is defined up front; it will be wired into
    real code when Phase 2 (Strategy Pattern) refactors that module into a
    `HackerNewsSource(IContentSource)` implementation.
    """


class LLMError(BriefingEngineError):
    """
    Raised when an AI/LLM provider fails to produce usable content for any
    reason not covered by a more specific subclass below (e.g. malformed
    responses, safety blocks, unexpected SDK errors).
    """


class LLMQuotaExceededError(LLMError):
    """Raised when the LLM provider rejects a request due to quota or rate limits (HTTP 429)."""


class LLMServiceUnavailableError(LLMError):
    """Raised when the LLM provider is temporarily overloaded or unreachable (HTTP 503)."""


class ConfigurationError(BriefingEngineError):
    """Raised when required configuration (e.g. API keys) is missing or invalid."""


class RepositoryError(BriefingEngineError):
    """Raised when reading from or writing to a data store (CSV files, Markdown files, etc.) fails."""
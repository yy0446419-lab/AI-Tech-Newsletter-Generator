"""
╔══════════════════════════════════════════════════════════════════╗
║           AI Tech Briefing Engine — FastAPI Backend               ║
║           Architecture Roadmap — FastAPI Backend                  ║
║                                                                    ║
║           Exposes ExtractionPipeline + AINewsletterGenerator as   ║
║           a REST API, fully decoupled from the Streamlit UI.      ║
║           Both consume the exact same pipeline classes.           ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ai_newsletter import AINewsletterGenerator
from core.exceptions import (
    BriefingEngineError,
    ConfigurationError,
    LLMError,
    LLMQuotaExceededError,
    LLMServiceUnavailableError,
    RepositoryError,
    ScrapingError,
)
from smart_data_extractor import ExtractionPipeline

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — anchored to this file's location, same pattern app.py uses,
# so the server behaves identically regardless of the working directory it's
# launched from.
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = str(BASE_DIR / "output")
NEWSLETTER_DIR = str(BASE_DIR / "newsletters")
ENV_FILE = str(BASE_DIR / ".env")

app = FastAPI(
    title="AI Tech Briefing Engine API",
    description="Concurrent multi-source extraction and AI-synthesized briefing generation.",
    version="1.0.0",
)


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class BriefingResponse(BaseModel):
    status: str
    newsletter_filename: str
    word_count: int
    generated_at: datetime


class ErrorResponse(BaseModel):
    error: str
    detail: str


class HealthResponse(BaseModel):
    status: str


# ─────────────────────────────────────────────────────────────────────────────
# Exception → HTTP response mapping
# ─────────────────────────────────────────────────────────────────────────────
# One entry per exception type: (status_code, client-safe message). The
# message is deliberately generic per category rather than the exception's
# own str() — the real ConfigurationError message, for example, contains
# local file paths and setup instructions that have no business being
# echoed back to an arbitrary API caller. Full detail still reaches the
# server log, via logger.error(..., exc_info=True) in the handler below.
_EXCEPTION_RESPONSE_MAP: dict[type[BriefingEngineError], tuple[int, str]] = {
    LLMQuotaExceededError: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "The AI provider's rate limit or quota was exceeded. Please retry shortly.",
    ),
    LLMServiceUnavailableError: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The AI provider is temporarily overloaded. Please retry shortly.",
    ),
    LLMError: (
        status.HTTP_502_BAD_GATEWAY,
        "The AI provider returned an error during generation.",
    ),
    ScrapingError: (
        status.HTTP_502_BAD_GATEWAY,
        "One or more content sources could not be reached or parsed.",
    ),
    ConfigurationError: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "The service is missing required configuration.",
    ),
    RepositoryError: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "A server-side storage read or write operation failed.",
    ),
    BriefingEngineError: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An unexpected pipeline error occurred.",
    ),
}


def _resolve_error_response(exc: BriefingEngineError) -> tuple[int, str]:
    """
    Walks the exception's MRO to find the most specific registered
    (status_code, message) pair. A plain dict lookup on type(exc) only
    matches an *exact* class — a raised LLMQuotaExceededError would miss
    and fall through to the generic entry. Walking the MRO is what makes
    it correctly resolve to 429 rather than LLMError's 502.
    """
    for cls in type(exc).__mro__:
        if cls in _EXCEPTION_RESPONSE_MAP:
            return _EXCEPTION_RESPONSE_MAP[cls]
    return status.HTTP_500_INTERNAL_SERVER_ERROR, "An unexpected error occurred."


@app.exception_handler(BriefingEngineError)
async def briefing_engine_error_handler(request: Request, exc: BriefingEngineError) -> JSONResponse:
    """
    Single global handler for the entire exception hierarchy. Full detail
    is logged server-side (exc_info=True captures the original traceback,
    chained via `raise ... from exc` throughout the pipeline); only a
    generic, category-appropriate message goes back to the client — the
    real ConfigurationError message, for example, contains local file
    paths and setup instructions that have no business in an API response.
    """
    status_code, client_message = _resolve_error_response(exc)
    logger.error(f"[{type(exc).__name__}] {exc}", exc_info=True)
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=type(exc).__name__, detail=client_message).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Final safety net. If anything escapes the BriefingEngineError hierarchy
    entirely — a genuine bug, not a modeled failure mode — this still
    returns a clean JSON 500 instead of leaking a raw traceback to the
    client.
    """
    logger.critical(f"Unhandled non-domain exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="InternalServerError",
            detail="An unexpected server error occurred.",
        ).model_dump(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _find_latest_newsletter(newsletter_dir: str) -> Path:
    """
    AINewsletterGenerator.run() returns None — it doesn't hand back the
    path it wrote, and this file doesn't modify that class to add one.
    Re-scanning for the most recently modified .md file mirrors the exact
    approach app.py already uses for its Briefing Archive sidebar.
    """
    md_files = sorted(
        Path(newsletter_dir).glob("*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not md_files:
        raise RepositoryError(
            f"Pipeline completed without error, but no .md file was found "
            f"in '{newsletter_dir}'."
        )
    return md_files[0]


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["Operations"])
async def health() -> HealthResponse:
    """Liveness probe for load balancers, container orchestrators, and monitoring."""
    return HealthResponse(status="ok")


@app.post(
    "/generate-briefing",
    response_model=BriefingResponse,
    status_code=status.HTTP_200_OK,
    tags=["Pipeline"],
    responses={
        429: {"model": ErrorResponse, "description": "AI provider rate limit or quota exceeded"},
        500: {"model": ErrorResponse, "description": "Server configuration or storage error"},
        502: {"model": ErrorResponse, "description": "An upstream source or the AI provider returned an error"},
        503: {"model": ErrorResponse, "description": "AI provider temporarily overloaded"},
    },
)
async def generate_briefing() -> BriefingResponse:
    """
    Runs the full pipeline: concurrent multi-source extraction, then AI
    synthesis. Raises — never swallows — BriefingEngineError subclasses on
    failure; the global exception handler above maps them to the
    appropriate HTTP status.

    Deliberately does NOT fall back to a simulated briefing on AI failure,
    unlike the Streamlit UI. That fallback exists so a live product demo
    never shows a broken screen to a visitor — a legitimate UX concern for
    a portfolio piece. A REST client making a real request against a real
    API needs a real, honest error so it can retry or alert, not a
    silently substituted stand-in it has no way to detect.
    """
    await ExtractionPipeline(output_dir=OUTPUT_DIR).run()

    # AINewsletterGenerator.run() is synchronous — the Gemini SDK call it
    # makes is a blocking network call, not an async one. Calling it
    # directly here would freeze this process's entire asyncio event loop
    # for the duration of that call (commonly several seconds); every other
    # concurrent request to this server would stall until it returned.
    # asyncio.to_thread() offloads the blocking call to a worker thread so
    # the event loop stays free to serve other requests in the meantime.
    generator = AINewsletterGenerator(
        source_dir=OUTPUT_DIR,
        output_dir=NEWSLETTER_DIR,
        env_file=ENV_FILE,
    )
    await asyncio.to_thread(generator.run)

    newsletter_path = _find_latest_newsletter(NEWSLETTER_DIR)
    return BriefingResponse(
        status="success",
        newsletter_filename=newsletter_path.name,
        word_count=len(newsletter_path.read_text(encoding="utf-8").split()),
        generated_at=datetime.fromtimestamp(newsletter_path.stat().st_mtime),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
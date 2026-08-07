"""
╔══════════════════════════════════════════════════════════════════╗
║           Async HTTP Client — Shared Extraction Infrastructure   ║
║           Architecture Roadmap · Phase 3 — Asynchronous          ║
║           Processing                                              ║
╚══════════════════════════════════════════════════════════════════╝

Generic, source-agnostic ASYNC HTTP client with retry logic, built on
httpx.AsyncClient. Every concrete IContentSource implementation awaits
this instead of hand-rolling its own async session and retry loop —
this is what lets ExtractionPipeline fetch every registered source
concurrently via asyncio.gather().
"""

import logging

import httpx

from core.exceptions import ScrapingError

logger = logging.getLogger(__name__)


class HTTPClient:
    """
    Manages a persistent httpx.AsyncClient with retry logic, custom
    headers, and configurable timeouts.
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
        # follow_redirects=True is explicit because httpx, unlike requests,
        # defaults it to False — omitting this would silently change
        # behavior on any source that redirects.
        self._session = httpx.AsyncClient(
            headers=self._DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )

    async def get(self, url: str) -> str:
        """
        Performs an async GET request with retry logic.

        Args:
            url: The target URL to fetch.

        Returns:
            The raw HTML content as a string.

        Raises:
            ScrapingError: If all retry attempts are exhausted, or a
                          non-retryable HTTP error occurs.
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(f"GET {url!r}  (attempt {attempt}/{self._max_retries})")
                response = await self._session.get(url)
                response.raise_for_status()
                logger.info(
                    f"Response: HTTP {response.status_code} | "
                    f"{len(response.content) / 1024:.1f} KB"
                )
                return response.text

            except httpx.TimeoutException:
                logger.warning(f"Attempt {attempt}: Request timed out after {self._timeout}s.")
            except httpx.TransportError as exc:
                # Covers ConnectError, ReadError, WriteError, ProtocolError,
                # ProxyError, etc. — anything transient at the connection level.
                logger.warning(f"Attempt {attempt}: Transport/connection error — {exc}")
            except httpx.HTTPStatusError as exc:
                logger.error(f"HTTP error (non-retryable): {exc}")
                raise ScrapingError(f"HTTP error fetching {url!r}: {exc}") from exc
            except httpx.RequestError as exc:
                logger.error(f"Unexpected request exception: {exc}")
                raise ScrapingError(f"Request failed for {url!r}: {exc}") from exc

        raise ScrapingError(
            f"All {self._max_retries} attempts failed for URL: {url!r}"
        )

    async def close(self) -> None:
        """Closes the underlying async HTTP session and releases resources."""
        await self._session.aclose()
        logger.debug("HTTP session closed.")

    async def __aenter__(self) -> "HTTPClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()
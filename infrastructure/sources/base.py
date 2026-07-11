"""
╔══════════════════════════════════════════════════════════════════╗
║           HTTP Client — Shared Extraction Infrastructure         ║
║           Architecture Roadmap · Phase 2 — Strategy Pattern      ║
╚══════════════════════════════════════════════════════════════════╝

Generic, source-agnostic HTTP client with retry logic. Every concrete
IContentSource implementation can reuse this instead of hand-rolling
its own requests.Session and retry loop.
"""

import logging

import requests

from core.exceptions import ScrapingError

logger = logging.getLogger(__name__)


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
            ScrapingError: If all retry attempts are exhausted, or a
                          non-retryable HTTP error occurs.
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
                raise ScrapingError(f"HTTP error fetching {url!r}: {exc}") from exc
            except requests.exceptions.RequestException as exc:
                logger.error(f"Unexpected request exception: {exc}")
                raise ScrapingError(f"Request failed for {url!r}: {exc}") from exc

        raise ScrapingError(
            f"All {self._max_retries} attempts failed for URL: {url!r}"
        )

    def close(self) -> None:
        """Closes the underlying HTTP session and releases resources."""
        self._session.close()
        logger.debug("HTTP session closed.")

    def __enter__(self) -> "HTTPClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
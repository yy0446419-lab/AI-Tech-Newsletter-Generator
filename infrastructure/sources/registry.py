"""
╔══════════════════════════════════════════════════════════════════╗
║           Source Registry — Strategy Factory                     ║
║           Architecture Roadmap · Phase 2 — Strategy Pattern      ║
╚══════════════════════════════════════════════════════════════════╝

Central factory/registry for IContentSource strategies. ExtractionPipeline
asks this registry for a source by its string ID; it never imports a
concrete source class directly. This is what lets a new source (Reddit,
Bloomberg, a real-estate feed, ...) be added with a single new file plus
a single registration call — zero changes to the pipeline itself.
"""

import logging

from core.exceptions import ScrapingError
from core.protocols import IContentSource

logger = logging.getLogger(__name__)


class SourceRegistry:
    """
    Process-wide registry mapping source_id -> IContentSource instance.

    Implemented with classmethods rather than as something you
    instantiate: there is exactly one registry per process, shared by
    every caller. A CLI run, a Streamlit callback, and eventually every
    FastAPI request handler all resolve sources through the same
    registry, so registration only needs to happen once at import time.
    """

    _sources: dict[str, IContentSource] = {}

    @classmethod
    def register(cls, source: IContentSource) -> None:
        """
        Registers a content source strategy under its own source_id.

        Args:
            source: Any object satisfying the IContentSource protocol.

        Raises:
            TypeError: If `source` does not implement IContentSource
                      (missing source_id or extract()), checked via
                      isinstance() against the runtime_checkable protocol.
        """
        if not isinstance(source, IContentSource):
            raise TypeError(
                f"{type(source).__name__!r} does not implement the "
                f"IContentSource protocol (missing source_id or extract())."
            )
        cls._sources[source.source_id] = source
        logger.info(f"Registered content source: '{source.source_id}' ({type(source).__name__})")

    @classmethod
    def get(cls, source_id: str) -> IContentSource:
        """
        Resolves a registered source by its ID.

        Args:
            source_id: The identifier a source was registered under.

        Returns:
            The IContentSource instance registered for this ID.

        Raises:
            ScrapingError: If no source is registered under this ID.
        """
        if source_id not in cls._sources:
            available = ", ".join(sorted(cls._sources)) or "(none registered)"
            raise ScrapingError(
                f"Unknown source_id: {source_id!r}. Available sources: {available}"
            )
        return cls._sources[source_id]

    @classmethod
    def available_ids(cls) -> list[str]:
        """Returns all currently registered source IDs, e.g. for a UI selector."""
        return sorted(cls._sources.keys())
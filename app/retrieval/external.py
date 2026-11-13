"""Future external-source contract; external correction is explicitly disabled."""

from typing import Protocol
from app.retrieval.chunks import Chunk


class ExternalEvidenceSource(Protocol):
    """An unimplemented source boundary, never called by the corrective pipeline."""

    def search(self, question: str) -> list[Chunk]:
        """Return external evidence only in a separately authorized future design."""
        ...


class DisabledExternalSource:
    """Reject all external-source requests instead of fetching ungoverned evidence."""

    def search(self, question: str) -> list[Chunk]:
        """Refuse external correction unconditionally."""
        raise RuntimeError("External evidence sources are disabled.")

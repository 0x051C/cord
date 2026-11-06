from datetime import datetime
from typing import Iterable, Optional, Protocol


class StorageError(RuntimeError):
    """The storage backend is not reachable / not usable."""


class Repository(Protocol):
    """Stores validated papers as JSON-compatible documents, one collection per paper kind."""

    def ping(self) -> None:
        """Raise ``StorageError`` when the backend is unavailable."""

    def insert_many(self, kind: str, documents: Iterable[dict], created_at: Optional[datetime] = None) -> int:
        """Store documents of a kind; ``created_at`` defaults to now. Returns the inserted count."""

    def fetch_since(self, kind: str, since: datetime) -> list[dict]:
        """Documents of a kind stored after ``since``, oldest first."""

    def count(self, kind: str) -> int:
        """Number of stored documents of a kind."""

    # Run journal (shown by the web UI) ---------------------------------------
    def save_run(self, run: dict, errors: list[dict]) -> None:
        """Store a run summary (``run["id"]``, ``run["started_at"]``...) and its validation errors."""

    def list_runs(self, limit: int = 50) -> list[dict]:
        """Run summaries, newest first."""

    def get_run(self, run_id: str) -> Optional[dict]: ...

    def run_errors(self, run_ids: list[str]) -> list[dict]:
        """Validation errors of the given runs, each with ``id`` and ``run_id``."""

    def get_error(self, error_id: str) -> Optional[dict]: ...

    def close(self) -> None: ...

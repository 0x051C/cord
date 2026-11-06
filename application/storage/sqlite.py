"""
SQLite repository.

Each paper kind gets a table whose columns are derived from the model schema
(one column per leaf field, e.g. ``item__documents__date_started``) so the data
is easy to browse and query, plus ``_document`` holding the complete JSON
document, which is what ``fetch_since`` returns.
"""

import functools
import json
import sqlite3
import threading
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union, get_args, get_origin

from application.storage.base import StorageError
from models.logic.pydantic_helper import LeafField, get_path
from models.registry import PAPER_KINDS, PaperKind

_SQL_TYPES = {str: "TEXT", int: "INTEGER", float: "REAL"}


def _sql_type(leaf: LeafField) -> str:
    annotation = leaf.info.annotation
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        annotation = args[0] if len(args) == 1 else None
    return _SQL_TYPES.get(annotation, "")  # "" -> no declared type, SQLite keeps values as given


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _to_sql_value(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


_JOURNAL_DDL = """
CREATE TABLE IF NOT EXISTS _runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,
    document TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS _runs_started_at ON _runs (started_at);
CREATE TABLE IF NOT EXISTS _errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    file TEXT, kind TEXT, row INTEGER, field TEXT, message TEXT, value TEXT, context TEXT
);
CREATE INDEX IF NOT EXISTS _errors_run_id ON _errors (run_id);
"""
_ERROR_COLUMNS = ("file", "kind", "row", "field", "message", "value", "context")


def _locked(method):
    """One connection shared by threads (the web server), statements are serialised."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class SQLiteRepository:
    def __init__(self, path: Union[str, Path], kinds: Iterable[PaperKind] = PAPER_KINDS):
        self.path = str(path)
        self.kinds = {kind.key: kind for kind in kinds}
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
        except sqlite3.Error as e:
            raise StorageError(f"Cannot open SQLite database {self.path}: {e}") from e
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        for kind in self.kinds.values():
            self._ensure_table(kind)
        with self._conn:
            self._conn.executescript(_JOURNAL_DDL)

    def _ensure_table(self, kind: PaperKind) -> None:
        table = _quote(kind.key)
        leaves = kind.model.leaf_fields()
        columns = ",\n".join(f"    {_quote(leaf.column)} {_sql_type(leaf)}".rstrip() for leaf in leaves)
        with self._conn:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (\n"
                "    _id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                "    _created_at TEXT NOT NULL,\n"
                "    _document TEXT NOT NULL,\n"
                f"{columns}\n)"
            )
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS {_quote(kind.key + '_created_at')} ON {table} (_created_at)"
            )
            # The schema may have gained fields since the table was created.
            existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for leaf in leaves:
                if leaf.column not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {_quote(leaf.column)} {_sql_type(leaf)}")

    def _kind(self, key: str) -> PaperKind:
        try:
            return self.kinds[key]
        except KeyError:
            raise KeyError(f"Unknown paper kind {key!r}, expected one of {sorted(self.kinds)}") from None

    @_locked
    def ping(self) -> None:
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error as e:
            raise StorageError(str(e)) from e

    @_locked
    def insert_many(self, kind: str, documents: Iterable[dict], created_at: Optional[datetime] = None) -> int:
        paper_kind = self._kind(kind)
        leaves = paper_kind.model.leaf_fields()
        created = _utc_iso(created_at or datetime.now(timezone.utc))
        columns = ["_created_at", "_document", *(leaf.column for leaf in leaves)]
        sql = (
            f"INSERT INTO {_quote(kind)} ({', '.join(map(_quote, columns))}) "
            f"VALUES ({', '.join('?' for _ in columns)})"
        )
        rows = [
            (
                created,
                json.dumps(document, ensure_ascii=False),
                *(_to_sql_value(get_path(document, leaf.path)) for leaf in leaves),
            )
            for document in documents
        ]
        with self._conn:
            self._conn.executemany(sql, rows)
        return len(rows)

    @_locked
    def fetch_since(self, kind: str, since: datetime) -> list[dict]:
        self._kind(kind)
        cursor = self._conn.execute(
            f"SELECT _document FROM {_quote(kind)} WHERE _created_at > ? ORDER BY _id", (_utc_iso(since),)
        )
        return [json.loads(row["_document"]) for row in cursor]

    @_locked
    def count(self, kind: str) -> int:
        self._kind(kind)
        return self._conn.execute(f"SELECT COUNT(*) FROM {_quote(kind)}").fetchone()[0]

    # ------------------------------------------------------------ run journal
    @_locked
    def save_run(self, run: dict, errors: list[dict]) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO _runs (id, started_at, status, document) VALUES (?, ?, ?, ?)",
                (run["id"], run["started_at"], run["status"], json.dumps(run, ensure_ascii=False)),
            )
            self._conn.executemany(
                f"INSERT INTO _errors (run_id, {', '.join(_ERROR_COLUMNS)}) VALUES (?{', ?' * len(_ERROR_COLUMNS)})",
                [(run["id"], *(error.get(column) for column in _ERROR_COLUMNS)) for error in errors],
            )

    @_locked
    def list_runs(self, limit: int = 50) -> list[dict]:
        cursor = self._conn.execute("SELECT document FROM _runs ORDER BY started_at DESC LIMIT ?", (limit,))
        return [json.loads(row["document"]) for row in cursor]

    @_locked
    def get_run(self, run_id: str) -> Optional[dict]:
        row = self._conn.execute("SELECT document FROM _runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row["document"]) if row else None

    @_locked
    def run_errors(self, run_ids: list[str]) -> list[dict]:
        if not run_ids:
            return []
        cursor = self._conn.execute(
            f"SELECT * FROM _errors WHERE run_id IN ({', '.join('?' for _ in run_ids)}) ORDER BY id", list(run_ids)
        )
        return [dict(row, id=str(row["id"])) for row in cursor]

    @_locked
    def get_error(self, error_id: str) -> Optional[dict]:
        if not str(error_id).isdigit():
            return None
        row = self._conn.execute("SELECT * FROM _errors WHERE id = ?", (int(error_id),)).fetchone()
        return dict(row, id=str(row["id"])) if row else None

    @_locked
    def close(self) -> None:
        self._conn.close()

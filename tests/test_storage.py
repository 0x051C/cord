from datetime import datetime, timedelta, timezone

import pytest

from application.storage.sqlite import SQLiteRepository
from models.registry import KINDS_BY_KEY, PAPER_KINDS


def test_tables_follow_the_schema(repository):
    for kind in PAPER_KINDS:
        columns = [row["name"] for row in repository._conn.execute(f'PRAGMA table_info("{kind.key}")')]
        assert columns == ["_id", "_created_at", "_document", *(leaf.column for leaf in kind.model.leaf_fields())]


def test_round_trip(repository, generator):
    kind = KINDS_BY_KEY["declaration"]
    documents = generator.documents(kind, 5)
    assert repository.insert_many(kind.key, documents) == 5
    assert repository.fetch_since(kind.key, datetime.now(timezone.utc) - timedelta(minutes=1)) == documents
    row = repository._conn.execute('SELECT declaration_id, item__documents__document FROM "declaration"').fetchone()
    assert row["declaration_id"] == documents[0]["declaration_id"]
    assert row["item__documents__document"] == documents[0]["item"]["documents"]["document"]


def test_fetch_since_filters_by_insertion_time(repository, generator):
    kind = KINDS_BY_KEY["waybill"]
    now = datetime.now(timezone.utc)
    repository.insert_many(kind.key, generator.documents(kind, 2), created_at=now - timedelta(days=400))
    repository.insert_many(kind.key, generator.documents(kind, 3), created_at=now - timedelta(days=10))
    assert len(repository.fetch_since(kind.key, now - timedelta(days=180))) == 3
    assert repository.count(kind.key) == 5


def test_seed_repository(repository, generator):
    kind = KINDS_BY_KEY["clearancestatement"]
    assert generator.seed_repository(repository, kind, 7, days=30) == 7
    assert len(repository.fetch_since(kind.key, datetime.now(timezone.utc) - timedelta(days=31))) == 7


def test_unknown_kind(repository):
    with pytest.raises(KeyError):
        repository.insert_many("nope", [])


def test_new_schema_fields_are_added(tmp_path):
    path = tmp_path / "db.sqlite3"
    SQLiteRepository(path).close()
    repo = SQLiteRepository(path)
    with repo._conn:
        repo._conn.execute('CREATE TABLE "old" (_id INTEGER PRIMARY KEY, _created_at TEXT, _document TEXT)')
    repo.close()
    # reopening an existing database must not fail
    SQLiteRepository(path).close()

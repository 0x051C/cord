"""MongoDB repository: one collection per paper kind, insertion time is taken from ``_id``."""

import os
import struct
from datetime import datetime, timezone
from typing import Iterable, Optional

from application.storage.base import StorageError


def _object_id_at(moment: datetime):
    from bson import ObjectId

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return ObjectId(struct.pack(">I", int(moment.timestamp())) + os.urandom(8))


class MongoRepository:
    def __init__(self, uri: str, database: str = "cord", timeout_ms: int = 5000):
        from pymongo import MongoClient

        self._client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
        self._db = self._client[database]

    def ping(self) -> None:
        from pymongo.errors import PyMongoError

        try:
            self._client.admin.command("ping")
        except PyMongoError as e:
            raise StorageError(str(e)) from e

    def insert_many(self, kind: str, documents: Iterable[dict], created_at: Optional[datetime] = None) -> int:
        documents = [dict(document) for document in documents]
        if not documents:
            return 0
        if created_at is not None:
            for document in documents:
                document["_id"] = _object_id_at(created_at)
        return len(self._db[kind].insert_many(documents).inserted_ids)

    def fetch_since(self, kind: str, since: datetime) -> list[dict]:
        from bson import ObjectId

        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        documents = list(self._db[kind].find({"_id": {"$gt": ObjectId.from_datetime(since)}}).sort("_id", 1))
        for document in documents:
            document.pop("_id", None)
        return documents

    def count(self, kind: str) -> int:
        return self._db[kind].count_documents({})

    # ------------------------------------------------------------ run journal
    def save_run(self, run: dict, errors: list[dict]) -> None:
        self._db["_runs"].replace_one({"_id": run["id"]}, {"_id": run["id"], **run}, upsert=True)
        if errors:
            self._db["_errors"].insert_many([{"run_id": run["id"], **error} for error in errors])

    def list_runs(self, limit: int = 50) -> list[dict]:
        cursor = self._db["_runs"].find({}, {"_id": 0}).sort("started_at", -1).limit(limit)
        return list(cursor)

    def get_run(self, run_id: str) -> Optional[dict]:
        return self._db["_runs"].find_one({"_id": run_id}, {"_id": 0})

    def run_errors(self, run_ids: list[str]) -> list[dict]:
        cursor = self._db["_errors"].find({"run_id": {"$in": list(run_ids)}}).sort("_id", 1)
        return [_with_str_id(document) for document in cursor]

    def get_error(self, error_id: str) -> Optional[dict]:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            document = self._db["_errors"].find_one({"_id": ObjectId(error_id)})
        except (InvalidId, TypeError):
            return None
        return _with_str_id(document) if document else None

    def close(self) -> None:
        self._client.close()


def _with_str_id(document: dict) -> dict:
    document["id"] = str(document.pop("_id"))
    return document

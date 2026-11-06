from application.configuration_handling import resolve_path
from application.storage.base import Repository, StorageError


def build_repository(settings) -> Repository:
    backend = str(settings.get("storage_backend", "mongo")).lower()
    if backend == "sqlite":
        from application.storage.sqlite import SQLiteRepository

        return SQLiteRepository(resolve_path(settings.get("sqlite_path", "sandbox/cord.sqlite3")))
    if backend == "mongo":
        from application.storage.mongo import MongoRepository

        return MongoRepository(
            settings.mongod_connection_link,
            database=settings.get("mongod_database", "cord"),
        )
    raise ValueError(f"Unknown storage_backend setting: {backend!r} (expected 'mongo' or 'sqlite')")


__all__ = ["Repository", "StorageError", "build_repository"]

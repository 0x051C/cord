"""
The ETL run: input files -> validation -> storage -> department reports.

1. new files in ``input_files_path`` are validated row by row (errors go to
   ``validation.log``), processed files are rotated (``.old`` -> ``.old.old`` -> ``old/``);
2. valid records are stored (MongoDB or SQLite); when storage is unreachable they
   are dumped to ``output_<time>.json`` instead;
3. records stored during the last ``days_to_fetch`` days are routed to the
   departments and exported to xlsx (only when the run stored new records);
4. log files are copied next to the reports, an ``__CLEAR__`` file in the input
   folder truncates them afterwards.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from application import ingest, reports
from application.filesystem import FileSystem, build_filesystem
from application.logging_setup import LOG_FILE_NAMES, configure_logging, flush_logs, validation_logger
from application.pipeline_config import PipelineConfig
from application.storage import Repository, StorageError, build_repository
from models.paper import Paper
from models.registry import kind_of

CLEAR_LOGS_MARKER = "__CLEAR__"


STATUS_OK = "ok"
STATUS_NO_NEW_RECORDS = "no_new_records"
STATUS_STORAGE_UNAVAILABLE = "storage_unavailable"
STATUS_FAILED = "failed"


@dataclass
class RunReport:
    id: str
    started_at: datetime
    environment: str = ""
    finished_at: Optional[datetime] = None
    status: str = STATUS_OK
    message: str = ""
    files: list[dict] = field(default_factory=list)  # FileResult.to_document()
    valid_rows: int = 0
    invalid_rows: int = 0
    stored: dict[str, int] = field(default_factory=dict)
    routed: dict[str, dict[str, int]] = field(default_factory=dict)  # department -> kind -> records in its reports
    exported: list[str] = field(default_factory=list)
    fallback_dump: Optional[str] = None
    errors: list[ingest.RowError] = field(default_factory=list)

    @classmethod
    def start(cls, now: datetime, environment: str) -> "RunReport":
        return cls(id=f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}", started_at=now, environment=environment)

    @classmethod
    def from_document(cls, document: dict, errors: list[dict]) -> "RunReport":
        """Inverse of ``to_document`` (plus the separately stored errors)."""
        finished = document.get("finished_at")
        return cls(
            id=document["id"],
            started_at=datetime.fromisoformat(document["started_at"]),
            environment=document.get("environment", ""),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            status=document.get("status", STATUS_OK),
            message=document.get("message", ""),
            files=document.get("files", []),
            valid_rows=document.get("valid_rows", 0),
            invalid_rows=document.get("invalid_rows", 0),
            stored=document.get("stored", {}),
            routed=document.get("routed", {}),
            exported=document.get("exported", []),
            fallback_dump=document.get("fallback_dump"),
            errors=[ingest.RowError(**error) for error in errors],
        )

    def to_document(self) -> dict:
        """JSON-compatible summary stored in the run journal (errors are stored separately)."""
        return {
            "id": self.id,
            "environment": self.environment,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "message": self.message,
            "files": self.files,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "error_count": len(self.errors),
            "stored": self.stored,
            "routed": self.routed,
            "exported": self.exported,
            "fallback_dump": self.fallback_dump,
        }

    def summary(self) -> str:
        names = [file["name"] for file in self.files]
        lines = [
            f"run             : {self.id} ({self.status}{', ' + self.message if self.message else ''})",
            f"files processed : {len(names)} {names if names else ''}".rstrip(),
            f"rows valid      : {self.valid_rows}",
            f"rows invalid    : {self.invalid_rows} (details in validation.log)",
            f"stored          : {self.stored or '-'}",
            f"reports written : {len(self.exported)}",
        ]
        if self.fallback_dump:
            lines.append(f"storage unavailable, records dumped to {self.fallback_dump}")
        return "\n".join(lines)


def group_documents(papers: list[Paper]) -> dict[str, list[dict]]:
    """Validated papers as JSON-compatible documents, grouped by paper kind key."""
    grouped: dict[str, list[dict]] = dict()
    for paper in papers:
        grouped.setdefault(kind_of(paper).key, []).append(paper.model_dump(mode="json"))
    return grouped


def store_documents(
    repository: Repository, grouped: dict[str, list[dict]], created_at: Optional[datetime] = None
) -> dict[str, int]:
    return {key: repository.insert_many(key, documents, created_at=created_at) for key, documents in grouped.items()}


def store(repository: Repository, papers: list[Paper], created_at: Optional[datetime] = None) -> dict[str, int]:
    return store_documents(repository, group_documents(papers), created_at=created_at)


def dump_documents(grouped: dict[str, list[dict]], directory: str, now: datetime) -> str:
    path = Path(directory) / f"output_{now.strftime('%Y-%m-%d_%H-%M-%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "received_timestamp": now.timestamp(),
        "paper_list": [
            {"_id": uuid.uuid4().hex, "_kind": key} | document
            for key, documents in grouped.items()
            for document in documents
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def dump_fallback(papers: list[Paper], directory: str, now: datetime) -> str:
    return dump_documents(group_documents(papers), directory, now)


def publish(repository: Repository, fs: FileSystem, config: PipelineConfig, now: datetime) -> tuple[dict, list[str]]:
    """Route the records stored during the last ``days_to_fetch`` days and export them to xlsx."""
    sorted_documents = reports.sort_documents(repository, config, now)
    return _routed_counts(sorted_documents), reports.export(fs, config, sorted_documents, now)


def save_journal(repository: Repository, report: "RunReport") -> None:
    """Store the run summary and its errors for the dashboard; never hides the outcome of the run."""
    try:
        repository.save_run(report.to_document(), [error.to_document() for error in report.errors])
    except Exception as e:
        validation_logger.error(f"Could not save the run journal: {e!r}")


def supply_logs(fs: FileSystem, config: PipelineConfig) -> None:
    flush_logs()
    logs = [Path(config.log_dir) / name for name in LOG_FILE_NAMES if (Path(config.log_dir) / name).exists()]
    for folder in set(config.output_dirs.values()):
        fs.makedirs(folder)
        for log in logs:
            fs.upload(str(log), fs.join(folder, log.name))
    if CLEAR_LOGS_MARKER in fs.listdir(config.input_dir):
        for log in logs:
            log.write_text("", encoding="utf-8")


def _routed_counts(sorted_documents) -> dict[str, dict[str, int]]:
    return {
        department.value: {key: len(frame) for key, frame in frames.items()}
        for department, frames in sorted_documents.items()
    }


def _connect(settings, repository: Optional[Repository]) -> tuple[Optional[Repository], Optional[Exception]]:
    """Return a reachable repository, or the reason there is none."""
    created = None
    try:
        if repository is None:
            repository = created = build_repository(settings)
        repository.ping()
        return repository, None
    except (StorageError, OSError) as e:
        if created is not None:
            created.close()
        return None, e


def run(
    settings=None,
    *,
    config: Optional[PipelineConfig] = None,
    fs: Optional[FileSystem] = None,
    repository: Optional[Repository] = None,
    now: Optional[datetime] = None,
) -> RunReport:
    from application.configuration_handling import ENVIRONMENT

    if settings is None:
        from application.configuration_handling import settings
    config = config or PipelineConfig.from_settings(settings)
    configure_logging(config.log_dir)
    fs = fs or build_filesystem(settings)
    now = now or datetime.now(timezone.utc)
    report = RunReport.start(now, ENVIRONMENT)
    own_repository = repository is None
    repo, storage_error = None, None

    try:
        results = ingest.ingest(fs, config)
        papers = [paper for result in results for paper in result.papers]
        report.files = [result.to_document() for result in results]
        report.errors = [error for result in results for error in result.errors]
        report.valid_rows = len(papers)
        report.invalid_rows = sum(result.invalid_rows for result in results)

        repo, storage_error = _connect(settings, repository)
        if not papers:
            report.status = STATUS_NO_NEW_RECORDS
            validation_logger.warning("No new records.")
        elif repo is None:
            report.status = STATUS_STORAGE_UNAVAILABLE
            report.message = str(storage_error)
            report.fallback_dump = dump_fallback(papers, config.fallback_dump_dir, now)
            validation_logger.error(
                f"An error occurred while connecting to the database: \n\t\t{storage_error}\n\n"
                f"Records were saved to {report.fallback_dump}"
            )
        else:
            report.stored = store(repo, papers)
            report.routed, report.exported = publish(repo, fs, config, now)

        supply_logs(fs, config)
    except Exception as e:
        report.status, report.message = STATUS_FAILED, repr(e)
        validation_logger.exception("The run failed")
        raise
    finally:
        report.finished_at = datetime.now(timezone.utc)
        if repo is not None:
            save_journal(repo, report)
            if own_repository:
                repo.close()
    return report

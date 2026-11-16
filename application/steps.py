"""
The ETL run split into steps that run in separate processes (the Airflow tasks in
``dags/cord_etl.py``)::

    extract -> load -> publish -> deliver_logs -> record

``pipeline.run`` does the same work in one process (``python main.py run``); both use
the helpers in ``application/pipeline.py``.

A run keeps its state in a stage file, ``<staging_path>/<run id>.json``: the run summary,
the validation errors and the validated records. Every step reads the file, does its part
and writes it back. Input files are renamed as soon as they are read, so ``extract`` must
never be retried; the later steps can be, because they only work from the stage file.

``record`` saves the run to the journal shown by the dashboard. It runs even when an
earlier step failed and works out from the stage file how far the run got. The stage file
is deleted once a run has been recorded, unless it failed or storage was unavailable.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from application import ingest
from application.filesystem import FileSystem, build_filesystem
from application.logging_setup import configure_logging, validation_logger
from application.pipeline import (
    STATUS_FAILED,
    STATUS_NO_NEW_RECORDS,
    STATUS_OK,
    STATUS_STORAGE_UNAVAILABLE,
    RunReport,
    _connect,
    dump_documents,
    group_documents,
    publish as publish_reports,
    save_journal,
    store_documents,
    supply_logs,
)
from application.pipeline_config import PipelineConfig
from application.storage import Repository, StorageError

STATUS_RUNNING = "running"  # extracted, not stored yet


@dataclass
class Stage:
    report: RunReport
    documents: dict[str, list[dict]]  # paper kind key -> validated records
    published: bool = False


def write_stage(directory: str, stage: Stage) -> str:
    """Save the run state atomically; returns the stage file path."""
    path = Path(directory) / f"{stage.report.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run": stage.report.to_document(),
        "errors": [error.to_document() for error in stage.report.errors],
        "documents": stage.documents,
        "published": stage.published,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return str(path)


def read_stage(path: str) -> Stage:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Stage(
        report=RunReport.from_document(payload["run"], payload["errors"]),
        documents=payload["documents"],
        published=payload.get("published", False),
    )


def _setup(settings, config: Optional[PipelineConfig], fs: Optional[FileSystem], new_run: bool = False):
    if settings is None:
        from application.configuration_handling import settings
    config = config or PipelineConfig.from_settings(settings)
    configure_logging(config.log_dir, new_run=new_run)
    return settings, config, fs


def extract(
    settings=None,
    *,
    config: Optional[PipelineConfig] = None,
    fs: Optional[FileSystem] = None,
    now: Optional[datetime] = None,
) -> str:
    """Read and validate new input files (marking them processed); returns the stage file path."""
    from application.configuration_handling import ENVIRONMENT

    settings, config, fs = _setup(settings, config, fs, new_run=True)
    fs = fs or build_filesystem(settings)
    report = RunReport.start(now or datetime.now(timezone.utc), ENVIRONMENT)
    report.status = STATUS_RUNNING

    results = ingest.ingest(fs, config)
    papers = [paper for result in results for paper in result.papers]
    report.files = [result.to_document() for result in results]
    report.errors = [error for result in results for error in result.errors]
    report.valid_rows = len(papers)
    report.invalid_rows = sum(result.invalid_rows for result in results)
    return write_stage(config.staging_dir, Stage(report, group_documents(papers)))


def load(
    stage_path: str,
    settings=None,
    *,
    config: Optional[PipelineConfig] = None,
    repository: Optional[Repository] = None,
    allow_fallback: bool = True,
) -> str:
    """Store the validated records; returns the run status.

    When storage is unreachable this raises ``StorageError`` (so the scheduler can retry),
    or, with ``allow_fallback`` (the last attempt), dumps the records to a JSON file instead.
    """
    settings, config, _ = _setup(settings, config, None)
    stage = read_stage(stage_path)
    report = stage.report
    if report.status != STATUS_RUNNING:  # already done by an earlier attempt
        return report.status

    if not stage.documents:
        report.status = STATUS_NO_NEW_RECORDS
        validation_logger.warning("No new records.")
        write_stage(config.staging_dir, stage)
        return report.status

    repo, storage_error = _connect(settings, repository)
    if repo is None:
        if not allow_fallback:
            raise StorageError(f"Storage is unavailable: {storage_error}")
        report.status = STATUS_STORAGE_UNAVAILABLE
        report.message = str(storage_error)
        report.fallback_dump = dump_documents(stage.documents, config.fallback_dump_dir, report.started_at)
        validation_logger.error(
            f"An error occurred while connecting to the database: \n\t\t{storage_error}\n\n"
            f"Records were saved to {report.fallback_dump}"
        )
        write_stage(config.staging_dir, stage)
        return report.status

    try:
        report.stored = store_documents(repo, stage.documents, created_at=report.started_at)
        report.status = STATUS_OK
        write_stage(config.staging_dir, stage)
    finally:
        if repository is None:
            repo.close()
    return report.status


def publish(
    stage_path: str,
    settings=None,
    *,
    config: Optional[PipelineConfig] = None,
    fs: Optional[FileSystem] = None,
    repository: Optional[Repository] = None,
) -> int:
    """Route the stored records to the departments and export the xlsx reports; returns how many."""
    settings, config, fs = _setup(settings, config, fs)
    stage = read_stage(stage_path)
    report = stage.report
    if report.status != STATUS_OK or stage.published:
        return len(report.exported)

    fs = fs or build_filesystem(settings)
    repo, storage_error = _connect(settings, repository)
    if repo is None:
        raise StorageError(f"Storage is unavailable: {storage_error}")
    try:
        report.routed, report.exported = publish_reports(repo, fs, config, report.started_at)
    finally:
        if repository is None:
            repo.close()
    stage.published = True
    write_stage(config.staging_dir, stage)
    return len(report.exported)


def deliver_logs(settings=None, *, config: Optional[PipelineConfig] = None, fs: Optional[FileSystem] = None) -> None:
    """Copy the log files next to the reports (truncating them when ``__CLEAR__`` is present)."""
    settings, config, fs = _setup(settings, config, fs)
    supply_logs(fs or build_filesystem(settings), config)


def _outcome(stage: Optional[Stage]) -> Optional[str]:
    """Why the run is incomplete, or None when every step finished."""
    if stage is None:
        return "reading the input files failed"
    if stage.report.status == STATUS_RUNNING:
        return "storing the records failed"
    if stage.report.status == STATUS_OK and not stage.published:
        return "exporting the reports failed"
    return None


def record(
    stage_path: Optional[str],
    settings=None,
    *,
    config: Optional[PipelineConfig] = None,
    repository: Optional[Repository] = None,
    now: Optional[datetime] = None,
) -> RunReport:
    """Finish the run and save it to the journal; works out from the stage file whether a step failed."""
    from application.configuration_handling import ENVIRONMENT

    settings, config, _ = _setup(settings, config, None)
    now = now or datetime.now(timezone.utc)
    stage = read_stage(stage_path) if stage_path and Path(stage_path).exists() else None
    report = stage.report if stage else RunReport.start(now, ENVIRONMENT)

    failure = _outcome(stage)
    if failure:
        report.status, report.message = STATUS_FAILED, failure
        validation_logger.error(f"The run failed: {failure}")
    report.finished_at = now

    repo, storage_error = _connect(settings, repository)
    if repo is None:
        validation_logger.error(f"Could not save the run journal: {storage_error}")
    else:
        save_journal(repo, report)
        if repository is None:
            repo.close()

    if stage is not None:
        write_stage(config.staging_dir, stage)
        if report.status in (STATUS_OK, STATUS_NO_NEW_RECORDS):
            Path(stage_path).unlink()
    return report

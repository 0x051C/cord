"""Routing stored records to departments and exporting them to xlsx."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from application.filesystem import FileSystem
from application.logging_setup import validation_logger
from application.pipeline_config import Department, PipelineConfig
from application.storage import Repository
from models.paper import stringify
from models.registry import PaperKind

DATE_FORMAT = "%d-%m-%Y"


def to_frame(kind: PaperKind, documents: list[dict]) -> pd.DataFrame:
    return pd.DataFrame.from_records(
        [[stringify(value) for value in kind.model.flatten_document(document)] for document in documents],
        columns=kind.model.flat_titles(),
    )


def route(frame: pd.DataFrame, column: str, patterns: dict[Department, Optional[str]]) -> dict[Department, pd.DataFrame]:
    """Split records by department, a record may go to several departments."""
    values = frame[column].fillna("").astype(str)
    routed = dict()
    for department, pattern in patterns.items():
        if pattern:
            compiled = re.compile(pattern)
            mask = values.map(lambda value: compiled.search(value) is not None).astype(bool)
            routed[department] = frame[mask]
        else:
            routed[department] = frame.iloc[0:0]
    return routed


def sort_documents(
    repository: Repository, config: PipelineConfig, now: datetime
) -> dict[Department, dict[str, pd.DataFrame]]:
    since = now - timedelta(days=config.days_to_fetch)
    result: dict[Department, dict[str, pd.DataFrame]] = {department: dict() for department in Department}
    for kind in config.kinds:
        documents = repository.fetch_since(kind.key, since)
        if not documents:
            continue
        for department, frame in route(to_frame(kind, documents), kind.sort_column, config.routing_patterns).items():
            result[department][kind.key] = frame
    return result


def date_range(config: PipelineConfig, now: datetime) -> tuple[str, str]:
    return (now - timedelta(days=config.days_to_fetch)).strftime(DATE_FORMAT), now.strftime(DATE_FORMAT)


def export(
    fs: FileSystem,
    config: PipelineConfig,
    sorted_documents: dict[Department, dict[str, pd.DataFrame]],
    now: Optional[datetime] = None,
) -> list[str]:
    now = now or datetime.now(timezone.utc)
    date_from, date_to = date_range(config, now)
    written = list()
    for department, frames in sorted_documents.items():
        folder = config.output_dirs[department]
        fs.makedirs(folder)
        for key, frame in frames.items():
            path = fs.join(folder, config.output_filenames[key].format(date_from, date_to) + ".xlsx")
            with fs.open(path, mode="wb") as handle:
                frame.to_excel(handle, sheet_name=date_to, index=False, engine="openpyxl")
            validation_logger.info(f"{department.value}: {len(frame)} records -> {path}")
            written.append(path)
    return written

"""Discovering input files, reading them and validating their rows."""

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Optional

from pydantic import ValidationError

from application.filesystem import FileSystem
from application.logging_setup import validation_logger
from application.pipeline_config import PipelineConfig
from models.paper import Paper
from models.registry import PaperKind

PROCESSED_SUFFIX = ".old"
ARCHIVE_DIR = "old"


MAX_VALUE_LENGTH = 500
MAX_CONTEXT_LENGTH = 20_000


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass
class RowError:
    """One validation error of one row (a row may have several)."""

    file: str
    kind: str
    row: int  # 1-based data row number (the header is not counted)
    field: str  # e.g. "item.documents.date_started"
    message: str
    value: str  # offending input value
    context: str  # the whole row, as JSON

    def to_document(self) -> dict:
        return asdict(self)


@dataclass
class FileResult:
    name: str
    kind: PaperKind
    papers: list[Paper] = field(default_factory=list)
    rows: int = 0
    errors: list[RowError] = field(default_factory=list)
    error: Optional[str] = None  # the file could not be processed at all

    @property
    def invalid_rows(self) -> int:
        return len({error.row for error in self.errors})

    def to_document(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.key,
            "rows": self.rows,
            "valid": len(self.papers),
            "invalid": self.invalid_rows,
            "error": self.error,
        }


def classify(filename: str, config: PipelineConfig) -> Optional[PaperKind]:
    if config.input_files_regex and not re.match(config.input_files_regex, filename):
        return None
    for kind in config.kinds:
        pattern = config.file_patterns.get(kind.key)
        if pattern and re.match(pattern, filename):
            return kind
    return None


def discover_files(fs: FileSystem, config: PipelineConfig) -> Iterator[tuple[str, PaperKind]]:
    """Yield new input files and rotate processed ones.

    Processed files are renamed ``x.csv`` -> ``x.csv.old``; on the next run they
    become ``x.csv.old.old`` and on the run after that they are moved to ``old/``.
    """
    path = config.input_dir
    for name in fs.listdir(path):
        if name.endswith(PROCESSED_SUFFIX * 2):
            archive = fs.join(path, ARCHIVE_DIR)
            fs.makedirs(archive)
            fs.rename(fs.join(path, name), fs.join(archive, name[: -len(PROCESSED_SUFFIX * 2)]))
        elif name.endswith(PROCESSED_SUFFIX):
            fs.rename(fs.join(path, name), fs.join(path, name + PROCESSED_SUFFIX))
        else:
            kind = classify(name, config)
            if kind is not None:
                validation_logger.info(f"file {name} is submitted to validation.")
                yield name, kind


def read_rows(fs: FileSystem, path: str, delimiters: str) -> list[list[str]]:
    """Read a delimited file (first line is a header), values are kept verbatim."""
    with fs.open(path, mode="r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.readline()
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=delimiters).delimiter
        except csv.Error:
            delimiter = delimiters[0]
        handle.seek(0)
        # Values are not quoted in the source files, quotes are part of names (e.g. LLC "...").
        reader = csv.reader(handle, delimiter=delimiter, quoting=csv.QUOTE_NONE)
        next(reader, None)  # header
        return [row for row in reader if any(value.strip() for value in row)]


def validate_rows(rows: list[list[str]], kind: PaperKind, source: str) -> tuple[list[Paper], list[RowError]]:
    papers, errors = list(), list()
    for index, row in enumerate(rows):
        values = kind.model.group_nested(row)
        try:
            papers.append(kind.model.model_validate(values))
        except ValidationError as e:
            context = _short(values, MAX_CONTEXT_LENGTH)
            for detail in e.errors(include_url=False):
                errors.append(
                    RowError(
                        file=source,
                        kind=kind.key,
                        row=index + 1,
                        field=".".join(str(part) for part in detail["loc"]) or "(row)",
                        message=detail["msg"],
                        value=_short(detail.get("input"), MAX_VALUE_LENGTH),
                        context=context,
                    )
                )
            validation_logger.error(
                f'\n\t\tErrors in row {index + 1} of file "{source}":\n\n\t{e}\nContext:\n{values}'
            )
    return papers, errors


def load_file(fs: FileSystem, config: PipelineConfig, name: str, kind: PaperKind) -> FileResult:
    path = fs.join(config.input_dir, name)
    rows = read_rows(fs, path, config.csv_delimiters)
    papers, errors = validate_rows(rows, kind, name)
    validation_logger.info(f'"{name}": {len(papers)}/{len(rows)} rows are valid.')
    fs.rename(path, path + PROCESSED_SUFFIX)  # mark the file as exhausted
    return FileResult(name=name, kind=kind, papers=papers, rows=len(rows), errors=errors)


def ingest(fs: FileSystem, config: PipelineConfig) -> list[FileResult]:
    results = list()
    for name, kind in list(discover_files(fs, config)):
        try:
            results.append(load_file(fs, config, name, kind))
        except Exception as e:
            validation_logger.error(f'File "{name}" raised exception {e!r}')
            results.append(FileResult(name=name, kind=kind, error=repr(e)))
    return results

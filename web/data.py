"""Read side of the dashboard: everything here is synchronous and runs in worker threads."""

import json
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from application import reports
from application.pipeline_config import Department, PipelineConfig
from application.storage import Repository
from models.paper import stringify
from models.registry import KINDS_BY_KEY, PAPER_KINDS, PaperKind

KIND_LABELS = {
    "declaration": "Declarations",
    "declarationupdates": "Declaration corrections",
    "clearancestatement": "Clearance statements",
    "waybill": "Waybills",
}
DEPARTMENT_LABELS = {
    Department.COMMON: "Common",
    Department.IMPORT: "Import department",
    Department.EXPORT: "Export department",
}
STATUS_LABELS = {
    "ok": "OK",
    "no_new_records": "No new records",
    "storage_unavailable": "Storage unavailable",
    "failed": "Failed",
}
ERROR_COLUMNS = [
    {"title": "File", "field": "file", "headerFilter": "input"},
    {"title": "Type", "field": "kind", "headerFilter": "input"},
    {"title": "Row", "field": "row", "hozAlign": "right", "sorter": "number"},
    {"title": "Field", "field": "field", "headerFilter": "input"},
    {"title": "Message", "field": "message", "headerFilter": "input", "widthGrow": 3},
    {"title": "Value", "field": "value", "headerFilter": "input", "widthGrow": 2},
]
RUN_COLUMNS = [
    {"title": "Started", "field": "started", "sorter": "string"},
    {"title": "Status", "field": "status_label", "headerFilter": "input"},
    {"title": "Files", "field": "file_count", "hozAlign": "right", "sorter": "number"},
    {"title": "Valid rows", "field": "valid_rows", "hozAlign": "right", "sorter": "number"},
    {"title": "Invalid rows", "field": "invalid_rows", "hozAlign": "right", "sorter": "number"},
    {"title": "Stored", "field": "stored_total", "hozAlign": "right", "sorter": "number"},
    {"title": "Reports", "field": "report_count", "hozAlign": "right", "sorter": "number"},
    {"title": "Message", "field": "message", "widthGrow": 2},
]


def format_time(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def decorate_run(run: dict) -> dict:
    """Add display fields to a journal entry."""
    run = dict(run)
    run["started"] = format_time(run.get("started_at"))
    run["finished"] = format_time(run.get("finished_at"))
    run["status_label"] = STATUS_LABELS.get(run.get("status"), run.get("status"))
    run["file_count"] = len(run.get("files") or [])
    run["stored_total"] = sum((run.get("stored") or {}).values())
    run["report_count"] = len(run.get("exported") or [])
    return run


def record_columns(kind: PaperKind) -> list[dict]:
    return [{"title": leaf.title, "field": leaf.column, "headerFilter": "input"} for leaf in kind.model.leaf_fields()]


class DepartmentCache:
    """Routing of the stored records, recomputed at most every ``ttl`` seconds per document type."""

    def __init__(self, ttl: float = 60.0):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, dict[Department, pd.DataFrame]]] = dict()

    def routed(self, repository: Repository, config: PipelineConfig, kind: PaperKind) -> dict[Department, pd.DataFrame]:
        with self._lock:
            entry = self._entries.get(kind.key)
            if entry and time.monotonic() - entry[0] < self.ttl:
                return entry[1]
        since = datetime.now(timezone.utc) - timedelta(days=config.days_to_fetch)
        documents = repository.fetch_since(kind.key, since)
        frame = pd.DataFrame.from_records(
            [[stringify(value) for value in kind.model.flatten_document(document)] for document in documents],
            columns=[leaf.column for leaf in kind.model.leaf_fields()],
        )
        routed = reports.route(frame, kind.sort_column, config.routing_patterns)
        with self._lock:
            self._entries[kind.key] = (time.monotonic(), routed)
        return routed

    def counts(self, repository: Repository, config: PipelineConfig) -> dict[Department, dict[str, int]]:
        result: dict[Department, dict[str, int]] = {department: dict() for department in Department}
        for kind in PAPER_KINDS:
            for department, frame in self.routed(repository, config, kind).items():
                result[department][kind.key] = len(frame)
        return result

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def dashboard(repository: Repository, config: PipelineConfig, cache: DepartmentCache) -> dict:
    runs = [decorate_run(run) for run in repository.list_runs(limit=10)]
    last_run = runs[0] if runs else None
    last_import = next((run for run in runs if run["file_count"]), None)
    last_export = next((run for run in runs if run.get("routed")), None)
    return {
        "runs": runs,
        "last_run": last_run,
        "last_import": last_import,
        "last_export": last_export,
        "totals": {kind.key: repository.count(kind.key) for kind in PAPER_KINDS},
        "window": cache.counts(repository, config),
        "days": config.days_to_fetch,
    }


def errors_frame(repository: Repository, run_ids: list[str]) -> pd.DataFrame:
    errors = repository.run_errors(run_ids)
    columns = ["id", "run_id", "file", "kind", "row", "field", "message", "value"]
    frame = pd.DataFrame.from_records([{c: e.get(c) for c in columns} for e in errors], columns=columns)
    frame["kind"] = frame["kind"].map(lambda key: KIND_LABELS.get(key, key))
    return frame


def error_detail(repository: Repository, error_id: str) -> Optional[dict]:
    error = repository.get_error(error_id)
    if error is None:
        return None
    try:
        error["context_pretty"] = json.dumps(json.loads(error.get("context") or "null"), ensure_ascii=False, indent=2)
    except ValueError:
        error["context_pretty"] = error.get("context") or ""
    return error


# --------------------------------------------------------------- remote grid
_PARAM = re.compile(r"^(sort|filter)\[(\d+)\]\[(\w+)\]$")


def grid_params(args) -> tuple[int, int, list[dict], list[dict]]:
    """Parse Tabulator remote-mode query parameters (page, size, sort[i][..], filter[i][..])."""
    groups: dict[str, dict[int, dict]] = {"sort": {}, "filter": {}}
    items = args.items(multi=True) if hasattr(args, "getlist") else args.items()  # MultiDict or dict
    for key, value in items:
        match = _PARAM.match(key)
        if match:
            groups[match.group(1)].setdefault(int(match.group(2)), {})[match.group(3)] = value
    try:
        page = max(int(args.get("page", 1)), 1)
        size = min(max(int(args.get("size", 50)), 1), 1000)
    except (TypeError, ValueError):
        page, size = 1, 50
    return page, size, [groups["sort"][i] for i in sorted(groups["sort"])], [groups["filter"][i] for i in sorted(groups["filter"])]


def _json_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    return value


def paginate(frame: pd.DataFrame, args) -> dict:
    page, size, sorters, filters = grid_params(args)
    for spec in filters:
        column, needle = spec.get("field"), str(spec.get("value", ""))
        if column in frame.columns and needle:
            values = frame[column].astype(str)
            if spec.get("type") == "=":
                frame = frame[values == needle]
            else:
                frame = frame[values.str.contains(needle, case=False, regex=False, na=False)]
    valid = [s for s in sorters if s.get("field") in frame.columns]
    if valid:
        frame = frame.sort_values(
            by=[s["field"] for s in valid],
            ascending=[s.get("dir", "asc") != "desc" for s in valid],
            kind="stable",
            key=lambda column: column if pd.api.types.is_numeric_dtype(column) else column.astype(str).str.lower(),
        )
    total = len(frame)
    window = frame.iloc[(page - 1) * size : page * size]
    data = [{key: _json_value(value) for key, value in row.items()} for row in window.to_dict(orient="records")]
    return {"last_page": max(math.ceil(total / size), 1), "last_row": total, "data": data}


def kind_or_none(key: str) -> Optional[PaperKind]:
    return KINDS_BY_KEY.get(key)


def department_or_none(value: str) -> Optional[Department]:
    try:
        return Department(value)
    except ValueError:
        return None

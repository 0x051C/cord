from quart import Blueprint, abort, jsonify, render_template, request
from quart.utils import run_sync

from application.pipeline_config import Department
from models.registry import PAPER_KINDS
from web import data, state

blueprint = Blueprint("ui", __name__)


def _common() -> dict:
    return {
        "kinds": PAPER_KINDS,
        "departments": list(Department),
        "kind_labels": data.KIND_LABELS,
        "department_labels": data.DEPARTMENT_LABELS,
    }


async def _in_thread(function, *args):
    return await run_sync(function)(*args)


# ------------------------------------------------------------------ pages
@blueprint.get("/healthz")
async def healthz():
    return "ok"


@blueprint.get("/")
async def dashboard():
    ctx = state()
    view = await _in_thread(data.dashboard, ctx.repository, ctx.config, ctx.cache)
    return await render_template("dashboard.html", view=view, **_common())


@blueprint.get("/partials/dashboard")
async def dashboard_partial():
    ctx = state()
    view = await _in_thread(data.dashboard, ctx.repository, ctx.config, ctx.cache)
    return await render_template("partials/dashboard.html", view=view, **_common())


@blueprint.get("/runs")
async def runs():
    return await render_template("runs.html", columns=data.RUN_COLUMNS, **_common())


@blueprint.get("/runs/<run_id>")
async def run_detail(run_id: str):
    run = await _in_thread(state().repository.get_run, run_id)
    if run is None:
        abort(404)
    return await render_template(
        "run.html", run=data.decorate_run(run), error_columns=data.ERROR_COLUMNS, **_common()
    )


@blueprint.get("/errors")
async def errors():
    runs = await _in_thread(state().repository.list_runs, 50)
    runs = [data.decorate_run(run) for run in runs if run.get("error_count")]
    selected = request.args.get("run") or (runs[0]["id"] if runs else "")
    return await render_template(
        "errors.html", runs=runs, selected=selected, error_columns=data.ERROR_COLUMNS, **_common()
    )


@blueprint.get("/partials/errors/<error_id>")
async def error_detail(error_id: str):
    error = await _in_thread(data.error_detail, state().repository, error_id)
    if error is None:
        abort(404)
    return await render_template("partials/error_detail.html", error=error, **_common())


@blueprint.get("/departments")
async def departments():
    department = data.department_or_none(request.args.get("department", Department.COMMON.value))
    kind = data.kind_or_none(request.args.get("kind", PAPER_KINDS[2].key))
    if department is None or kind is None:
        abort(404)
    return await render_template("departments.html", **await _department_view(department, kind))


@blueprint.get("/partials/departments/<department>/<kind>")
async def department_partial(department: str, kind: str):
    dept, paper_kind = data.department_or_none(department), data.kind_or_none(kind)
    if dept is None or paper_kind is None:
        abort(404)
    return await render_template("partials/department.html", **await _department_view(dept, paper_kind))


async def _department_view(department, kind) -> dict:
    ctx = state()
    counts = await _in_thread(ctx.cache.counts, ctx.repository, ctx.config)
    return {
        "department": department,
        "kind": kind,
        "counts": counts,
        "columns": data.record_columns(kind),
        "days": ctx.config.days_to_fetch,
        **_common(),
    }


# -------------------------------------------------------------- grid data
@blueprint.get("/api/runs")
async def api_runs():
    runs = await _in_thread(state().repository.list_runs, 500)
    return jsonify([data.decorate_run(run) for run in runs])


@blueprint.get("/api/errors")
async def api_errors():
    run_ids = [run_id for run_id in request.args.getlist("run") if run_id]
    if not run_ids:
        return jsonify({"last_page": 1, "last_row": 0, "data": []})
    frame = await _in_thread(data.errors_frame, state().repository, run_ids)
    return jsonify(data.paginate(frame, request.args))


@blueprint.get("/api/departments/<department>/<kind>")
async def api_department_records(department: str, kind: str):
    dept, paper_kind = data.department_or_none(department), data.kind_or_none(kind)
    if dept is None or paper_kind is None:
        abort(404)
    ctx = state()
    routed = await _in_thread(ctx.cache.routed, ctx.repository, ctx.config, paper_kind)
    return jsonify(data.paginate(routed[dept], request.args))

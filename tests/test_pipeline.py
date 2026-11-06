import json
import os

import pandas as pd

from application import pipeline, reports
from application.pipeline_config import Department
from application.storage import StorageError
from models.registry import PAPER_KINDS


def seed_inputs(generator, config, rows=20, invalid_ratio=0.1):
    for kind in PAPER_KINDS:
        generator.write_csv(config.input_dir, kind, rows, invalid_ratio=invalid_ratio)


def test_full_run(generator, pipeline_config, fs, repository):
    seed_inputs(generator, pipeline_config)
    report = pipeline.run(config=pipeline_config, fs=fs, repository=repository)

    assert len(report.files) == len(PAPER_KINDS)
    assert report.invalid_rows == 2 * len(PAPER_KINDS)
    assert report.valid_rows == 18 * len(PAPER_KINDS)
    assert report.stored == {kind.key: 18 for kind in PAPER_KINDS}
    assert len(report.exported) == len(PAPER_KINDS) * len(Department)
    assert all(os.path.exists(path) for path in report.exported)

    # processed files are marked, errors and logs are supplied next to the reports
    assert all(name.endswith(".csv.old") for name in os.listdir(pipeline_config.input_dir))
    log = open(os.path.join(pipeline_config.log_dir, "validation.log"), encoding="utf-8").read()
    assert log.count("Errors in row") == report.invalid_rows
    for folder in pipeline_config.output_dirs.values():
        assert "validation.log" in os.listdir(folder)

    # exported spreadsheets are flat, one column per leaf field
    declaration_report = next(p for p in report.exported if os.path.basename(p).startswith("gtd_1"))
    frame = pd.read_excel(declaration_report)
    assert list(frame.columns) == PAPER_KINDS[2].model.flat_titles()


def test_second_run_has_nothing_new(generator, pipeline_config, fs, repository):
    seed_inputs(generator, pipeline_config)
    pipeline.run(config=pipeline_config, fs=fs, repository=repository)
    report = pipeline.run(config=pipeline_config, fs=fs, repository=repository)
    assert report.valid_rows == 0 and report.exported == []
    assert all(name.endswith(".csv.old.old") for name in os.listdir(pipeline_config.input_dir))

    pipeline.run(config=pipeline_config, fs=fs, repository=repository)
    assert os.listdir(pipeline_config.input_dir) == ["old"]
    assert len(os.listdir(os.path.join(pipeline_config.input_dir, "old"))) == len(PAPER_KINDS)


class UnreachableRepository:
    def ping(self):
        raise StorageError("connection refused")

    def close(self):
        pass


def test_storage_unavailable_dumps_records(generator, pipeline_config, fs):
    seed_inputs(generator, pipeline_config, rows=5, invalid_ratio=0)
    report = pipeline.run(config=pipeline_config, fs=fs, repository=UnreachableRepository())
    assert report.fallback_dump and report.exported == []
    dump = json.load(open(report.fallback_dump, encoding="utf-8"))
    assert len(dump["paper_list"]) == 5 * len(PAPER_KINDS)


def test_routing():
    frame = pd.DataFrame({"op_type": ["ИМ40", "ЭК10", "ЭК11", None]})
    routed = reports.route(
        frame,
        "op_type",
        {Department.IMPORT: "^.*(ИМ40).*$", Department.EXPORT: "^.*(ЭК10).*$", Department.COMMON: None},
    )
    assert routed[Department.IMPORT]["op_type"].tolist() == ["ИМ40"]
    assert routed[Department.EXPORT]["op_type"].tolist() == ["ЭК10"]
    assert routed[Department.COMMON].empty


def test_clear_marker_truncates_logs(generator, pipeline_config, fs, repository):
    seed_inputs(generator, pipeline_config, rows=3)
    open(os.path.join(pipeline_config.input_dir, pipeline.CLEAR_LOGS_MARKER), "w").close()
    pipeline.run(config=pipeline_config, fs=fs, repository=repository)
    assert os.path.getsize(os.path.join(pipeline_config.log_dir, "validation.log")) == 0
    assert os.path.getsize(os.path.join(pipeline_config.output_dirs[Department.COMMON], "validation.log")) > 0

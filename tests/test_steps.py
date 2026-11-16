"""The ETL split into steps (application/steps.py), as the Airflow tasks run it."""

import json
import os

import pytest

from application import steps
from application.pipeline import STATUS_FAILED, STATUS_NO_NEW_RECORDS, STATUS_OK, STATUS_STORAGE_UNAVAILABLE
from application.pipeline_config import Department
from application.storage import StorageError
from models.registry import PAPER_KINDS

from tests.test_pipeline import UnreachableRepository, seed_inputs


def run_steps(pipeline_config, fs, repository):
    """All steps in order, each one only seeing the stage file path (like separate processes)."""
    stage = steps.extract(config=pipeline_config, fs=fs)
    steps.load(stage, config=pipeline_config, repository=repository)
    steps.publish(stage, config=pipeline_config, fs=fs, repository=repository)
    steps.deliver_logs(config=pipeline_config, fs=fs)
    return stage, steps.record(stage, config=pipeline_config, repository=repository)


def test_steps_do_what_a_full_run_does(generator, pipeline_config, fs, repository):
    seed_inputs(generator, pipeline_config)
    stage, report = run_steps(pipeline_config, fs, repository)

    assert report.status == STATUS_OK
    assert report.valid_rows == 18 * len(PAPER_KINDS)
    assert report.invalid_rows == 2 * len(PAPER_KINDS)
    assert report.stored == {kind.key: 18 for kind in PAPER_KINDS}
    assert len(report.exported) == len(PAPER_KINDS) * len(Department)
    assert all(os.path.exists(path) for path in report.exported)
    for folder in pipeline_config.output_dirs.values():
        assert "validation.log" in os.listdir(folder)

    # the dashboard sees the run and its validation errors; the stage file is cleaned up
    saved = repository.get_run(report.id)
    assert saved["status"] == STATUS_OK and saved["error_count"] == report.invalid_rows
    assert len(repository.run_errors([report.id])) == len(report.errors)
    assert not os.path.exists(stage)


def test_stage_round_trip(generator, pipeline_config, fs):
    seed_inputs(generator, pipeline_config, rows=5)
    stage = steps.read_stage(steps.extract(config=pipeline_config, fs=fs))
    path = steps.write_stage(pipeline_config.staging_dir, stage)
    again = steps.read_stage(path)
    assert again.report.to_document() == stage.report.to_document()
    assert again.report.errors == stage.report.errors
    assert again.documents == stage.documents


def test_retrying_load_and_publish_does_not_duplicate(generator, pipeline_config, fs, repository):
    seed_inputs(generator, pipeline_config, rows=5, invalid_ratio=0)
    stage = steps.extract(config=pipeline_config, fs=fs)
    for _ in range(2):
        assert steps.load(stage, config=pipeline_config, repository=repository) == STATUS_OK
        steps.publish(stage, config=pipeline_config, fs=fs, repository=repository)
    assert {kind.key: repository.count(kind.key) for kind in PAPER_KINDS} == {kind.key: 5 for kind in PAPER_KINDS}


def test_load_raises_until_the_last_attempt_then_dumps(generator, pipeline_config, fs):
    seed_inputs(generator, pipeline_config, rows=5, invalid_ratio=0)
    stage = steps.extract(config=pipeline_config, fs=fs)

    with pytest.raises(StorageError):  # an earlier attempt: let the scheduler retry
        steps.load(stage, config=pipeline_config, repository=UnreachableRepository(), allow_fallback=False)
    assert steps.read_stage(stage).report.status == steps.STATUS_RUNNING

    status = steps.load(stage, config=pipeline_config, repository=UnreachableRepository(), allow_fallback=True)
    assert status == STATUS_STORAGE_UNAVAILABLE
    dump = json.load(open(steps.read_stage(stage).report.fallback_dump, encoding="utf-8"))
    assert len(dump["paper_list"]) == 5 * len(PAPER_KINDS)

    # publishing is skipped, the stage file is kept (it still holds the records)
    assert steps.publish(stage, config=pipeline_config, fs=fs, repository=UnreachableRepository()) == 0
    report = steps.record(stage, config=pipeline_config, repository=UnreachableRepository())
    assert report.status == STATUS_STORAGE_UNAVAILABLE and os.path.exists(stage)


def test_no_new_records(pipeline_config, fs, repository):
    os.makedirs(pipeline_config.input_dir)
    stage, report = run_steps(pipeline_config, fs, repository)
    assert report.status == STATUS_NO_NEW_RECORDS and report.exported == []
    assert repository.get_run(report.id)["status"] == STATUS_NO_NEW_RECORDS


def test_record_marks_an_unfinished_run_as_failed(generator, pipeline_config, fs, repository):
    seed_inputs(generator, pipeline_config, rows=3)
    stage = steps.extract(config=pipeline_config, fs=fs)
    # `load` failed for good: record() still journals the run, as failed, and keeps the stage file
    report = steps.record(stage, config=pipeline_config, repository=repository)
    assert report.status == STATUS_FAILED and "storing" in report.message
    assert repository.get_run(report.id)["status"] == STATUS_FAILED
    assert os.path.exists(stage)


def test_record_without_a_stage_file(pipeline_config, repository):
    report = steps.record(None, config=pipeline_config, repository=repository)
    assert report.status == STATUS_FAILED and repository.get_run(report.id) is not None

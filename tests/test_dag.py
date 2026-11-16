"""Structure of the Airflow DAG (dags/cord_etl.py). Skipped unless Airflow is installed.

    .venv-airflow/bin/python -m pytest tests/test_dag.py
"""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("airflow")

DAG_FILE = Path(__file__).resolve().parent.parent / "dags" / "cord_etl.py"


@pytest.fixture(scope="module")
def dag():
    spec = importlib.util.spec_from_file_location("cord_etl_dag", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.dag


def test_tasks_and_order(dag):
    assert dag.dag_id == "cord_etl"
    assert set(dag.task_ids) == {"extract", "load", "has_new_records", "publish", "deliver_logs", "record"}

    def upstream(task_id):
        return set(dag.get_task(task_id).upstream_task_ids)

    assert upstream("load") == {"extract"}
    assert upstream("has_new_records") == {"load"}
    assert upstream("publish") == {"extract", "has_new_records"}
    assert upstream("deliver_logs") == {"publish"}
    assert upstream("record") == {"deliver_logs"}


def test_failure_handling(dag):
    assert dag.max_active_runs == 1 and not dag.catchup
    assert dag.get_task("extract").retries == 0  # input files are renamed once read
    assert dag.get_task("load").retries == 3
    assert dag.get_task("deliver_logs").trigger_rule == "all_done"
    assert dag.get_task("record").trigger_rule == "all_done"


def test_parsing_does_not_import_the_application(dag):
    # the scheduler parses the file often; heavy imports belong inside the tasks
    source = DAG_FILE.read_text(encoding="utf-8")
    top_level = source.split("def cord_etl")[0]
    assert "import application" not in top_level and "from application" not in top_level

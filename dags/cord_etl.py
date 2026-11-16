"""
### cord ETL

Customs declarations, their updates, clearance statements and waybills arrive as
`^`-delimited files. Each run validates them with the Pydantic models, stores the
valid records and exports per-department xlsx reports.

| task | what it does | retries |
|---|---|---|
| `extract` | reads and validates new input files, marks them processed, writes the run's stage file | none: files are renamed once read |
| `load` | stores the validated records (MongoDB or SQLite) | 3; the last attempt dumps the records to JSON if storage is still down |
| `has_new_records` | skips `publish` when nothing was stored | |
| `publish` | routes recent records to departments, exports xlsx | 2 |
| `deliver_logs` | copies the logs next to the reports | runs even if a step failed |
| `record` | saves the run to the journal shown by the dashboard | runs even if a step failed |

The steps live in `application/steps.py`; `python main.py run` does the same work in one process.
Settings come from the `CORD_ENV` profile of the worker environment (`local` = sandbox + SQLite).
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.sdk import TriggerRule, dag, get_current_context, task
from airflow.sdk.exceptions import AirflowFailException

# The project root holds the `application` and `models` packages imported by the tasks.
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

LOAD_RETRIES = 3


@dag(
    dag_id="cord_etl",
    schedule=os.environ.get("CORD_SCHEDULE", "@hourly"),
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,  # runs rename input files: never two at once
    default_args={"owner": "cord", "retries": 0},
    tags=["cord", "etl"],
    doc_md=__doc__,
)
def cord_etl():
    # application modules read the settings at import time, so they are imported inside the
    # tasks: the scheduler parses this file often and must not load pandas, pydantic, etc.

    @task
    def extract() -> str:
        from application import steps

        return steps.extract()

    @task(retries=LOAD_RETRIES, retry_delay=timedelta(minutes=1))
    def load(stage_path: str) -> str:
        from application import steps

        ti = get_current_context()["ti"]
        last_attempt = ti.try_number > LOAD_RETRIES
        return steps.load(stage_path, allow_fallback=last_attempt)

    @task.short_circuit(ignore_downstream_trigger_rules=False)
    def has_new_records(status: str) -> bool:
        return status == "ok"

    @task(retries=2, retry_delay=timedelta(minutes=1))
    def publish(stage_path: str) -> int:
        from application import steps

        return steps.publish(stage_path)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def deliver_logs() -> None:
        from application import steps

        steps.deliver_logs()

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def record() -> str:
        from application import steps

        # pulled by hand: when `extract` failed there is no stage file, and the run is still recorded
        stage_path = get_current_context()["ti"].xcom_pull(task_ids="extract")
        report = steps.record(stage_path)
        print(report.summary())
        if report.status == "failed":
            # `record` is the last task: without this the DAG run would show as successful
            raise AirflowFailException(f"cord run {report.id} failed: {report.message}")
        return report.status

    stage_path = extract()
    status = load(stage_path)
    published = publish(stage_path)
    has_new_records(status) >> published
    published >> deliver_logs() >> record()


dag = cord_etl()

import os

# Must be set before anything imports the settings (models read them at import time).
os.environ.setdefault("CORD_ENV", "local")

from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from application.configuration_handling import settings  # noqa: E402
from application.filesystem import LocalFileSystem  # noqa: E402
from application.mock_data import MockDataGenerator  # noqa: E402
from application.pipeline_config import Department, PipelineConfig  # noqa: E402
from application.storage.sqlite import SQLiteRepository  # noqa: E402
from models.declaration import Declaration  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent


@pytest.fixture
def decl_test_line() -> dict:
    lines = (TESTS_DIR / "test_line.txt").read_text(encoding="utf-8").splitlines()
    return Declaration.group_nested(lines)


@pytest.fixture
def generator() -> MockDataGenerator:
    return MockDataGenerator(seed=1234)


@pytest.fixture
def pipeline_config(tmp_path) -> PipelineConfig:
    config = PipelineConfig.from_settings(settings)
    return replace(
        config,
        input_dir=str(tmp_path / "input"),
        output_dirs={department: str(tmp_path / "output" / department.value) for department in Department},
        log_dir=str(tmp_path / "logs"),
        fallback_dump_dir=str(tmp_path),
        staging_dir=str(tmp_path / "staging"),
    )


@pytest.fixture
def fs() -> LocalFileSystem:
    return LocalFileSystem()


@pytest.fixture
def repository(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    yield repo
    repo.close()

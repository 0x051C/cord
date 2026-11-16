from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from application.configuration_handling import resolve_path
from models.registry import PAPER_KINDS, PaperKind


class Department(str, Enum):
    COMMON = "common"
    IMPORT = "impdiv"
    EXPORT = "expdiv"


@dataclass
class PipelineConfig:
    input_dir: str
    output_dirs: dict[Department, str]
    routing_patterns: dict[Department, Optional[str]]
    file_patterns: dict[str, str]  # kind key -> file name regex
    output_filenames: dict[str, str]  # kind key -> xlsx name template
    log_dir: str
    fallback_dump_dir: str
    staging_dir: str = "staging"  # run state shared by the Airflow tasks (application/steps.py)
    input_files_regex: Optional[str] = None
    csv_delimiters: str = "^"
    days_to_fetch: int = 180
    kinds: tuple[PaperKind, ...] = field(default=PAPER_KINDS)

    @classmethod
    def from_settings(cls, settings) -> "PipelineConfig":
        local = str(settings.get("filesystem", "smb")).lower() == "local"

        def path(value):
            return resolve_path(value) if local else str(value)

        return cls(
            input_dir=path(settings.input_files_path),
            output_dirs={
                Department.COMMON: path(settings.xlsx_path_common),
                Department.IMPORT: path(settings.xlsx_path_impdiv),
                Department.EXPORT: path(settings.xlsx_path_expdiv),
            },
            routing_patterns={
                Department.COMMON: settings.get("re_for_both"),
                Department.IMPORT: settings.get("re_for_impdiv"),
                Department.EXPORT: settings.get("re_for_expdiv"),
            },
            file_patterns={kind.key: settings.get(kind.file_regex_setting) for kind in PAPER_KINDS},
            output_filenames={
                kind.key: settings.get(kind.output_filename_setting, kind.default_output_filename)
                for kind in PAPER_KINDS
            },
            # logs, the fallback dump and the Airflow run state are always written locally
            log_dir=resolve_path(settings.get("log_dir", ".")),
            fallback_dump_dir=resolve_path(settings.get("fallback_dump_path", ".")),
            staging_dir=resolve_path(settings.get("staging_path", "staging")),
            input_files_regex=settings.get("input_files_regex"),
            csv_delimiters=settings.get("csv_delimiters", "^"),
            days_to_fetch=int(settings.get("days_to_fetch", 180)),
        )

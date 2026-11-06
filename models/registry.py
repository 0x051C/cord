"""Every document type handled by the application and how it is processed."""

from dataclasses import dataclass

from models.declaration import Declaration, DeclarationUpdates
from models.paper import Paper
from models.statement import ClearanceStatement
from models.waybill import Waybill


@dataclass(frozen=True)
class PaperKind:
    key: str  # storage collection / table name
    model: type[Paper]
    file_regex_setting: str  # setting holding the input file name pattern
    sort_column: str  # column used to route records to departments
    output_filename_setting: str  # setting holding the xlsx name template ({0} - from, {1} - to)
    default_output_filename: str
    file_prefix: str  # prefix used for generated (mock) input files

    @property
    def title(self) -> str:
        return self.model.__name__


# Order matters for file classification: updates (gtd_korrekt_*) before declarations (gtd_*).
PAPER_KINDS: tuple[PaperKind, ...] = (
    PaperKind(
        key="declarationupdates",
        model=DeclarationUpdates,
        file_regex_setting="re_updates",
        sort_column="op_type",
        output_filename_setting="declaration_updates_output_filename",
        default_output_filename="gtd_updates_{0} — {1}",
        file_prefix="gtd_korrekt_",
    ),
    PaperKind(
        key="clearancestatement",
        model=ClearanceStatement,
        file_regex_setting="re_statement",
        sort_column="mode_of_operation",
        output_filename_setting="clearance_statement_output_filename",
        default_output_filename="euro_{0} — {1}",
        file_prefix="euro_",
    ),
    PaperKind(
        key="declaration",
        model=Declaration,
        file_regex_setting="re_declaration",
        sort_column="op_type",
        output_filename_setting="declaration_output_filename",
        default_output_filename="gtd_{0} — {1}",
        file_prefix="gtd_",
    ),
    PaperKind(
        key="waybill",
        model=Waybill,
        file_regex_setting="re_waybill",
        sort_column="stated_goal",
        output_filename_setting="waybill_output_filename",
        default_output_filename="ttn_{0} — {1}",
        file_prefix="ttn_",
    ),
)

KINDS_BY_KEY: dict[str, PaperKind] = {kind.key: kind for kind in PAPER_KINDS}


def kind_of(paper: Paper) -> PaperKind:
    for kind in PAPER_KINDS:
        if type(paper) is kind.model:
            return kind
    raise KeyError(type(paper).__name__)

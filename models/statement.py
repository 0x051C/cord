import datetime
import re
from typing import Annotated, Any, List, Optional, Union

from pydantic import Field, field_validator

from application.configuration_handling import settings
from models.entity import Entity, StatementEntity
from models.invoice_amount import StatementInvoiceAmount
from models.logic.pydantic_helper import auto_enum, date_validation
from models.paper import Paper

StatementModeOfOperation = auto_enum("StatementModeOfOperation", settings.statement_mode)
FeacnString = Annotated[str, Field(min_length=settings.feacn_length)]


class ClearanceStatement(Paper):
    """
    Statements for goods worth no more than 1000 EUR,
    which cannot be declared with any other document (ClearanceStatement)

    Number
    Date
    Declarant's OKPO (classifier code)
    Declarant's name
    Declarant's address
    Sender's/receiver's OKPO
    Sender's/receiver's name
    Mode of operation
    Item name
    FEACN code
    Invoice value
    Currency code
    Value in roubles
    Item weight (kg)
    Supply contract
    Waybill (TTN, CMR, etc.)
    Commercial/financial documents (bill, tax invoice, invoice, etc.)
    Other documents
    Release for free circulation"""

    statement_id: str
    statement_date: datetime.datetime
    declarant: Union[Entity, dict, None] = Field(None, union_mode="left_to_right")  # len 3
    receiving: Union[StatementEntity, dict, None] = Field(None, union_mode="left_to_right")  # type: ignore[valid-type] # len 2
    mode_of_operation: StatementModeOfOperation = Field(title="Mode of Operation")  # type: ignore[valid-type]
    item_name: Union[List[str], str, None] = None
    feacn_code: Union[FeacnString, int]
    invoice: Union[StatementInvoiceAmount, dict, None] = Field(None, union_mode="left_to_right")  # type: ignore[valid-type]
    cost_in_rubles: Union[float, str] = Field(union_mode="left_to_right")
    item_weight: Union[float, str] = Field(union_mode="left_to_right")
    delivery_contract: Optional[str] = None
    waybill: Optional[str] = None
    commercial_finance_documents: Union[List[str], str]
    other_documents: Union[List[str], str]
    released_at: str

    @field_validator("statement_id")
    @classmethod
    def statement_id_validation(cls, v: str) -> str:
        match = re.match(settings.statement_id_pattern, v)
        if match is None:
            raise ValueError(settings.statement_id_date_msg)
        date_validation(day=1, month=1, year=int(match.group("year")))
        return v

    @field_validator("statement_date", mode="before")
    @classmethod
    def statement_date_check(cls, v: Any):
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v
        match = re.match("^" + settings.statement_date_format + "$", str(v))
        if not match:
            raise ValueError(settings.statement_date_check_failed_msg)
        return date_validation(
            day=int(match.group("day")),
            month=int(match.group("month")),
            year=int(match.group("year")),
        )

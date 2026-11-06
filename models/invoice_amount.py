from typing import Annotated, Union

from pydantic import Field

from application.configuration_handling import settings
from models.base import CordModel
from models.logic.pydantic_helper import auto_enum, reorder_fields

Alpha3CurrencyCodeEnum = auto_enum("Alpha3CurrencyCodeEnum", settings.allowed_currency_codes)


class InvoiceAmount(CordModel):
    # TODO: Convert to Decimal type for all values across the validation.
    value: Union[float, str, None] = Field(0.0, title="Invoice's Total Monetary Value", union_mode="left_to_right")
    currency_alpha3: Union[Alpha3CurrencyCodeEnum, str, None] = Field(  # type: ignore[valid-type]
        None, title="Currency Alpha-3 (3 digit) Code"
    )
    exchange_rate: Union[Annotated[float, Field(gt=0)], str, None] = Field(1.0, title="Exchange Rate", union_mode="left_to_right")


StatementInvoiceAmount = reorder_fields(
    InvoiceAmount, ["value", "currency_alpha3"], name="StatementInvoiceAmount"
)

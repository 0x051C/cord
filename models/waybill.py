import datetime
import re
from typing import Union

from pydantic import Field, field_validator

from application.configuration_handling import settings
from models.entity import WaybillBuyerEntity, WaybillSellerEntity
from models.item import WaybillItem
from models.paper import Paper


def parse_waybill_date(v):
    """``"22.06.2022"`` -> ``datetime(2022, 6, 22)``, empty string -> ``None``."""
    if v == "" or v is None:
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v
    try:
        d, m, y = re.match(settings.waybill_registration_date_regex, v).groupdict().values()  # type: ignore[union-attr]
        return datetime.datetime(day=int(d), month=int(m), year=int(y))
    except Exception as e:
        raise ValueError(
            settings.waybill_registration_date_failed_msg.format(v=v) + f"\tError details: \n\n{e}"
        )


class Waybill(Paper):
    id: str = Field(..., title="Waybill Registration Number")
    registration: Union[datetime.datetime, datetime.date] = Field(title="Registration Date")
    stated_goal: str = Field(..., title="Waybill Stated Transportation Goal")
    crossed_at: Union[datetime.datetime, datetime.date, None] = Field(None, title="Date of crossing the border")
    contract: str = Field("", title="Purchase contract")
    specification: str = Field("", title="Item Specifications")
    seller: WaybillSellerEntity = Field(title="Seller Entity")  # type: ignore[valid-type]
    seller_bank: str = Field("", title="Seller's Bank")
    sender_name: str = Field("", title="Sender's Name")
    sender_tax_payer_id: str = Field("", title="Sender's Tax Payer ID")
    sender_cargo_handling_terminal: str = Field("", title="Sender's Terminal")
    buyer: WaybillBuyerEntity = Field(title="Buyer Entity")  # type: ignore[valid-type]
    buyer_bank: str = Field(title="Buyer's Bank")
    receiver_name: str = Field(title="Receiver's Name")
    receiver_tax_payer_id: str = Field(title="Receiver's Tax Payer ID")
    receiver_cargo_handling_terminal: str = Field(title="Receiver's Terminal")
    currency: str = Field(title="Currency of Contract")
    item_name: str = Field(title="Name of Item")
    item: WaybillItem = Field(title="Item object")  # type: ignore[valid-type]
    price_in_national_currency: Union[str, float, None] = Field(None, title="Price in Roubles")
    correction_date: Union[datetime.datetime, datetime.date, None] = Field(None, title="Date of Correction")
    global_unique_identifier: str = Field(title="GUID")

    @field_validator("registration", "crossed_at", "correction_date", mode="before")
    @classmethod
    def date_conversion(cls, v):
        return parse_waybill_date(v)

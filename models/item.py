from typing import Optional, Union

from pydantic import Field

from application.configuration_handling import settings
from models.base import CordModel
from models.document import Document
from models.logic.pydantic_helper import reorder_fields


class Item(CordModel):
    feacn_code: Optional[str] = Field("", title="feacn_code", max_length=settings.feacn_length)
    procedure: str = Field(..., title="procedure")
    parent: Optional[str] = Field("", title="parent")
    item_price: Union[float, str, None] = Field(..., title="price", alias="price", union_mode="left_to_right")
    documents: Optional[Document] = Field(None, title="documents")


WaybillItem = reorder_fields(model=Item, order=["feacn_code", "item_price"], name="WaybillItem")

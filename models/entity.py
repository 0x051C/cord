from typing import Union

from models.base import CordModel
from models.logic.pydantic_helper import reorder_fields


class Entity(CordModel):
    """
    Description of a party named in the document (tax payer ID, name, address).
    """

    tax_payer_id: Union[None, int, str] = None
    name: str
    address: str


# Cosignor/Cosignee has a different field structure in every document type,
# the models reflect the column order of the source files.
StatementEntity = reorder_fields(model=Entity, order=["tax_payer_id", "name"], name="StatementEntity")
WaybillSellerEntity = reorder_fields(
    model=Entity, order=["name", "address", "tax_payer_id"], name="WaybillSellerEntity"
)
WaybillBuyerEntity = reorder_fields(
    model=Entity, order=["name", "tax_payer_id", "address"], name="WaybillBuyerEntity"
)

import re
from typing import Annotated, Optional, Union

from pydantic import Field, ValidationInfo, field_validator

import models.logic.validators as validators
from application.configuration_handling import settings
from models.bank import Bank
from models.country import Country, CountryOfOrigin, CountryOfTrade
from models.declaration_types_enum import DeclarationTypesEnum
from models.entity import Entity
from models.invoice_amount import InvoiceAmount
from models.item import Item
from models.paper import Paper

DecimalString = Annotated[str, Field(pattern=settings.decimal_places_regex)]


class Declaration(Paper):
    """
    #### Data model of a customs cargo declaration (GTD)
     Describes the data types and how they are validated during parsing.

    Attributes (Keyword Arguments):

        Customs regime;
        Declaration (GTD) number;
        Sender\\Additional;
        Receiver\\Additional;
        Responsible for financial settlement\\Additional;
        Trading country;
        Customs value;
        Country of departure\\export, its code;
        Country of origin;
        Invoice total (box 22);
        Currency;
        Exchange rate;
        Bank MFO (sort code);
        Bank name;
        Bank OKPO (classifier);
        FEACN code;
        Procedure;
        General declaration/preceding document;
        Item price;
        Document code;
        Document;
        Start date;
        End date;
        D/J mark;
    """

    #   Thought of moving common fields to Paper superclass,
    #   Terrible idea, all of the fields are in different order nothing is standardised.

    crud_type: str = Field("", title="CRUD Type")

    op_type: Union[DeclarationTypesEnum, str] = Field("", title="Operation Type")  # type: ignore[valid-type]

    declaration_id: str = Field(..., title="Declaration ID")

    sender: Optional[Entity] = Field(None, title="Sender Entity")
    sender_additional: Optional[Entity] = Field(None, title="Additional Sender Entity")

    receiver: Optional[Entity] = Field(None, title="Receiver Entity")
    receiver_additional: Optional[Entity] = Field(None, title="Additional Receiver Entity")

    financially_responsibe: Optional[Entity] = Field(None, title="Financially-responsible Entity")
    financially_responsibe_additional: Optional[Entity] = Field(
        None, title="Additional Financially-responsible Entity"
    )

    country_of_trade: Optional[CountryOfTrade] = Field(None, title="Country of Trade")  # type: ignore[valid-type]
    value_in_rub: Union[float, DecimalString, None] = Field(None, title="Value in Roubles", union_mode="left_to_right")
    country_of_departure: Optional[Country] = Field(None, title="Country of Departure")
    country_of_origin: Optional[CountryOfOrigin] = Field(None, title="Country of Origin")  # type: ignore[valid-type]
    invoice_value: Optional[InvoiceAmount] = Field(None, title="Total Invoice Amount")

    banking_information: Optional[Bank] = Field(None, title="Banking Information")

    item: Optional[Item] = Field(None, title="Item")
    timestamp: Optional[str] = Field(None, title="Item release timestamp")

    @field_validator("crud_type")
    @classmethod
    def validate_crud_type(cls, v: str) -> str:
        """Creation keywords are kept as-is (e.g. ``main``), other keywords map to their operation (``korrekt`` -> ``update``)."""
        crud_dict = settings.declaration_crud_allow_dict
        if v in validators.as_list(crud_dict.get("create")):
            return v
        for operation, keywords in crud_dict.items():
            if v in validators.as_list(keywords):
                return operation
        raise ValueError(f'Unknown operation type "{v}"')

    @field_validator("declaration_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        m = re.search(pattern=settings.declaration_id_pattern, string=v)
        if m is None:
            raise ValueError(settings.declaration_id_pattern_message)
        validators.validate_authority(
            regex_match=m,
            allow_list=settings.authority_allow_list,
            msg=settings.validate_id_authority_msg.format(authority=m.group("authority"), v=v),
        )
        validators.date_check(
            regex_match=m,
            msg=settings.validate_id_msg.format(
                date=".".join([m.group("day"), m.group("month"), m.group("year")]), v=v
            ),
        )
        return v

    @field_validator("sender_additional")
    @classmethod
    def sender_is_none(cls, v, info: ValidationInfo):
        if v is not None and info.data.get("sender") is None:
            raise ValueError(settings.sender_is_none_msg)
        return v

    @field_validator("receiver_additional")
    @classmethod
    def receiver_is_none(cls, v, info: ValidationInfo):
        if v is not None and info.data.get("receiver") is None:
            raise ValueError(settings.receiver_is_none_msg)
        return v

    @field_validator("financially_responsibe_additional")
    @classmethod
    def fin_responsible_is_none(cls, v, info: ValidationInfo):
        if v is not None and info.data.get("financially_responsibe") is None:
            raise ValueError(settings.fin_responsible_is_none_msg)
        return v


class DeclarationUpdates(Declaration):
    """Corrections of previously submitted declarations (``gtd_korrekt_*`` files)."""

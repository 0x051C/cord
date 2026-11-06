from re import match
from typing import Annotated

from pydantic import AfterValidator, Field

from application.configuration_handling import settings
from models.base import CordModel
from models.logic.pydantic_helper import reorder_fields
from models.logic.validators import as_list


def check_alpha2(v: str) -> str:
    if v is None or v == "":
        return v
    if match(settings.alpha2_regex, v) is None:
        raise ValueError(str(settings.alpha2_does_not_match_msg).format(v=v))
    if v not in as_list(settings.alpha2_codes):
        raise ValueError(str(settings.alpha2_not_found_msg).format(v=v))
    return v


Alpha2Code = Annotated[str, AfterValidator(check_alpha2)]


class Country(CordModel):
    name: str = Field(title="Name")
    code: Alpha2Code = Field(title="alpha-2 country code")


CountryOfTrade = reorder_fields(model=Country, order=["code"], name="CountryOfTrade")
CountryOfOrigin = reorder_fields(model=Country, order=["name"], name="CountryOfOrigin")

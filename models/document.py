import datetime
import re
from typing import Optional, Union

from pydantic import model_validator

from application.configuration_handling import settings
from models.base import CordModel


def doc_string_date_2_datetime(v):
    """``"26/02/19"`` -> ``datetime(2019, 2, 26)`` (format: ``document_date_format`` setting).

    Strings that do not match the format (e.g. empty ones) become ``None``.
    """
    if not isinstance(v, str):
        return v
    match = None
    for match in re.finditer(settings.document_date_format, v):
        pass
    if match is None:
        return None
    day, month, year = (int(match.group(g)) for g in ("day", "month", "year"))
    if not (day and month and year):
        return None
    if year < 100:
        year += 2000
    try:
        return datetime.datetime(day=day, month=month, year=year)
    except ValueError as e:
        raise ValueError(f"{v}: {e}")


class Document(CordModel):
    document_code: Optional[str] = None
    document: Optional[str] = None
    date_started: Union[datetime.datetime, str, None] = None
    date_ended: Union[datetime.datetime, str, None] = None

    @model_validator(mode="before")
    @classmethod
    def dates_check(cls, values):
        if not isinstance(values, dict) or "date_started" not in values or "date_ended" not in values:
            return values
        values = dict(values)
        date_started = doc_string_date_2_datetime(values["date_started"])
        date_ended = doc_string_date_2_datetime(values["date_ended"])
        if (
            isinstance(date_started, datetime.datetime)
            and isinstance(date_ended, datetime.datetime)
            and date_started > date_ended
        ):
            raise ValueError(
                settings.document_date_check_failed_msg.format(ds=date_started, de=date_ended)
            )
        values["date_started"] = date_started
        values["date_ended"] = date_ended
        return values

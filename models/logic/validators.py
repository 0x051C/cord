import re
from typing import Iterable, Union

import models.logic.pydantic_helper as pydantic_helper


def as_list(value: Union[str, Iterable[str], None]) -> list[str]:
    """Settings with a single value come back as a plain string, normalise to a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return [str(v) for v in value]


def validate_authority(
    regex_match: re.Match, allow_list, msg="Authority is not in allow list."
) -> None:
    if regex_match.group("authority") not in as_list(allow_list):
        raise ValueError("".join(msg))


def date_check(regex_match: re.Match, msg: str):
    year = int(regex_match.group("year"))
    if year < 100:  # two digit year, e.g. 21 -> 2021
        year += 2000
    try:
        return pydantic_helper.date_validation(
            day=int(regex_match.group("day")),
            month=int(regex_match.group("month")),
            year=year,
        )
    except ValueError:
        raise ValueError(msg)

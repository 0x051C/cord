"""
Validation settings, loaded by dynaconf (only UPPERCASE names become settings).

Values are read from ``validation.ini`` next to this file when it exists; the
fallbacks below are used otherwise. New settings can be appended with
``tools/add_setting.py``.
"""

import configparser
from pathlib import Path
from typing import Any, List, Union


def DO_NOTHING(args):
    return args


config = configparser.ConfigParser(interpolation=None, delimiters=":")
config.read(Path(__file__).resolve().parent / "validation.ini", encoding="utf-8-sig")


def custom_get(
    section: str = "Validation",
    option: str = "",
    fallback: Any = "",
    apply=lambda x: x.split(),
) -> Union[Any, List]:
    return_value = apply(config.get(section=section, option=option, fallback=fallback))
    if isinstance(return_value, (list, tuple)) and len(return_value) == 1:
        return return_value[0]
    return return_value


def as_list(x: Any) -> list:
    """Whitespace separated values -> list (always a list, even for one value)."""
    return x.split() if isinstance(x, str) else list(x)


def crud_dict_split(x: Any) -> dict:
    """``create:main\\nupdate:korrekt, korrect`` -> ``{"create": ["main"], "update": ["korrekt", "korrect"]}``"""
    if not isinstance(x, str):
        return x
    result = dict()
    for line in x.splitlines():
        if ":" not in line:
            continue
        key, values = line.split(":", 1)
        result[key.strip()] = [value.strip() for value in values.split(",") if value.strip()]
    return result


ALLOWED_CURRENCY_CODES = custom_get(
    option="currency_codes_allow_list", fallback="RUB UAH USD EUR", apply=as_list
)
DECIMAL_MARKS = custom_get(option="decimal_marks", fallback=",")
DECIMAL_PLACES = config.getint(section="Validation", option="decimal_places", fallback=2)
AUTHORITY_ALLOW_LIST = custom_get(
    option="authority_allow_list",
    fallback="700000000 700010000 700020000 700030000 700040000 700040300 700050000",
    apply=as_list,
)
DECLARATION_ID_PATTERN = custom_get(
    option="declaration_id_pattern",
    fallback=(
        r"^(?P<authority>700\d{6})/"
        r"(?P<day>\d{2})(?P<month>\d{2})(?P<year>\d{2})/"
        r"(?P<serial>\d{6})$"
    ),
    apply=lambda x: "".join(x).replace("\n", ""),
)
DECLARATION_ID_PATTERN_MESSAGE = custom_get(
    option="declaration_id_pattern_message",
    fallback="The declaration number does not match the format.",
    apply=DO_NOTHING,
)
FEACN_LENGTH = config.getint(section="Validation", option="feacn_length", fallback=10)
FEACN_CODE_REGEX = ""

DECLARATION_TYPES_ALLOW_LIST = custom_get(
    option="declaration_types_allow_list",
    # official customs codes as written in the source files (EK.. = export, IM.. = import, TR.. = transit)
    fallback="ЭК10 ЭК10П ЭК11 ИМ31 ЭК32 ИМ40 ИМ40В ИМ40П ИМ41 ИМ51 ЭК61 ИМ72 ЭК72 ИМ75 ТР80 ИМ00 ЭК00",
    apply=as_list,
)

ALPHA2_CODES = custom_get(option="alpha2_codes", fallback="RU UA XX", apply=as_list)

DECLARATION_CRUD_ALLOW_DICT = custom_get(
    option="declaration_crud_allow_dict",
    fallback={"create": ["main"], "update": ["korrekt", "korrect"]},
    apply=crud_dict_split,
)

DOCUMENT_DATE_FORMAT = custom_get(
    option="document_date_format",
    fallback=r"^(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{2})$",
)

STATEMENT_DATE_FORMAT = custom_get(
    option="clearance_statement_date_fromat",
    fallback=r"(?P<day>\d{2}).(?P<month>\d{2}).(?P<year>\d{4})",
)

STATEMENT_MODE = custom_get(
    option="clearance_statement_mode_of_operation_allow_list",
    # as written in the source files: import, export, re-import, re-export
    fallback="Импорт Экспорт Реимпорт Реэкспорт",
    apply=as_list,
)

STATEMENT_ID_PATTERN = custom_get(
    option="clearance_statement_id_pattern",
    fallback=r"700\d{6}/(?P<year>\d{4})/\d{6}",
    apply=lambda x: x.strip("\n"),
)

DECIMAL_PLACES_REGEX = custom_get(
    option="decimal_places_regex", fallback="[\\.,]\\d{2}(?!\\d)$"
)

DECIMAL_PLACES_MSG = custom_get(
    option="decimal_places_msg",
    fallback="Wrong number of digits after the decimal comma (or point).",
    apply=DO_NOTHING,
)

SENDER_IS_NONE_MSG = custom_get(
    option="sender_is_none_msg",
    fallback='The additional "Sender" field is filled while the main one is empty.',
    apply=DO_NOTHING,
)

# NB: the ini option keeps its historical spelling ("reciever").
RECEIVER_IS_NONE_MSG = custom_get(
    option="reciever_is_none_msg",
    fallback='The additional "Receiver" field is filled while the main one is empty.',
    apply=DO_NOTHING,
)

FIN_RESPONSIBLE_IS_NONE_MSG = custom_get(
    option="fin_responsible_is_none_msg",
    fallback='The additional "Party responsible for financial settlement" field is filled while the main one is empty.',
    apply=DO_NOTHING,
)

VALIDATE_ID_MSG = custom_get(
    option="validate_id_msg",
    fallback="Invalid value of the 2nd element of the declaration number ({date}) in {v}",
    apply=DO_NOTHING,
)

VALIDATE_ID_AUTHORITY_MSG = custom_get(
    option="validate_id_authority_msg",
    fallback="{v} - the issuing authority ({authority}) is not in the allow list.",
    apply=DO_NOTHING,
)

STATEMENT_DATE_CHECK_FAILED_MSG = custom_get(
    option="statement_date_check_failed_msg",
    fallback="Invalid statement date.",
    apply=DO_NOTHING,
)

ALPHA2_NOT_FOUND_MSG = custom_get(
    option="alpha2_not_found_msg",
    fallback='Country code "{v}" is not listed in the settings file.',
    apply=DO_NOTHING,
)

ALPHA2_DOES_NOT_MATCH_MSG = custom_get(
    option="alpha2_does_not_match_msg",
    fallback="{v} does not match the alpha-2 format.",
    apply=DO_NOTHING,
)

ALPHA2_REGEX = custom_get(option="alpha2_regex", fallback="^[A-Z]{2}$", apply=DO_NOTHING)

DOCUMENT_DATE_CHECK_FAILED_MSG = custom_get(
    option="document_date_check_failed_msg",
    fallback="The start date ({ds}) is later than the release date ({de})",
    apply=DO_NOTHING,
)

FEACN_CODE_TOO_LONG_MSG = custom_get(
    option="feacn_code_too_long_msg",
    fallback="The FEACN code has the wrong length.",
    apply=DO_NOTHING,
)

STATEMENT_ID_DATE_MSG = custom_get(
    option="statement_id_date_msg",
    fallback="The date in the statement number is invalid.",
    apply=DO_NOTHING,
)

WAYBILL_REGISTRATION_DATE_REGEX = custom_get(
    option="waybill_registration_date_regex",
    fallback="(?P<day>\\d{2}).(?P<month>\\d{2}).(?P<year>\\d{4})",
    apply=DO_NOTHING,
)

WAYBILL_REGISTRATION_DATE_FAILED_MSG = custom_get(
    option="waybill_registration_date_failed_msg",
    fallback="Registration date error, cannot extract the values from {v}",
    apply=DO_NOTHING,
)

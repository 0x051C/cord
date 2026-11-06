import datetime
from itertools import repeat

import pytest
from pydantic import ValidationError

from models.declaration import Declaration
from models.item import Item
from models.statement import ClearanceStatement
from models.waybill import Waybill

# Synthetic records: same layout and edge cases as the real exports, fictional content.
# Never paste real exports into tests or mock data.
STATEMENT_LINE = """700010000/2021/999123^12.05.2021^TEST1234^SP TESTOVA ANNA IVANOVNA^000004, Sampleton, 4 Test Lane, bld. 75^^LLC "Example Cargo"^Импорт^Graphics tablet, medium, Qty - 5 pcs.; Graphics tablet, small, Qty – 5 pcs.^84^1000.50^RUB^1050.75^8.75^No. 1/2020 from 10.08.2020 to 30.12.2021^CMR No. 13 of 27.04.2021;^No. 13 of 27.04.2021^Packing list No. 13 of 27.04.2021; Specification No. 1 of 23.04.2021; Payment order No. 32 of 08.04.2021^2021-05-12 16:16:30^
"""

WAYBILL_LINE = """1001^22.06.2022^Реализация^22.06.2022^12/21 of 10.12.2021^8 of 23.05.2022^LLC "EXAMPLE AGRO"^000005, Mockford, 5 Sample Ave.^TEST2001^TEST9001^LLC "EXAMPLE AGRO"^000005, Mockford, 5 Sample Ave.^TEST2001^LLC DEMO FARMS^TEST3001^000006, Demo City, 6 Field Rd.^TEST9002^LLC "DEMO FARMS"^TEST3001^000006, Demo City, 6 Field Rd.^RUB^Compound feed PK 6-6^2309^500000^250000^^0F1E2D3C4B5A69788796A5B4C3D2E1F00F1E2D3C4B5A69788796A5B4C3D2E1F0^"""


@pytest.fixture
def statement_test_line() -> dict:
    return ClearanceStatement.group_nested(STATEMENT_LINE.split("^"))


@pytest.fixture
def waybill_test_line() -> dict:
    return Waybill.group_nested(WAYBILL_LINE.split("^"))


def test_sparta_declaration():
    values = list(repeat("sparta" + "".join(repeat("a", (2**16) - len("spartaa"))), 42))
    with pytest.raises(ValidationError):
        Declaration.from_row(values)


def test_empty_constructor():
    with pytest.raises(ValidationError):
        Declaration()


def test_proper_declaration(decl_test_line):
    declaration = Declaration(**decl_test_line)
    Item(**decl_test_line["item"])
    assert declaration.declaration_id == "700040300/120521/999001"
    assert declaration.item.item_price == 1234567.0
    assert declaration.item.documents.date_started == datetime.datetime(2019, 2, 26)
    assert declaration.item.documents.date_ended == datetime.datetime(2021, 12, 31)


def test_group_nested_shape(decl_test_line):
    assert decl_test_line["sender"] == {
        "tax_payer_id": "",
        "name": 'LLC "EXAMPLE TRANSPORT COMPANY"',
        "address": "000001, Testville, 1 Example St., bld. 1, room 10",
    }
    assert decl_test_line["country_of_trade"] == {"code": "RU"}
    assert decl_test_line["country_of_origin"] == {"name": "UNKNOWN"}
    assert set(decl_test_line["item"]) == {"feacn_code", "procedure", "parent", "price", "documents"}
    assert decl_test_line["timestamp"] == "12.05.2021 14:09:45"


def test_declaration_id(decl_test_line):
    bad = dict(decl_test_line, declaration_id="700WRONGCODE/WRONG0/CODE00")
    with pytest.raises(ValidationError):
        Declaration(**bad)

    date = datetime.datetime.now().date()
    good = dict(decl_test_line, declaration_id=f"700000000/{date:%d%m%y}/000001")
    assert Declaration(**good)


def test_declaration_id_impossible_date(decl_test_line):
    with pytest.raises(ValidationError, match="310221"):
        Declaration(**dict(decl_test_line, declaration_id="700040300/310221/999001"))


def test_declaration_id_unknown_authority(decl_test_line):
    with pytest.raises(ValidationError, match="799999999"):
        Declaration(**dict(decl_test_line, declaration_id="799999999/120521/999001"))


def test_additional_receiver_without_receiver(decl_test_line):
    line = dict(decl_test_line, receiver=None)
    line["receiver_additional"] = {"tax_payer_id": "1", "name": "X", "address": "Y"}
    with pytest.raises(ValidationError, match="Receiver"):
        Declaration(**line)


def test_declaration_no_end_date(decl_test_line):
    decl_test_line["item"]["documents"]["date_ended"] = ""
    declaration = Declaration(**decl_test_line)
    assert declaration.item.documents.date_ended is None


def test_end_gt_start(decl_test_line):
    decl_test_line["item"]["documents"] = {
        "document_code": None,
        "document": "2019/02/26",
        "date_started": "31/12/21",
        "date_ended": "26/02/19",
    }
    with pytest.raises(ValidationError):
        Declaration.model_validate(decl_test_line)


def test_crud_type_keywords(decl_test_line):
    assert Declaration(**dict(decl_test_line, crud_type="korrekt")).crud_type == "update"
    with pytest.raises(ValidationError):
        Declaration(**dict(decl_test_line, crud_type="unknown"))


@pytest.mark.xfail(reason="currency_alpha3 is Union[enum, str]: any string is accepted, decide whether to enforce")
def test_currency_code(decl_test_line):
    decl_test_line["invoice_value"]["currency_alpha3"] = "PPP"
    with pytest.raises(ValidationError):
        Declaration(**decl_test_line)


def test_statement(statement_test_line):
    statement = ClearanceStatement(**statement_test_line)
    assert statement.statement_date == datetime.datetime(2021, 5, 12)
    assert statement.receiving.name == 'LLC "Example Cargo"'
    assert statement.invoice.currency_alpha3 == "RUB"


def test_statement_bad_date(statement_test_line):
    with pytest.raises(ValidationError):
        ClearanceStatement(**dict(statement_test_line, statement_date="31.02.2021"))


def test_waybill(waybill_test_line):
    waybill = Waybill(**waybill_test_line)
    assert waybill.registration == datetime.datetime(2022, 6, 22)
    assert waybill.correction_date is None
    assert waybill.item.item_price == 500000.0

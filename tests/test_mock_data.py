import pytest
from pydantic import ValidationError

from application.ingest import classify, read_rows
from application.mock_data import MockDataGenerator
from models.registry import PAPER_KINDS


@pytest.mark.parametrize("kind", PAPER_KINDS, ids=lambda k: k.key)
def test_generated_rows_validate(generator, kind):
    for row in generator.rows(kind, 30):
        assert len(row) == len(kind.model.leaf_fields())
        kind.model.from_row(row)


@pytest.mark.parametrize("kind", PAPER_KINDS, ids=lambda k: k.key)
def test_invalid_rows_are_rejected(generator, kind):
    with pytest.raises(ValidationError):
        kind.model.from_row(generator.invalid_row(kind))


def test_same_seed_same_data():
    kind = PAPER_KINDS[0]
    first = MockDataGenerator(seed=99).rows(kind, 5)
    second = MockDataGenerator(seed=99).rows(kind, 5)
    assert [row[1:] for row in first] == [row[1:] for row in second]


def test_updates_use_update_keyword(generator):
    from models.registry import KINDS_BY_KEY

    for document in generator.documents(KINDS_BY_KEY["declarationupdates"], 10):
        assert document["crud_type"] == "update"


@pytest.mark.parametrize("kind", PAPER_KINDS, ids=lambda k: k.key)
def test_csv_is_picked_up_by_the_pipeline(generator, pipeline_config, fs, tmp_path, kind):
    path = generator.write_csv(tmp_path, kind, 20, invalid_ratio=0.25)
    assert classify(path.name, pipeline_config) is kind
    rows = read_rows(fs, str(path), pipeline_config.csv_delimiters)
    assert len(rows) == 20
    invalid = 0
    for row in rows:
        try:
            kind.model.from_row(row)
        except ValidationError:
            invalid += 1
    assert invalid == 5


@pytest.mark.parametrize("kind", PAPER_KINDS, ids=lambda k: k.key)
def test_mock_data_is_recognisably_fake(generator, kind):
    from models.logic.pydantic_helper import get_path

    leaves = kind.model.leaf_fields()
    for document in generator.documents(kind, 30):
        for leaf in leaves:
            value = get_path(document, leaf.path)
            if leaf.name.endswith("tax_payer_id") or leaf.name in ("sort_code", "classifier", "seller_bank", "buyer_bank"):
                assert value in ("", None) or str(value).startswith("TEST"), (leaf.title, value)
        if kind.key == "waybill":
            assert document["id"].startswith("MOCK-")
        number = document.get("declaration_id") or document.get("statement_id")
        if number:
            assert int(number.rsplit("/", 1)[1]) >= 990_000, number

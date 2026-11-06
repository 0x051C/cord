from models.paper import Paper, PaperCollection


class ClassOne(Paper):
    id: int
    p: str


class ClassTwo(Paper):
    one: ClassOne
    name: str


t = ClassTwo(one=ClassOne(id=1, p="One"), name="Two")


def test_flattening():
    assert t.flat_values() == [1, "One", "Two"]


def test_key_flattening():
    assert t.flat_keys() == ["one id", "one p", "name"]


def test_group_nested_round_trip():
    assert ClassTwo.from_row(t.flat_values()) == t


def test_short_row_reports_missing_fields():
    assert ClassTwo.group_nested([1]) == {"one": {"id": 1}}


def test_paper_collection():
    collection = PaperCollection(paper_list=[t for _ in range(10)])
    frame = collection.to_dataframe()
    assert frame.shape == (10, 3)
    assert list(frame.columns) == ["one id", "one p", "name"]

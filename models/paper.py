from typing import Any, List, Optional

import pandas as pd

from models.base import CordModel
from models.logic import pydantic_helper


class Paper(CordModel):
    """Base class of every document type parsed from a flat source row."""

    @classmethod
    def leaf_fields(cls) -> list[pydantic_helper.LeafField]:
        return pydantic_helper.leaf_fields(cls)

    @classmethod
    def group_nested(cls, values: list) -> dict:
        """Group a flat row into the nested dict accepted by the model.

        e.g. if columns 2-4 hold the attributes ``a``, ``b``, ``c`` of a nested model ``x``::

            ["v1", 1, "v2", "v3", "v4"]  ->  {"f1": "v1", "x": {"a": 1, "b": "v2", "c": "v3"}, "f2": "v4"}
        """
        return pydantic_helper.group_nested(cls, values)

    @classmethod
    def from_row(cls, values: list):
        return cls.model_validate(cls.group_nested(values))

    @classmethod
    def flat_titles(cls) -> list[str]:
        return [leaf.title for leaf in cls.leaf_fields()]

    @classmethod
    def flatten_document(cls, document: dict) -> list:
        """Flat values of a stored (``model_dump(mode="json")``) document, in ``flat_titles()`` order."""
        return [pydantic_helper.get_path(document, leaf.path) for leaf in cls.leaf_fields()]

    def flat_values(self) -> list:
        return self.flatten_document(self.model_dump(mode="json"))

    def flat_keys(self) -> list[str]:
        return self.flat_titles()


class PaperCollection(CordModel):
    paper_list: List[Paper]
    received_timestamp: Optional[float] = None

    def to_dataframe(self) -> pd.DataFrame:
        """Flatten the collection, all papers are expected to share the first paper's type."""
        if not self.paper_list:
            return pd.DataFrame()
        return pd.DataFrame.from_records(
            [paper.flat_values() for paper in self.paper_list],
            columns=self.paper_list[0].flat_keys(),
        )


def stringify(value: Any) -> Any:
    """Make a flat value spreadsheet friendly."""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    return value

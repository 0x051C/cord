"""
Helpers for mapping flat CSV rows onto nested pydantic models.

A source row is a flat list of values. Its column order is the *depth-first
order of the model's leaf fields*: a field holding a nested model consumes as
many consecutive columns as that model has leaves, e.g. for::

    class Entity(BaseModel):          class Declaration(BaseModel):
        tax_payer_id: str                 declaration_id: str
        name: str                         sender: Entity
        address: str                      timestamp: str

the row ``[id, tax_id, name, address, ts]`` groups into
``{"declaration_id": id, "sender": {"tax_payer_id": ..., "name": ..., "address": ...}, "timestamp": ts}``.
"""

import datetime
import types
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Iterator, Optional, Union, get_args, get_origin

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo


def date_validation(day: int = 1, month: int = 1, year: int = 2014) -> datetime.datetime:
    try:
        return datetime.datetime(day=day % 100, month=month % 100, year=year % 10000)
    except Exception as e:
        raise ValueError(str(e))


def nested_model(annotation: Any) -> Optional[type[BaseModel]]:
    """Return the pydantic model held by a field annotation (``X``, ``Optional[X]``, ``Union[X, dict, None]``...)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) in (Union, types.UnionType):
        for arg in get_args(annotation):
            model = nested_model(arg)
            if model is not None:
                return model
    return None


@dataclass(frozen=True)
class LeafField:
    """A non-model field reached by walking a model depth-first."""

    path: tuple[str, ...]  # field names, e.g. ("item", "documents", "date_started")
    input_path: tuple[str, ...]  # same path using validation aliases (keys expected on input)
    owner: type[BaseModel]  # model that declares the field
    name: str
    info: FieldInfo

    @property
    def title(self) -> str:
        """Flat column title, e.g. ``"item documents date_started"``."""
        return " ".join(self.path)

    @property
    def column(self) -> str:
        """Identifier-safe flat column name, e.g. ``"item__documents__date_started"``."""
        return "__".join(self.path)


def iter_leaves(
    model: type[BaseModel], _path: tuple = (), _input_path: tuple = ()
) -> Iterator[LeafField]:
    for name, info in model.model_fields.items():
        path = (*_path, name)
        input_path = (*_input_path, info.alias or name)
        sub_model = nested_model(info.annotation)
        if sub_model is not None:
            yield from iter_leaves(sub_model, path, input_path)
        else:
            yield LeafField(path=path, input_path=input_path, owner=model, name=name, info=info)


def leaf_fields(model: type[BaseModel]) -> list[LeafField]:
    return list(iter_leaves(model))


_EXHAUSTED = object()


def group_nested(model: type[BaseModel], values: Iterable[Any]) -> dict:
    """Group a flat row into the nested dict expected by ``model``.

    Extra trailing values are ignored; when the row is too short, the missing
    keys are left out so validation reports them as missing.
    """
    iterator = iter(values)

    def consume(m: type[BaseModel]) -> dict:
        out = dict()
        for name, info in m.model_fields.items():
            key = info.alias or name
            sub_model = nested_model(info.annotation)
            if sub_model is not None:
                group = consume(sub_model)
                if group:
                    out[key] = group
            else:
                value = next(iterator, _EXHAUSTED)
                if value is _EXHAUSTED:
                    return out
                out[key] = value
        return out

    return consume(model)


def get_path(document: Any, path: Iterable[str]) -> Any:
    for key in path:
        if not isinstance(document, dict):
            return None
        document = document.get(key)
    return document


def reorder_fields(model: type[BaseModel], order: list[str], name: Optional[str] = None) -> type[BaseModel]:
    """Create a model with only the ``order`` fields of ``model``, in that order.

    The same entity is laid out differently in different source files (and some
    files omit fields), this builds the matching model. Validators declared with
    ``Annotated[..., AfterValidator(...)]``, aliases and constraints carry over.
    """
    fields = model.model_fields
    new_model = create_model(
        name or f"{model.__name__}_{'_'.join(order)}",
        __config__=model.model_config,
        __doc__=model.__doc__,
        **{field: (fields[field].annotation, fields[field]) for field in order},  # type: ignore
    )
    new_model.__source_model__ = model  # type: ignore[attr-defined]
    return new_model


def auto_enum(name: str, values: Iterable[str]) -> type[Enum]:
    """Build a ``str`` Enum whose members are the given (configured) values."""
    if isinstance(values, str):
        values = values.split()
    return Enum(name, {value: value for value in values}, type=str)  # type: ignore[return-value]

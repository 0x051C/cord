from pydantic import BaseModel, ConfigDict


class CordModel(BaseModel):
    """Common configuration for every model of the application."""

    model_config = ConfigDict(
        # Configured patterns use look-arounds / comments, unsupported by the default Rust engine.
        regex_engine="python-re",
        # Fields with an alias (e.g. Item.item_price <- "price") accept both names.
        validate_by_name=True,
        validate_by_alias=True,
    )

from typing import Union

from models.base import CordModel


class Bank(CordModel):
    """
    ```
    Bank(
    sort_code = int | str, — MFO (bank sort code)
    name = str,
    classifier = str) — OKPO (classifier) code
    ```
    """

    sort_code: Union[int, str]
    name: str
    classifier: str

"""
Application settings (dynaconf).

Two profiles are supported, selected with the ``CORD_ENV`` environment variable:

* unset / ``production`` -- ``validation_config.py`` + ``cord.toml`` + ``.secrets.ini``
  (SMB share, MongoDB; ``cord.toml`` and ``.secrets.ini`` are local, git-ignored files).
* ``local`` -- ``validation_config.py`` + ``profiles/local.toml`` (local folders under
  ``sandbox/``, SQLite). Fully self-contained, no network access needed.

Any setting can also be overridden with a ``CORD_<NAME>`` environment variable.
"""

import os
from pathlib import Path

from dynaconf import Dynaconf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

ENVIRONMENT = os.environ.get("CORD_ENV", "production").strip().lower() or "production"

# NB: profile files must not be named "<name>.local.toml": dynaconf automatically loads
# such a file on top of "<name>.toml", which would leak a local profile into production.
if ENVIRONMENT == "production":
    _profile_files = ["cord.toml", ".secrets.ini"]
else:
    _profile_files = [f"profiles/{ENVIRONMENT}.toml"]

settings = Dynaconf(
    envvar_prefix="CORD",
    settings_files=[str(CONFIG_DIR / name) for name in ["validation_config.py", *_profile_files]],
    core_loaders=["PY", "TOML", "INI"],
)

assert settings.get("FEACN_LENGTH") is not None, (
    f"Validation settings were not loaded, check {CONFIG_DIR / 'validation_config.py'}"
)


def resolve_path(value) -> str:
    """Resolve a *local* path setting relative to the project root."""
    path = Path(value)
    return str(path if path.is_absolute() else PROJECT_ROOT / path)

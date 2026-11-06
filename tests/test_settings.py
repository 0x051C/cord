import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = (
    "import json; from application.configuration_handling import settings, ENVIRONMENT; "
    "from dynaconf.utils.inspect import get_history; "
    "print(json.dumps({'environment': ENVIRONMENT, 'files': sorted({str(h['identifier']) for h in get_history(settings)}), "
    "'web_auth': settings.get('web_auth'), 'storage_backend': settings.get('storage_backend')}))"
)


def load_profile(cord_env=None) -> dict:
    """Load the settings in a fresh interpreter (they are read once, at import time)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CORD_")}
    if cord_env:
        env["CORD_ENV"] = cord_env
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_production_does_not_load_local_profile():
    # dynaconf loads "<name>.local.toml" next to "<name>.toml" automatically: no profile may leak into production
    production = load_profile()
    assert production["environment"] == "production"
    assert not [f for f in production["files"] if "profiles" in Path(f).parts or ".local." in Path(f).name]
    assert production["web_auth"] != "none" and production["storage_backend"] != "sqlite"


def test_local_profile():
    local = load_profile("local")
    assert any(Path(f).as_posix().endswith("config/profiles/local.toml") for f in local["files"])
    assert local["web_auth"] == "none" and local["storage_backend"] == "sqlite"

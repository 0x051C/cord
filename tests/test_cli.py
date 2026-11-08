import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def cli(*args, cord_env=None):
    """Run main.py in a fresh interpreter: settings are read once, at import time."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CORD_")}
    if cord_env:
        env["CORD_ENV"] = cord_env
    return subprocess.run([sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("args", [["--help"], ["seed", "--help"], ["serve", "-h"]])
def test_help(args):
    result = cli(*args)
    assert result.returncode == 0 and "Usage:" in result.stdout


@pytest.mark.parametrize("command", ["seed", "reset"])
def test_local_only_commands_refuse_production(command):
    result = cli(command)
    assert result.returncode == 2 and "only works with a local profile" in result.stderr


@pytest.mark.parametrize("args, hint", [
    (["seed", "--kinds", "nope", "--rows", "1"], "unknown kind"),
    (["seed", "--target", "s3"], "'s3' is not one of"),
    (["seed", "--invalid-ratio", "2"], "--invalid-ratio"),
    (["serve", "--port", "0"], "--port"),
])
def test_bad_options(args, hint):
    result = cli(*args, cord_env="local")
    assert result.returncode == 2 and hint in result.stderr

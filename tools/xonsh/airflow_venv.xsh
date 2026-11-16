# Xonsh autovox rule: entering a folder that has a `.venv-airflow` virtualenv (cord) activates
# it and points Airflow at that project; leaving the folder deactivates it and undoes the settings.
#
# Needs `xontrib load vox autovox` earlier in ~/.xonshrc. Install by linking this file into
# xonsh's rc.d folder (see "Xonsh: activate the Airflow virtualenv automatically" in README.md):
#
#     ln -s $PWD/tools/xonsh/airflow_venv.xsh ~/.config/xonsh/rc.d/

from pathlib import Path as _AirflowVenvPath

_AIRFLOW_VENV = ".venv-airflow"
_AIRFLOW_SET_BY_US = []  # variables this rule set, so deactivation only removes those


@events.autovox_policy
def _airflow_venv_policy(path, **_):
    # autovox asks for each folder from the current one up to /, so subfolders count too
    venv = path / _AIRFLOW_VENV
    return venv if (venv / "bin" / "python").exists() else None


@events.vox_on_activate
def _airflow_venv_activate(name=None, path=None, **_):
    if path is None or _AirflowVenvPath(path).name != _AIRFLOW_VENV:
        return
    project = _AirflowVenvPath(path).parent
    settings = {
        "AIRFLOW_HOME": str(project / ".airflow"),
        "AIRFLOW__CORE__DAGS_FOLDER": str(project / "dags"),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
        "CORD_ENV": "local",  # sandbox + SQLite; set CORD_ENV yourself to override
    }
    for key, value in settings.items():
        if key not in ${...}:
            ${...}[key] = value
            _AIRFLOW_SET_BY_US.append(key)


@events.vox_on_deactivate
def _airflow_venv_deactivate(name=None, path=None, **_):
    while _AIRFLOW_SET_BY_US:
        ${...}.pop(_AIRFLOW_SET_BY_US.pop(), None)

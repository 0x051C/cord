import logging
import sys
from pathlib import Path

validation_logger = logging.getLogger("validation")
smb_logger = logging.getLogger("smbprotocol")

LOG_FILE_NAMES = ("validation.log", "smb.log")
_FORMATTER = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
_installed: list[tuple[logging.Logger, logging.Handler]] = []


class _FirstLineFormatter(logging.Formatter):
    """Console output: first meaningful line of a message only, details stay in the log file."""

    def format(self, record: logging.LogRecord) -> str:
        lines = [line.strip() for line in record.getMessage().splitlines() if line.strip()]
        short = logging.makeLogRecord({**record.__dict__, "msg": lines[0] if lines else "", "args": None})
        return super().format(short)


def configure_logging(log_dir, console: bool = True, new_run: bool = True) -> Path:
    """(Re)install the file handlers in ``log_dir``; safe to call more than once.

    ``smb.log`` is started afresh for each run; later steps of the same run (Airflow tasks,
    each in its own process) pass ``new_run=False`` to append to it instead.
    """
    for logger, handler in _installed:
        logger.removeHandler(handler)
        handler.close()
    _installed.clear()

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    validation_logger.setLevel(logging.DEBUG)
    smb_logger.setLevel(logging.INFO)

    handlers = [
        (validation_logger, logging.FileHandler(log_dir / "validation.log", mode="a", encoding="utf-8")),
        (smb_logger, logging.FileHandler(log_dir / "smb.log", mode="w" if new_run else "a", encoding="utf-8")),
    ]
    if console:
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(_FirstLineFormatter("%(levelname)-7s %(message)s"))
        handlers.append((validation_logger, console_handler))

    for logger, handler in handlers:
        if handler.formatter is None:
            handler.setFormatter(_FORMATTER)
        logger.addHandler(handler)
        _installed.append((logger, handler))
    return log_dir


def flush_logs() -> None:
    for _, handler in _installed:
        handler.flush()

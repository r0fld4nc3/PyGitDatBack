import logging
from logging import FileHandler
from pathlib import Path

from conf_globals import APP_NAME, HOST

from .path_helpers import get_os_env_config_folder

LOG_FILE = get_os_env_config_folder() / HOST / APP_NAME / f"{APP_NAME}.log"

# Third-party loggers that are very chatty at DEBUG level
_NOISY_LOGGERS = ("git", "urllib3", "requests")


def configure_logging(level: int = logging.INFO, log_file: Path = LOG_FILE, console: bool = True) -> None:
    """
    Set up the root logger once, at startup.
    Modules then get their own logger with `logging.getLogger(__name__)`,
    which passes records up to the root handlers configured here.
    """
    if log_file.exists() and not log_file.is_file():
        raise RuntimeError(f"Log file path exists but is not a file: '{log_file}'")

    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s] %(message)s", datefmt="%d-%m-%Y %H:%M:%S"
    )

    # Remove any pre-existing handlers. Important when running in dev
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    file_handler = FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(root.level, logging.WARNING))


def reset_log_file(log_file: Path = LOG_FILE) -> None:
    if log_file.exists() and log_file.is_file():
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("")

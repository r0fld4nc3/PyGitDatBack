import os
import logging
from pathlib import Path
from .path_helpers import get_os_env_config_folder, ensure_paths
from conf_globals import HOST, APP_NAME

LOG_FILE = get_os_env_config_folder() / HOST / APP_NAME / f"{APP_NAME}.log"
print(f"{LOG_FILE=}")

LEVELS = {
    0: logging.DEBUG,
    1: logging.INFO,
    2: logging.WARNING,
    3: logging.ERROR
}

def create_logger(logger_name: str, level: int) -> logging.Logger:
    # Create needed folder if it doesn't exist
    if not get_os_env_config_folder().exists():
        os.makedirs(get_os_env_config_folder(), exist_ok=True)

    ensure_paths(LOG_FILE.parent)

    if not LOG_FILE.exists():
        with open(LOG_FILE, 'w', encoding="utf-8") as f:
            f.write('')

    logger = logging.getLogger(logger_name)

    logger.setLevel(LEVELS.get(level, 1))

    handler_stream = logging.StreamHandler()
    handler_file = logging.FileHandler(LOG_FILE)

    formatter = logging.Formatter(f"[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s] %(message)s", 
                                  datefmt="%d-%m-%Y %H:%M:%S")
    handler_stream.setFormatter(formatter)
    handler_file.setFormatter(formatter)

    # Add the handlers if not present already
    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        logger.addHandler(handler_stream)

    if not any(isinstance(handler, logging.FileHandler) and handler.baseFilename == LOG_FILE for handler in logger.handlers):
        logger.addHandler(handler_file)

    return logger


def reset_log_file() -> None:
    if Path(LOG_FILE).exists():
        with open(LOG_FILE, 'w') as f:
            f.write('')

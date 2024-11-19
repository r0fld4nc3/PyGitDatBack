from datetime import datetime
from PySide6.QtWidgets import QApplication

from log import create_logger
from conf_globals import G_LOG_LEVEL

logger = create_logger(__name__, G_LOG_LEVEL)

def get_screen_info(app: QApplication) -> tuple:
    # Get the primary screen
    screen = app.primaryScreen()
    logger.debug(f"{screen=}")

    # Screen resolution
    size = screen.size()
    width = size.width()
    height = size.height()
    
    logger.debug(f"{size=}")
    logger.debug(f"{width=}")
    logger.debug(f"{height=}")

    # Scaling factor
    scale_f = screen.devicePixelRatio()
    logger.debug(f"{scale_f=}")

    return width, height, scale_f


def get_current_timestamp() -> str:
    fmt = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    return fmt

def to_datetime(ts: str) -> datetime:
    try:
        date = datetime.strptime(ts, "%d-%m-%Y %H:%M:%S")
    except ValueError:
        date = datetime.strptime(get_current_timestamp(), "%d-%m-%Y %H:%M:%S")

    return date

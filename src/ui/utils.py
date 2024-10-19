from PySide6.QtWidgets import QApplication
from urllib.parse import urlparse

from log import create_logger
from conf_globals import G_LOG_LEVEL

logger = create_logger(f"src.{__name__}", G_LOG_LEVEL)

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

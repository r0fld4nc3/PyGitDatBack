import logging

from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


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

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel
)
from PySide6.QtCore import Qt

from conf_globals import G_LOG_LEVEL
from log import create_logger

logger = create_logger(__name__, G_LOG_LEVEL)

class AlignedWidget(QWidget):
    def __init__(self, widget, alignment=Qt.AlignCenter, margins: tuple =None):
        super().__init__()

        if not margins:
            margins = (0, 0, 0, 0)

        if len(margins) != 4:
            raise ValueError(f"Expected `margins` to have 4 elements, but got {len(margins)}: {margins}")
        
        # logger.debug(f"{margins=} ({widget})")

        self.main_widget = widget
        layout = QHBoxLayout()
        layout.addWidget(self.main_widget, alignment=alignment)
        layout.setContentsMargins(*margins)
        
        if isinstance(widget, QLabel):
            self.main_widget.setStyleSheet(f"padding-left: {margins[0]}px; padding-top: {margins[1]}px; padding-right: {margins[2]}px; padding-bottom: {margins[3]}px;")

        self.setLayout(layout)

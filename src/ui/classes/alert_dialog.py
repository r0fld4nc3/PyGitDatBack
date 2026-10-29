import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout

logger = logging.getLogger(__name__)


class AlertDialog(QDialog):
    def __init__(self, alert: str, title: str = "Alert"):
        super().__init__()

        self.alert_text = alert
        self.title = title

        self.setWindowTitle(title)

        self.resize(QSize(400, 200))

        QBtn = QDialogButtonBox.Ok | QDialogButtonBox.Cancel

        self.button_box = QDialogButtonBox(QBtn)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout()

        self.message_box = QTextEdit(self.alert_text)
        self.message_box.setEnabled(False)
        self.message_box.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.message_box)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

        self.exec()

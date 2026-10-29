import logging

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

import settings

log = logging.getLogger(__name__)


class RepoSettingsDialog(QDialog):
    """
    Editable application settings.

    Widgets can write to settings as the user edits them. A snapshot is taken when the dialog
    opens: OK keeps the changes (and writes any memory-only ones), anything else restores it.
    """

    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(400, 300)

        self.config = settings.get()
        self.config_snapshot = self.config.snapshot()

        self.content_layout = QVBoxLayout()
        self.content_layout.addStretch()

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.content_layout)
        layout.addWidget(self.buttons)

    def accept(self):
        log.info("Settings accepted.")

        self.config.save_if_dirty()

        super().accept()

    def reject(self):
        log.info("Settings cancelled.")

        self.config.restore(self.config_snapshot)

        super().reject()

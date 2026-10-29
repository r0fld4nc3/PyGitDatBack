import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import settings

log = logging.getLogger(__name__)

# Range offered for max_concurrent_tasks
MIN_CONCURRENT_TASKS = 1
MAX_CONCURRENT_TASKS = 100


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

        self.content_layout.addWidget(self._build_max_concurrent_tasks_widget())

        self.content_layout.addStretch()

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.content_layout)
        layout.addWidget(self.buttons)

    def _build_max_concurrent_tasks_widget(self) -> QWidget:
        """Label, integer slider and the current value, writing to `max_concurrent_tasks` as it moves."""
        label = QLabel("Max Concurrent Tasks:")
        label.setToolTip("Maximum allowed paralell tasks.")

        # Clamp the saved value, in case the file holds one outside the range.
        value = min(max(self.config.settings.max_concurrent_tasks, MIN_CONCURRENT_TASKS), MAX_CONCURRENT_TASKS)

        # QSlider
        self.max_concurrent_tasks_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_concurrent_tasks_slider.setRange(MIN_CONCURRENT_TASKS, MAX_CONCURRENT_TASKS)
        self.max_concurrent_tasks_slider.setSingleStep(1)
        self.max_concurrent_tasks_slider.setPageStep(1)
        self.max_concurrent_tasks_slider.setValue(value)

        # Slider value. Pre-compute max number and size to avoid slider shift.
        self.max_concurrent_tasks_value = QLabel(str(value))
        # Room for the widest number. Avoid slider shifting as digits change.
        widest = self.max_concurrent_tasks_value.fontMetrics().horizontalAdvance(str(MAX_CONCURRENT_TASKS))
        self.max_concurrent_tasks_value.setMinimumWidth(widest)
        self.max_concurrent_tasks_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Connected after setValue, so opening the dialog doesn't count as a change
        self.max_concurrent_tasks_slider.valueChanged.connect(self._on_max_concurrent_tasks_changed)

        # Build layouts

        out_widget = QWidget()

        layout_vertical = QVBoxLayout(out_widget)
        layout_vertical.addWidget(label)

        layout_horizontal = QHBoxLayout()
        layout_horizontal.setContentsMargins(0, 0, 0, 0)
        layout_horizontal.addWidget(self.max_concurrent_tasks_slider, stretch=1)
        layout_horizontal.addWidget(self.max_concurrent_tasks_value)

        layout_vertical.addLayout(layout_horizontal)
        return out_widget

    def _on_max_concurrent_tasks_changed(self, value: int):
        self.max_concurrent_tasks_value.setText(str(value))
        self.config.settings.max_concurrent_tasks = value  # memory() value. Only written on OK.

    def accept(self):
        log.info("Settings accepted.")

        self.config.save_if_dirty()

        super().accept()

    def reject(self):
        log.info("Settings cancelled.")

        self.config.restore(self.config_snapshot)

        super().reject()

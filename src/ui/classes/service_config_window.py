import logging

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

import settings
from systemd import ScheduleType

logger = logging.getLogger(__name__)

SCHEDULE_OPTIONS = [ScheduleType.DAILY, ScheduleType.WEEKLY, ScheduleType.MONTHLY, ScheduleType.MONTH_SPEC]
WEEK_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_DAYS = [str(n) for n in range(1, 32)]
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
HOURS = [f"{hour:02d}" for hour in range(24)]
MINUTES = [f"{minute:02d}" for minute in range(0, 60, 5)]

# Which date pickers each schedule type needs: (month day, month, week day). Anything else is weekly.
_PICKERS_FOR_TYPE = {
    ScheduleType.DAILY: (False, False, False),
    ScheduleType.MONTHLY: (True, False, False),
    ScheduleType.MONTH_SPEC: (True, True, False),
}
_WEEKLY_PICKERS = (False, False, True)


class ServiceConfigWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Service Settings")
        self.setModal(True)  # Block interaction with parent window
        self.resize(QSize(300, 200))

        s = settings.get().settings

        self.selected_type = s.schedule_type
        self.selected_week_day = s.schedule_week_day
        self.selected_month_day = s.schedule_month_day
        self.selected_month = s.schedule_month
        self.selected_time = s.schedule_time

        # "HH:MM:SS", but tolerate anything (ex.: empty, or just an hour)
        self.selected_hour, _, rest = self.selected_time.partition(":")
        self.selected_min = rest.partition(":")[0]

        logger.debug(f"{self.selected_type=} {self.selected_time=} {self.selected_hour=} {self.selected_min=}")

        self.schedule_type_dropdown = self._dropdown(SCHEDULE_OPTIONS, self.selected_type)
        if self.selected_type not in SCHEDULE_OPTIONS:
            self.schedule_type_dropdown.setCurrentText(ScheduleType.WEEKLY)
        self.schedule_type_dropdown.currentTextChanged.connect(self.on_schedule_type_changed)

        self.week_day_dropdown = self._dropdown(WEEK_DAYS, self.selected_week_day)
        self.month_days_dropdown = self._dropdown(MONTH_DAYS, self.selected_month_day)

        # Months are stored as numbers, 1-12
        self.months_dropdown = self._dropdown(MONTHS)
        if 1 <= self.selected_month <= len(MONTHS):
            self.months_dropdown.setCurrentIndex(self.selected_month - 1)

        self.hours_dropdown = self._dropdown(HOURS, self.selected_hour)
        self.hours_dropdown.setContentsMargins(0, 0, 0, 0)
        self.minutes_dropdown = self._dropdown(MINUTES, self.selected_min)

        hour_sep = QLabel(":")
        hour_sep.setContentsMargins(0, 0, 0, 0)

        ok_button = QPushButton("Accept")
        ok_button.clicked.connect(self.accept)

        date_row = QHBoxLayout()
        date_row.addStretch()
        for widget in (
            self.schedule_type_dropdown,
            self.month_days_dropdown,
            self.months_dropdown,
            self.week_day_dropdown,
            self.hours_dropdown,
            hour_sep,
            self.minutes_dropdown,
        ):
            date_row.addWidget(widget)
        date_row.addStretch()

        main_layout = QVBoxLayout()
        main_layout.addLayout(date_row)
        main_layout.addWidget(ok_button)
        self.setLayout(main_layout)

        # Initial visibility setup based on current selection
        self.on_schedule_type_changed(self.schedule_type_dropdown.currentText())

    @staticmethod
    def _dropdown(items: list[str], selected: str = "") -> QComboBox:
        """A combo box with `items`, preselecting `selected` when it is one of them."""
        dropdown = QComboBox()
        dropdown.addItems(items)
        if selected in items:
            dropdown.setCurrentText(selected)
        return dropdown

    def on_schedule_type_changed(self, schedule_type: str):
        """Show only the date pickers the chosen schedule type uses."""
        month_day, month, week_day = _PICKERS_FOR_TYPE.get(schedule_type, _WEEKLY_PICKERS)
        self.month_days_dropdown.setVisible(month_day)
        self.months_dropdown.setVisible(month)
        self.week_day_dropdown.setVisible(week_day)

    def get_selected_values(self):
        return (
            self.selected_type,
            self.selected_month,
            self.selected_month_day,
            self.selected_week_day,
            self.selected_time,
        )

    def accept(self):
        self.selected_type = self.schedule_type_dropdown.currentText()
        self.selected_month = self.months_dropdown.currentIndex() + 1  # Months are 1-12
        self.selected_month_day = self.month_days_dropdown.currentText()
        self.selected_week_day = self.week_day_dropdown.currentText()
        self.selected_time = f"{self.hours_dropdown.currentText()}:{self.minutes_dropdown.currentText()}:00"

        super().accept()

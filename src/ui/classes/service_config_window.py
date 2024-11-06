from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog, QComboBox
)
from PySide6.QtCore import QSize

from conf_globals import G_LOG_LEVEL
from log import create_logger
from settings import Settings
import systemd

logger = create_logger(__name__, G_LOG_LEVEL)


class ServiceConfigWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Service Settings")
        self.setModal(True) # Blocks interaction with parent window
        self.resize(QSize(300, 200))

        self.settings = Settings()
        self.settings.load_config()

        self.selected_type = self.settings.get_schedule_type()
        self.selected_week_day = self.settings.get_scheduled_week_day()
        self.selected_month_day = self.settings.get_scheduled_month_day()
        self.selected_month = self.settings.get_scheduled_month()
        self.selected_time = self.settings.get_scheduled_time()
        self.selected_hour = self.selected_time.split(':')[0]
        self.selected_min = self.selected_time.split(':')[1]

        logger.debug(f"{self.selected_type=}")
        logger.debug(f"{self.selected_time=}")
        logger.debug(f"{self.selected_hour=}")
        logger.debug(f"{self.selected_min=}")

        main_layout = QVBoxLayout()

        service_date_widgets_layout = QHBoxLayout()

        # Schedule Type Widget
        # schedule_type_options = [systemd.ScheduleTypes.DAILY.value, systemd.ScheduleTypes.WEEKLY.value, systemd.ScheduleTypes.YEARLY.value, systemd.ScheduleTypes.MONTHLY.value, systemd.ScheduleTypes.MONTH_SPEC.value, systemd.ScheduleTypes.EVERY.value]
        schedule_type_options = [systemd.ScheduleTypes.DAILY.value, systemd.ScheduleTypes.WEEKLY.value, systemd.ScheduleTypes.MONTHLY.value, systemd.ScheduleTypes.MONTH_SPEC.value]
        self.schedule_type_dropdown = QComboBox()
        self.schedule_type_dropdown.addItems(schedule_type_options)
        if self.selected_type in schedule_type_options:
            self.schedule_type_dropdown.setCurrentText(self.selected_type)
        else:
            self.schedule_type_dropdown.setCurrentText(systemd.ScheduleTypes.WEEKLY.value)
        # Connect the dropdown selection changed to a slot
        self.schedule_type_dropdown.currentTextChanged.connect(self.on_schedule_type_changed)
        
        # Week Days Combobox
        week_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        self.week_day_dropdown = QComboBox()
        self.week_day_dropdown.addItems(week_days)
        if self.selected_week_day in week_days:
            self.week_day_dropdown.setCurrentText(self.selected_week_day)

        # Month Days Combobox
        month_days = [str(n) for n in range(1, 32)]
        self.month_days_dropdown = QComboBox()
        self.month_days_dropdown.addItems(month_days)
        if self.selected_month_day in month_days:
            self.month_days_dropdown.setCurrentText(self.selected_month_day)

        # Months Combobox
        months = ["January", "February", "March", "April", "May", "Jun", "July", "August", "September", "October", "Novemeber", "December"]
        self.months_dropdown = QComboBox()
        self.months_dropdown.addItems(months)
        if self.selected_month in months:
            self.months_dropdown.setCurrentText(months[self.selected_month-1])

        # Time Possibilities Combobox
        times = self.__generate_hours_minutes()
        self.hours_dropdown = QComboBox()
        self.hours_dropdown.setContentsMargins(0, 0, 0, 0)
        self.minutes_dropdown = QComboBox()
        self.hours_dropdown.addItems(times[0])
        self.minutes_dropdown.addItems(times[1])
        if self.selected_hour in times[0]:
            self.hours_dropdown.setCurrentText(self.selected_hour)
        if self.selected_min in times[1]:
            self.minutes_dropdown.setCurrentText(self.selected_min)

        hour_sep = QLabel(":")
        hour_sep.setContentsMargins(0, 0, 0, 0)

        # Accept button
        ok_button = QPushButton("Accept")
        ok_button.clicked.connect(self.accept)

        # Add to service date layout
        service_date_widgets_layout.addStretch()
        service_date_widgets_layout.addWidget(self.schedule_type_dropdown)
        service_date_widgets_layout.addWidget(self.month_days_dropdown)
        service_date_widgets_layout.addWidget(self.months_dropdown)
        service_date_widgets_layout.addWidget(self.week_day_dropdown)
        service_date_widgets_layout.addWidget(self.hours_dropdown)
        service_date_widgets_layout.addWidget(hour_sep)
        service_date_widgets_layout.addWidget(self.minutes_dropdown)
        service_date_widgets_layout.addStretch()
        
        # Add to main layout
        main_layout.addLayout(service_date_widgets_layout)
        main_layout.addWidget(ok_button)

        self.setLayout(main_layout)

        # Initial visibility setup based on current selection
        self.on_schedule_type_changed(self.schedule_type_dropdown.currentText())

    def on_schedule_type_changed(self, schedule_type):
        # Default is Weekly
        if schedule_type == systemd.ScheduleTypes.DAILY.value:
            self.month_days_dropdown.hide()
            self.months_dropdown.hide()
            self.week_day_dropdown.hide()
        elif schedule_type == systemd.ScheduleTypes.MONTHLY.value:
            self.month_days_dropdown.show()
            self.months_dropdown.hide()
            self.week_day_dropdown.hide()
        elif schedule_type == systemd.ScheduleTypes.MONTH_SPEC.value:
            self.month_days_dropdown.show()
            self.months_dropdown.show()
            self.week_day_dropdown.hide()
        else:
            # Default is Weekly
            self.week_day_dropdown.show()
            self.months_dropdown.hide()

    def get_selected_values(self):
        return self.selected_type, self.selected_month, self.selected_month_day, self.selected_week_day, self.selected_time
    
    def accept(self):
        self.selected_type = self.schedule_type_dropdown.currentText()
        self.selected_month = self.months_dropdown.currentIndex() + 1 # Months are 1-12
        self.selected_month_day = self.month_days_dropdown.currentText()
        self.selected_week_day = self.week_day_dropdown.currentText()
        self.selected_time = f"{self.hours_dropdown.currentText()}:{self.minutes_dropdown.currentText()}:00"

        super().accept()
    
    def __generate_hours_minutes(self) -> list[list]:
        hours = []
        minutes = []

        # Generate hours from 0-24
        for hour in range(24):
            hour_str = f"{hour:02d}"
            hours.append(hour_str)

        # Generate minutes from 1-60 in 5 minute intervals
        for minute in range(0, 60, 5):
            minute_str = f"{minute:02d}"
            minutes.append(minute_str)

        return [hours, minutes]

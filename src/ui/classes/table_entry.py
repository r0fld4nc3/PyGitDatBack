from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QCheckBox, QLabel
)
from PySide6.QtCore import QDateTime, Qt

from conf_globals import G_LOG_LEVEL
from log import create_logger

from . import AlignedWidget

logger = create_logger(__name__, G_LOG_LEVEL)


class TableEntry(QWidget):
    def __init__(self, url: str):
        super().__init__()

        self.pull_checkbox = QCheckBox()
        self.pull_checkbox_widget = AlignedWidget(self.pull_checkbox)
        self.pull_checkbox.setChecked(True) # Default pull to true

        self.branches_to_pull = []
        
        self.url_label = QLabel(url.strip())
        self.url_label_widget = AlignedWidget(self.url_label, alignment=Qt.AlignLeft, margins=(5, 0, 0, 0))

        self.branches_label = QLabel()
        self.branches_label_widget = AlignedWidget(self.branches_label, alignment=Qt.AlignLeft, margins=(5, 0, 0, 0))
        
        self.timestamp_label = QLabel("n/a")
        self.timestamp_widget = AlignedWidget(self.timestamp_label)

        self.status_label = QLabel()
        self.status_widget = AlignedWidget(self.status_label)
        self.status_fetching = "Fetching..."
        self.status_finished = "Done"

        layout = QHBoxLayout()
        layout.addWidget(self.pull_checkbox_widget)
        layout.addWidget(self.url_label)
        layout.addWidget(self.timestamp_widget)
        layout.addWidget(self.status_widget)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.setLayout(layout)

    def get_pull(self) -> bool:
        return self.pull_checkbox.isChecked()

    def set_pull(self, state: bool):
        self.pull_checkbox.setChecked(state)

    def get_timestamp(self) -> str:
        return self.timestamp_label.text()

    def set_timestamp_now(self):
        """Sets the current timestamp on the timestamp_item."""
        _timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.timestamp_label.setText(_timestamp)
        logger.info(f"Set timestamp {_timestamp} of entry {self.get_url()}")

    def get_url(self) -> str:
        return self.url_label.text()

    def set_url(self, url):
        former_url = self.url_label.text()
        self.url_label.setText(url)
        logger.info(f"Set new URL: {url} for former {former_url}")

    def get_timestamp(self) -> str:
        return self.timestamp_label.text()

    def set_timestamp(self, timestamp: str):
        """Sets the timestamp on the timestamp_item."""
        self.timestamp_label.setText(timestamp)
        logger.info(f"Set timestamp '{timestamp}' of widget {self.timestamp_label} [{self.get_url()}]")

    def get_status(self) -> str:
        return self.status_label.text()

    def set_status(self, status: str):
        """Sets the status on the status_item."""
        self.status_label.setText(status)
        logger.info(f"Set status '{status}' of widget {self.status_label} [{self.get_url()}]")

    def get_branches(self) -> list:
        return self.branches_to_pull

    def set_branches(self, branches_to_set: list):
        self.branches_to_pull = branches_to_set
        self.branches_label.setText(', '.join(self.branches_to_pull))
        logger.info(f"Set new branches: {self.branches_to_pull} for {self.url_label.text()}")

    def props(self) -> dict:
        """Returns the properties that comprise the entry for a saveable format

        * `do_pull` Checked state of the checkbox. `True` if checkbox is checked, `False` otherwise
        * `branches` List of branches to pull from repository
        * `url` URL string
        * `ts` Timestamp string
        """

        ret = {
            "do_pull": self.get_pull(),
            "branches": self.get_branches(),
            "url": self.get_url(),
            "ts": self.get_timestamp()
        }

        return ret

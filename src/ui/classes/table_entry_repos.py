import logging
from enum import IntEnum, StrEnum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget

from defines import EntryKind
from utils import TimestampFormat, timestamp

from .aligned_widget import AlignedWidget

logger = logging.getLogger(__name__)


class Column(IntEnum):
    """Columns of the main table, in display order."""

    PULL = 0
    URL = 1
    BRANCHES = 2
    LAST_PULLED = 3
    STATUS = 4

    @property
    def header(self) -> str:
        return _COLUMN_LAYOUT[self][0]

    @property
    def width(self) -> int:
        return _COLUMN_LAYOUT[self][1]


# Header text and starting width of each column
_COLUMN_LAYOUT = {
    Column.PULL: ("Pull", 40),
    Column.URL: ("URL", 400),
    Column.BRANCHES: ("Branches", 150),
    Column.LAST_PULLED: ("Last Pulled", 175),
    Column.STATUS: ("Status", 100),
}


class EntryStatus(StrEnum):
    """Fixed texts of the Status column. Progress and errors are formatted on top of these."""

    FETCHING = "Fetching..."
    DONE = "Done"


class TableRepoEntry(QWidget):
    """
    One row of the main table: a single repository, or a whole GitHub account.

    * `kind`: `EntryKind.REPO` or `EntryKind.ACCOUNT`
    * `key`: the settings key. The URL for a repository, the owner name for an account.
    * `repo`: the `Repository` for repository rows, `None` for accounts.
    """

    def __init__(self, url: str, kind: EntryKind = EntryKind.REPO, key: str = "", repo=None):
        super().__init__()

        self.kind = kind
        self.key = key or url.strip()
        self.repo = repo
        self._url = url.strip()

        self.pull_checkbox = QCheckBox()
        self.pull_checkbox_widget = AlignedWidget(self.pull_checkbox)
        self.pull_checkbox.setChecked(True)  # Default pull to true

        self.url_label = QLabel(self._display_text())

        self.branches_label = QLabel("-")
        self.branches_label_widget = AlignedWidget(self.branches_label, alignment=Qt.AlignLeft, margins=(5, 0, 0, 0))

        self.timestamp_label = QLabel("n/a")
        self.timestamp_widget = AlignedWidget(self.timestamp_label)

        self.status_label = QLabel()
        self.status_widget = AlignedWidget(self.status_label)

        layout = QHBoxLayout()
        layout.addWidget(self.pull_checkbox_widget)
        layout.addWidget(self.url_label)
        layout.addWidget(self.timestamp_widget)
        layout.addWidget(self.status_widget)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.setLayout(layout)

    def cell_widgets(self) -> dict[Column, QWidget]:
        """The widget shown in each table column for this row."""
        return {
            Column.PULL: self.pull_checkbox_widget,
            Column.URL: self.url_label,
            Column.BRANCHES: self.branches_label_widget,
            Column.LAST_PULLED: self.timestamp_widget,
            Column.STATUS: self.status_widget,
        }

    @property
    def is_account(self) -> bool:
        return self.kind == EntryKind.ACCOUNT

    def _display_text(self) -> str:
        return f"{self._url}  (account)" if self.is_account else self._url

    # ---------- Pull checkbox ----------

    def get_pull(self) -> bool:
        return self.pull_checkbox.isChecked()

    def set_pull(self, state: bool):
        self.pull_checkbox.setChecked(state)

    # ---------- URL ----------

    def get_url(self) -> str:
        return self._url

    def set_url(self, url: str):
        former_url = self._url
        self._url = url.strip()
        if not self.is_account:
            self.key = self._url
        self.url_label.setText(self._display_text())
        logger.info(f"Set new URL: {url} for former {former_url}")

    # ---------- Last pulled ----------

    def get_timestamp(self) -> str:
        return self.timestamp_label.text()

    def set_timestamp(self, value: str):
        self.timestamp_label.setText(value)
        logger.info(f"Set timestamp '{value}' [{self.get_url()}]")

    def set_timestamp_now(self):
        self.set_timestamp(timestamp(TimestampFormat.PULLED))

    # ---------- Status ----------

    def get_status(self) -> str:
        return self.status_label.text()

    def set_status(self, status: str):
        self.status_label.setText(status)
        logger.info(f"Set status '{status}' [{self.get_url()}]")

    # ---------- Branches ----------

    def set_branch_count(self, count: int):
        """Show how many branches the local backup holds. `0` shows a dash: no backup yet."""
        self.branches_label.setText(str(count) if count else "-")

    def set_branches_text(self, text: str):
        """Free text for the Branches column, used by account rows (ex.: "12 repos")."""
        self.branches_label.setText(text or "-")

import sys
from pathlib import Path
from typing import List
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QLabel, QTableWidget, QSizePolicy, QInputDialog, QDialog
)
from PySide6.QtCore import QSize, QDateTime, Qt

from log import create_logger
from . import __VERSION__
from conf_globals import G_LOG_LEVEL, THREAD_TIMEOUT_SECONDS
from libgit import Repository
from .utils import get_screen_info
from libgit import validate_github_url


logger = create_logger("src.ui.ui_main", G_LOG_LEVEL)

repos = []
to_path = (Path(__name__).parent.parent / "tests/gitclone/repos").resolve()


class AlignedWidget(QWidget):
    def __init__(self, widget, alignment=Qt.AlignCenter, margins: tuple =None):
        super().__init__()

        if not margins:
            margins = (0, 0, 0, 0)

        if len(margins) != 4:
            raise ValueError(f"Expected `margins` to have 4 elements, but got {len(margins)}: {margins}")
        
        logger.debug(f"{margins=} ({widget})")

        self.main_widget = widget
        layout = QHBoxLayout()
        layout.addWidget(self.main_widget, alignment=alignment)
        layout.setContentsMargins(*margins)
        
        if isinstance(widget, QLabel):
            self.main_widget.setStyleSheet(f"padding-left: {margins[0]}px; padding-top: {margins[1]}px; padding-right: {margins[2]}px; padding-bottom: {margins[3]}px;")

        self.setLayout(layout)


class TableEntry(QWidget):
    def __init__(self, url: str):
        super().__init__()

        self.pull_checkbox = QCheckBox()
        self.pull_checkbox_widget = AlignedWidget(self.pull_checkbox)
        self.pull_checkbox.setChecked(True) # Default pull to true

        self.branches_checkbox = QCheckBox()
        self.branches_checkbox_widget = AlignedWidget(self.branches_checkbox)

        self.branches_to_pull = []
        
        self.url_label = QLabel(url.strip())
        self.url_label_widget = AlignedWidget(self.url_label, alignment=Qt.AlignLeft, margins=(5, 0, 0, 0))
        
        self.timestamp_label = QLabel("n/a")
        self.timestamp_widget = AlignedWidget(self.timestamp_label)

        layout = QHBoxLayout()
        layout.addWidget(self.pull_checkbox_widget)
        layout.addWidget(self.url_label)
        layout.addWidget(self.timestamp_widget)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.setLayout(layout)

    def set_timestamp_now(self):
        """Sets the current timestamp on the timestamp_item."""
        _timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.timestamp_label.setText(_timestamp)
        logger.info(f"Set timestamp {_timestamp} of widget {self.timestamp_label}")

    def set_branches(self, branches_to_set: list = []):
        self.branches_to_pull = branches_to_set
        logger.info(f"Set new branches: {branches_to_set} for {self.url_label.text()}")

    def props(self) -> dict:
        """Returns the properties that comprise the entry for a saveable format

        * `do_pull` Checked state of the checkbox. `True` if checkbox is checked, `False` otherwise
        * `pull_branches` Checked state of the checkbox. `True` if checkbox is checked, `False` otherwise
        * `branches` List of branches to pull from repository
        * `url` URL string
        * `ts` Timestamp string
        """

        ret = {
            "do_pull": self.pull_checkbox.isChecked(),
            "pull_branches": self.branches_checkbox.isChecked(),
            "branches": self.branches_to_pull,
            "url": self.url_label.text(),
            "ts": self.timestamp_label.text()
        }

        return ret


class GitDatBackUI(QWidget):
    def __init__(self):
        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()

        super().__init__()
        
        # Set UI constraints
        self.setWindowTitle("Git Dat Back")
        self.resize(QSize(750, 400))

        # Tracking
        self.entries: List[TableEntry] = []

        # Main layout
        self.main_layout = QVBoxLayout()

        # Widgets
        # Input field layout
        self.input_layout = QHBoxLayout()
        
        # Input field
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL")
        
        # Submit input button
        self.submit_button = QPushButton("Submit")
        self.submit_button.clicked.connect(self.add_entry)

        # Info Label
        self.info_label = QLabel()
        
        # Main Table
        self.entry_table = QTableWidget(0, 4)
        self.entry_table.setHorizontalHeaderLabels(["Pull", "Branches", "URL", "Last Pulled"])
        self.entry_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.entry_table.cellDoubleClicked.connect(self.handle_cell_doubleclick)
        self.entry_table.horizontalHeader().setStretchLastSection(True)
        self.entry_table.setColumnWidth(0, 40)
        self.entry_table.setColumnWidth(1, 75)
        self.entry_table.setColumnWidth(2, 400)
        self.entry_table.setColumnWidth(3, 175)
        # Selection behaviour
        self.entry_table.setSelectionBehavior(QTableWidget.SelectRows) # Select full rows

        # Actions Layout - Where we put button actions
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 5, 0, 5)
        self.actions_layout.setSpacing(10) # Spacing between buttons

        # Remove Button Layout - Where we put button actions
        self.remove_button_layout = QHBoxLayout()
        self.remove_button_layout.setContentsMargins(0, 5, 0, 10)
        self.remove_button_layout.setSpacing(10) # Spacing between buttons

        # Removed Selected Button
        self.remove_selected_button = QPushButton("Remove Selected")
        self.remove_selected_button.clicked.connect(self.remove_selected_entries)
        self.remove_selected_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Select All Button
        self.set_all_selected_button = QPushButton("Select All")
        self.set_all_selected_button.clicked.connect(self.set_all_selected)
        self.set_all_selected_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Deselect All Button
        self.set_all_deselected_button = QPushButton("Deselect All")
        self.set_all_deselected_button.clicked.connect(self.set_all_deselected)
        self.set_all_deselected_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Pull Repos Button
        self.pull_button = QPushButton("Pull Repos")
        self.pull_button.clicked.connect(self.pull_repos)

        self.label_version = QLabel('v' + '.'.join([str(x) for x in __VERSION__]))
        self.label_version.setAlignment(Qt.AlignCenter)

        # Add widgets to input layout
        self.input_layout.addWidget(self.url_input)
        self.input_layout.addWidget(self.submit_button)

        # Add widget to actions_layout
        self.actions_layout.addWidget(self.set_all_selected_button)
        self.actions_layout.addWidget(self.set_all_deselected_button)
        self.actions_layout.addStretch()
        
        # Add widget to remove_button layout
        self.remove_button_layout.addWidget(self.remove_selected_button)
        self.remove_button_layout.addStretch()
        
        # Add widgets to main layout
        self.main_layout.addLayout(self.input_layout)
        self.main_layout.addWidget(self.info_label)
        self.main_layout.addLayout(self.actions_layout)
        self.main_layout.addWidget(self.entry_table)
        self.main_layout.addLayout(self.remove_button_layout)
        self.main_layout.addWidget(self.pull_button)
        self.main_layout.addWidget(self.label_version)

        self.setLayout(self.main_layout)

        # for repo in repos:
            # self.url_input.setText(repo)
            # self.add_entry()

    def add_entry(self):
        url = self.url_input.text().strip()

        if not url:
            self.tell(f"Nothing to add.")
            return
        
        if self.entry_exists(url):
            self.tell(f"{entry} already exists.")
            return
        
        # TODO: Don't always call Repository, we gonna get rate limited.
        if not validate_github_url(url):
            logger.info(f"Unable to add URL: {url}")
            return
        
        entry = TableEntry(url)

        row_pos = self.entry_table.rowCount()
        self.entry_table.insertRow(row_pos)

        self.entry_table.setCellWidget(row_pos, 0, entry.pull_checkbox_widget)
        self.entry_table.setCellWidget(row_pos, 1, entry.branches_checkbox_widget)
        self.entry_table.setCellWidget(row_pos, 2, entry.url_label)
        self.entry_table.setCellWidget(row_pos, 3, entry.timestamp_widget)

        self.entries.append(entry)

        logger.info(f"Added entry: {url}")
        self.tell(f"Added entry: {url}")

        self.url_input.clear()

    def handle_cell_doubleclick(self, row, col):
        clickable_cols = list(range(4))
        
        if col in clickable_cols:
            item = self.entry_table.item(row, col)
            entry_item = self.entries[row]
            entry_branches = entry_item.props().get("branches")
            prefilled = ', '.join(entry_branches)

            logger.debug(f"Entry: {entry_item} {entry_branches}")
            logger.debug(f"{prefilled=}")

            input_dialog = QInputDialog(self)
            input_dialog.setWindowTitle("Edit Branches")
            input_dialog.setLabelText("Branches (comma separated)")
            input_dialog.setTextValue(prefilled)
            input_dialog.resize(400, 200)

            if input_dialog.exec_() == QDialog.Accepted:
                branches = input_dialog.textValue()
                entry_item.set_branches(branches.split(','))

    def iter_entries(self):
        """Yield existing UrlEntry objects."""
        for entry in self.entries:
            yield entry

    def entry_exists(self, url: str) -> bool:
        for entry_widget in self.iter_entries():
            logger.debug(f"{entry_widget=}")
            if entry_widget.url_label.text() == url:
                logger.info(f"{url} already in list of entries.")
                return True
        
        return False

    def remove_selected_entries(self):
        selected = self.entry_table.selectionModel().selectedRows()

        for index in sorted(selected, reverse=True):
            entry_to_remove = self.entries[index.row()]
            self.entries.remove(entry_to_remove)
            self.entry_table.removeRow(index.row())

    def set_all_selected(self):
        for entry in self.iter_entries():
            entry.pull_checkbox.setChecked(True)

        self.tell("Selected all.")

    def set_all_deselected(self):
        for entry in self.iter_entries():
            entry.pull_checkbox.setChecked(False)

        self.tell("Deselected all.")

    def tell(self, what: str):
        self.info_label.setText(what.strip())

    def pull_repos(self):
        logger.warning("Pull Repos lacks full implementation.")
        repos = []

        for entry in self.iter_entries():
            props = entry.props()
            logger.debug(f"{props}")
            
            is_checked = props.get("isChecked")
            url = props.get("url")
            
            if is_checked:
                repos.append((Repository(url), entry))

        if not repos:
            self.tell("Nothing is checked.")
            return

        with ThreadPoolExecutor() as executor:
            logger.info(f"Submitting clone_all_task for repositories [{', '.join(repo.name for repo, entry in repos)}]")
            futures = {executor.submit(clone_all_task, repo, to_path): entry for repo, entry in repos}
            
            for future in futures:
                entry: TableEntry = futures[future]
                try:
                    f = future.result(timeout=THREAD_TIMEOUT_SECONDS)
                    logger.info(f"{f} Result awaited successful")
                    entry.set_timestamp_now()
                except Exception as e:
                    logger.error(f"Error cloning repository {e}")

            logger.info(f"Done awaiting all ({len(futures)}) futures")

    def show(self):
        super().show()
        self._adjust_app_size()
        sys.exit(self.app.exec())

    def _adjust_app_size(self):
        screen_info = get_screen_info(self.app)

        logger.debug(f"{screen_info=}")

        if not self:
            logger.warning("Not self")
            return

        if screen_info[0] <= 2000 or screen_info[1] <= 1200 or screen_info[2] <= 0.7:
            logger.info("Resizing application")
            self.resize(QSize(650, 500))


def clone_all_task(repo: Repository, to: Path):
    repo.clone_from(to)
    # repo.clone_branches()

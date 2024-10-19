import sys
from pathlib import Path
from typing import List
from queue import Queue
from time import sleep
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QLabel, QTableWidget, QSizePolicy, QInputDialog, QDialog, QFileDialog
)
from PySide6.QtCore import QSize, QDateTime, Qt, QRunnable, QThread, QThreadPool, QObject, Signal

from log import create_logger
from . import __VERSION__
from conf_globals import G_LOG_LEVEL
from libgit import Repository
from .utils import get_screen_info
from libgit import validate_github_url, get_branches_and_commits, api_status


logger = create_logger("src.ui.ui_main", G_LOG_LEVEL)

repos = []
to_path = (Path(__name__).parent.parent / "tests/gitclone/repos").resolve()


class TaskQueue(QObject):
    def __init__(self):
        super().__init__()
        self.queue = Queue()
        self.thread_pool = QThreadPool()
        self.is_running = True
        
        self.worker_thread = QThread()
        self.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.process_tasks)
        self.worker_thread.start()

    def add_task(self, task: QRunnable):
        self.queue.put(task)

    def process_tasks(self):
        while self.is_running:
            if self.queue.qsize() == 0:
                continue

            try:
                task = self.queue.get(timeout=1)
                logger.info(f"Submitting {task} to thread pool")
                self.thread_pool.start(task)
                sleep(1)
                self.queue.task_done()
            except Exception as e:
                logger.error(f"Error processing task: {e}")

    def stop(self):
        logger.info("Stopping Task Queue")
        self.is_running = False
        self.worker_thread.quit()
        self.worker_thread.wait()

    def cleanup(self):
        self.stop()


class WorkerSignals(QObject):
    finished = Signal(str)
    error = Signal(str, str)


class BranchTask(QRunnable):
    def __init__(self, url, callback):
        super().__init__()
        self.url = url
        self.callback = callback

    def run(self):
        try:
            result = get_branches_and_commits(self.url)
            self.callback(result)
        except Exception as e:
            logger.error(f"Error obtaining branches and commits for repository {self.url}: {e}")

class CloneRepoTask(QRunnable):
    def __init__(self, repo, path, entry):
        super().__init__()
        self.repo = repo
        self.path = path
        self.entry = entry
        self.signals = WorkerSignals()

    def run(self):
        try:
            logger.info(f"Cloning repository {self.repo.url} into {self.path}")
            self.repo.clone_from(self.path)
            self.signals.finished.emit(self.repo.url)
        except Exception as e:
            logger.error(f"Error cloning repository {self.repo.url}: {e}")
            self.signals.error.emit(self.repo.url, str(e))


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

    def set_url(self, url):
        former_url = self.url_label.text()
        self.url_label.setText(url)
        logger.info(f"Set new URL: {url} for former {former_url}")

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
            "do_pull": self.pull_checkbox.isChecked(),
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
        self.resize(QSize(810, 400))

        # Tasks
        self.task_queue = TaskQueue()

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
        self.entry_table.setHorizontalHeaderLabels(["Pull", "URL", "Branches", "Last Pulled"])
        self.entry_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.entry_table.cellDoubleClicked.connect(self.handle_cell_doubleclick)
        self.entry_table.horizontalHeader().setStretchLastSection(True)
        self.entry_table.setColumnWidth(0, 40)
        self.entry_table.setColumnWidth(1, 400)
        self.entry_table.setColumnWidth(2, 150)
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

        # Backup Path Layout
        self.backup_path_layout = QHBoxLayout()
        
        # Backup Path Input
        self.backup_path_input = QLineEdit()
        self.backup_path_input.setPlaceholderText("Root folder for repositories...")
        self.backup_path_input.setText(str(to_path))

        # Backup Path Pick Button
        self.backup_back_button = QPushButton("Pick")
        self.backup_back_button.clicked.connect(self.pick_backup_path)
        self.backup_back_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

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

        # Add widgets to backup path layout
        self.backup_path_layout.addWidget(self.backup_path_input)
        self.backup_path_layout.addWidget(self.backup_back_button)
        
        # Add widgets to main layout
        self.main_layout.addLayout(self.input_layout)
        self.main_layout.addWidget(self.info_label)
        self.main_layout.addLayout(self.actions_layout)
        self.main_layout.addWidget(self.entry_table)
        self.main_layout.addLayout(self.remove_button_layout)
        self.main_layout.addLayout(self.backup_path_layout)
        self.main_layout.addWidget(self.pull_button)
        self.main_layout.addWidget(self.label_version)

        self.setLayout(self.main_layout)

        for repo in repos:
            self.url_input.setText(repo)
            self.add_entry()

    def add_entry(self):
        url = self.url_input.text().strip()

        if not url:
            self.tell(f"Nothing to add.")
            return
        
        if self.entry_exists(url):
            self.tell(f"{entry} already exists.")
            return
        
        if not validate_github_url(url):
            logger.info(f"Unable to validate URL: {url}")
            self.tell(f"Unable to validate {url}")
            return
        
        entry = TableEntry(url)

        row_pos = self.entry_table.rowCount()
        self.entry_table.insertRow(row_pos)

        self.entry_table.setCellWidget(row_pos, 0, entry.pull_checkbox_widget)
        self.entry_table.setCellWidget(row_pos, 1, entry.url_label)
        self.entry_table.setCellWidget(row_pos, 2, entry.branches_label_widget)
        self.entry_table.setCellWidget(row_pos, 3, entry.timestamp_widget)

        self.entries.append(entry)

        logger.info(f"Added entry: {url}")
        self.tell(f"Added entry: {url}")

        # branch_task = BranchTask(url, lambda res: self._update_entry_branches(entry, res))
        # self.task_queue.add_task(branch_task)

        # entry.branches_label.setText("Fecthing...")

        self.url_input.clear()

    def _update_entry_branches(self, entry, result):
        # TODO: When we are finally saving to a file, check if there are branches saved before we pull from the api

        logger.info(f"Update Entry {entry} with {result}")
        branches = []

        status = result[0]
        branch_info = result[1]

        if status != 200:
            code = str(status)
            if status == 403:
                code += " (Rate limited)"
            elif status == 404:
                code += " (Not found)"
            branches.append(code)
        else:
            for branch_name, branch_info in branch_info.items():
                branches.append(branch_name)

        entry.set_branches(branches)

    def handle_cell_doubleclick(self, row, col):
        clickable_cols = [1, 2]
        
        if col in clickable_cols:
            if col == clickable_cols[0]:
                item = self.entry_table.item(row, col)
                entry_item = self.entries[row]
                entry_url = entry_item.props().get("url")
                prefilled = entry_url

                logger.debug(f"Entry: {entry_item} {entry_url}")
                logger.debug(f"{prefilled=}")

                input_dialog = QInputDialog(self)
                input_dialog.setWindowTitle("Edit URL")
                input_dialog.setLabelText("New URL:")
                input_dialog.setTextValue(prefilled)
                input_dialog.resize(400, 200)

                if input_dialog.exec_() == QDialog.Accepted:
                    new_url = input_dialog.textValue()
                    if validate_github_url(new_url):
                        entry_item.set_url(new_url)
            elif col == clickable_cols[1]:
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

    def pick_backup_path(self):
        choice = QFileDialog.getExistingDirectory(self, "Select root folder", dir=str(to_path))
        folder_path = Path(choice).resolve()

        if choice:
            self.backup_path_input.setText(str(folder_path))
            logger.info(f"Backup path: {choice}")
        else:
            logger.info(f"User aborted backup path selection.")

    def tell(self, what: str):
        self.info_label.setText(what.strip())

    def pull_repos(self):
        logger.warning("Pull Repos lacks full implementation.")
        repos = []

        for entry in self.iter_entries():
            props = entry.props()
            logger.debug(f"{props}")
            
            is_checked = props.get("do_pull")
            url = props.get("url")
            
            if is_checked:
                repos.append((Repository(url), entry))

        if not repos:
            self.tell("Nothing is checked.")
            return

        for repo, entry in repos:
            clone_task = CloneRepoTask(repo, self.backup_path_input.text(), entry)

            # Connect the signals
            clone_task.signals.finished.connect(self.on_clone_success)
            clone_task.signals.error.connect(self.on_clone_error)

            self.task_queue.add_task(clone_task)

    def on_clone_success(self, repo_name):
        logger.info(f"Cloning completed for: {repo_name}")

        for entry in self.entries:  
            if entry.url_label.text() == repo_name:
                entry.set_timestamp_now()
                
    def on_clone_error(self, repo_name, error_msg):
        logger.error(f"Error cloning repository {repo_name}: {error_msg}")
        self.tell(f"Error cloning {repo_name}: {error_msg}")

    def show(self):
        super().show()
        self._adjust_app_size()
        sys.exit(self.app.exec())

    def closeEvent(self, event):
        logger.info("Application is closing. Shutting down procedure")
        self.task_queue.stop()
        event.accept()

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

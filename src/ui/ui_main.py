import sys
from pathlib import Path
from typing import List
from queue import Queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QLabel, QTableWidget, QSizePolicy, QInputDialog, QDialog, 
    QFileDialog, QDialogButtonBox, QTextEdit, QComboBox
)
from PySide6.QtCore import QSize, QDateTime, Qt, QRunnable, QThread, QThreadPool, QObject, Signal

from .utils import get_screen_info
from conf_globals import G_LOG_LEVEL, VERSION, MAX_CONCURRENT_TASKS
from log import create_logger
from settings import Settings
from libgit import Repository
from libgit import validate_github_url, get_branches_and_commits, api_status
import systemd

logger = create_logger(__name__, G_LOG_LEVEL)


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


class TaskQueue(QObject):
    _task_lock = threading.Lock()
    _ongoing_tasks: int = 0
    MAX_CONCURRENT_TASKS: int = MAX_CONCURRENT_TASKS

    def __init__(self):
        super().__init__()
        self.queue = Queue()
        self.thread_pool = QThreadPool()
        self.is_running = True
        
        self.worker_thread = QThread()
        self.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.process_tasks)
        self.worker_thread.start()

    @classmethod
    def get_ongoing_tasks(cls) -> int:
        with cls._task_lock:
            return cls._ongoing_tasks
        
    @classmethod
    def increment_ongoing_tasks(cls) -> bool:
        with cls._task_lock:
            if cls._ongoing_tasks < cls.MAX_CONCURRENT_TASKS:
                cls._ongoing_tasks += 1
                return True
            return False
        
    @classmethod
    def decrement_ongoing_tasks(cls):
        with cls._task_lock:
            if cls._ongoing_tasks > 0:
                cls._ongoing_tasks -= 1

    def add_task(self, task: QRunnable | CloneRepoTask):
        self.queue.put(task)
        logger.debug(f"Put task: {task.entry.get_url()}")

    def process_tasks(self):
        while self.is_running:
            if self.queue.qsize() == 0:
                sleep(1) # Prevent busy waiting
                continue

            try:
                # Peek without taking
                task = self.queue.queue[0]

                # Try to increment the task counter
                if self.increment_ongoing_tasks():
                    task = self.queue.get(timeout=1)
                    logger.info(f"Got task {task.entry.get_url()}! Ongoing: {self.get_ongoing_tasks()}")

                    # Wrap run method to handle completion
                    original_run = task.run
                    def wrapped_run():
                        try:
                            original_run()
                        except Exception as e:
                            logger.error(f"Error in wrapped run: {e}")
                        finally:
                            self.decrement_ongoing_tasks()
                            logger.debug(f"Task completed. Remaining active tasks: {self.get_ongoing_tasks()}")

                    task.run = wrapped_run

                    # Start the task
                    self.thread_pool.start(task)
                    self.queue.task_done()
                else:
                    # If we can't process now, wait before trying again
                    logger.debug(f"Max concurrent tasks reached ({self.MAX_CONCURRENT_TASKS}). Tasks in queue: {self.queue.qsize()}")
                    sleep(1)
                continue
            except Exception as e:
                logger.error(f"Error processing task: {e}")
                self.decrement_ongoing_tasks()

    def stop(self):
        logger.info("Stopping Task Queue")
        self.is_running = False
        self.worker_thread.quit()
        self.worker_thread.wait()

    def cleanup(self):
        self.stop()

    @classmethod
    def reset_task_counter(cls):
        with cls._task_lock:
            cls._ongoing_tasks = 0


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


class ServiceConfigWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Service Settings")
        self.setModal(True) # Blocks interaction with parent window
        self.resize(QSize(300, 200))

        self.settings = Settings()
        self.settings.load_config()

        self.selected_day = self.settings.get_scheduled_day()
        self.selected_time = self.settings.get_scheduled_time()
        self.selected_hour = self.selected_time.split(':')[0]
        self.selected_min = self.selected_time.split(':')[1]

        logger.debug(f"{self.selected_time=}")
        logger.debug(f"{self.selected_hour=}")
        logger.debug(f"{self.selected_min=}")

        main_layout = QVBoxLayout()

        service_date_widgets_layout = QHBoxLayout()
        
        # Schedule Widget
        date_widgets_label = QLabel("Schedule:")
        
        # Week Days Combobox
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        self.week_day_dropdown = QComboBox()
        self.week_day_dropdown.addItems(days)
        if self.selected_day in days:
            self.week_day_dropdown.setCurrentText(self.selected_day)

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
        service_date_widgets_layout.addWidget(date_widgets_label)
        service_date_widgets_layout.addWidget(self.week_day_dropdown)
        service_date_widgets_layout.addWidget(self.hours_dropdown)
        service_date_widgets_layout.addWidget(hour_sep)
        service_date_widgets_layout.addWidget(self.minutes_dropdown)
        service_date_widgets_layout.addStretch()
        
        # Add to main layout
        main_layout.addLayout(service_date_widgets_layout)
        main_layout.addWidget(ok_button)

        self.setLayout(main_layout)

    def get_selected_values(self):
        return self.selected_day, self.selected_time
    
    def accept(self):
        self.selected_day = self.week_day_dropdown.currentText()
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


class AlertDialog(QDialog):
    def __init__(self, alert: str, title: str="Alert"):
        super().__init__()

        self.alert_text = alert
        self.title = title

        self.setWindowTitle(title)

        self.resize(QSize(400, 200))

        QBtn = (
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )

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

    def set_timestamp(self, timestamp: str):
        """Sets the timestamp on the timestamp_item."""
        self.timestamp_label.setText(timestamp)
        logger.info(f"Set timestamp {timestamp} of widget {self.timestamp_label}")

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


class GitDatBackUI(QWidget):
    APP_VERSION_STR = 'v' + '.'.join([str(x) for x in VERSION])

    def __init__(self):
        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()

        super().__init__()

        self.settings = Settings()
        self.settings.load_config() # Load the config

        window_size = self.settings.get_window_size()
        logger.info(f"{window_size=}")

        self.repo_backup_path = self.settings.get_save_root_dir(fallback=(Path(__name__).parent.parent / "tests/gitclone/repos").resolve())
        
        # Set app constraints
        self.setWindowTitle(f"Git Dat Back ({self.APP_VERSION_STR})")
        if not window_size:
            # Default
            self.resize(QSize(810, 450))
        else:
            self.resize(QSize(window_size[0], window_size[1]))

        # Tasks
        self.task_queue = TaskQueue()

        # Tracking
        self.entries: List[TableEntry] = []

        # Main layout
        main_layout = QVBoxLayout()

        # Widgets
        # Input field layout
        input_layout = QHBoxLayout()
        
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
        remove_button_layout = QHBoxLayout()
        remove_button_layout.setContentsMargins(0, 5, 0, 10)
        remove_button_layout.setSpacing(10) # Spacing between buttons

        # Removed Selected Button
        self.remove_selected_button = QPushButton("Remove Selected")
        self.remove_selected_button.clicked.connect(self.remove_selected_entries)
        self.remove_selected_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Select Selected Button
        self.set_selection_selected_button = QPushButton("Select Selected")
        self.set_selection_selected_button.clicked.connect(self.set_selection_selected)
        self.set_selection_selected_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Deselect Selected Button
        self.set_selection_deselected_button = QPushButton("Deselect Selected")
        self.set_selection_deselected_button.clicked.connect(self.set_selection_deselected)
        self.set_selection_deselected_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

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
        self.backup_path_input.setText(str(self.repo_backup_path))
        self.backup_path_input.editingFinished.connect(self.set_backup_path)

        # Backup Path Pick Button
        self.pick_backup_path_button = QPushButton("Pick")
        self.pick_backup_path_button.clicked.connect(self.pick_backup_path)
        self.pick_backup_path_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Pull Repos Button
        self.pull_button = QPushButton("Pull Repos")
        self.pull_button.clicked.connect(self.pull_repos)

        # Register Services Buttons layout
        register_services_layout = QHBoxLayout()

        # Service Options
        self.service_options_button = QPushButton("Service Options")
        self.service_options_button.clicked.connect(self.show_service_options_dialog)

        # Register Service Button
        self.register_service_button = QPushButton("Register Service")
        self.register_service_button.clicked.connect(self.register_background_service)

        # Unregister Service Button
        self.unregister_service_button = QPushButton("Unregister Service")
        self.unregister_service_button.clicked.connect(self.unregister_background_service)

        # Add widgets to input layout
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.submit_button)

        # Add widget to actions_layout
        self.actions_layout.addWidget(self.set_selection_selected_button)
        self.actions_layout.addWidget(self.set_selection_deselected_button)
        self.actions_layout.addWidget(self.set_all_selected_button)
        self.actions_layout.addWidget(self.set_all_deselected_button)
        self.actions_layout.addStretch()
        
        # Add widget to remove_button layout
        remove_button_layout.addWidget(self.remove_selected_button)
        remove_button_layout.addStretch()

        # Add widgets to backup path layout
        self.backup_path_layout.addWidget(self.backup_path_input)
        self.backup_path_layout.addWidget(self.pick_backup_path_button)

        # Add widgets to register services layout
        register_services_layout.addWidget(self.service_options_button)
        register_services_layout.addWidget(self.register_service_button)
        register_services_layout.addWidget(self.unregister_service_button)
        register_services_layout.addStretch()
        
        # Add widgets to main layout
        main_layout.addLayout(input_layout)
        main_layout.addWidget(self.info_label)
        main_layout.addLayout(self.actions_layout)
        main_layout.addWidget(self.entry_table)
        main_layout.addLayout(remove_button_layout)
        main_layout.addLayout(self.backup_path_layout)
        main_layout.addLayout(register_services_layout)
        main_layout.addWidget(self.pull_button)

        self.setLayout(main_layout)

        self.load_saved_repos()

    def load_saved_repos(self):
        if not self.settings:
            logger.warning(f"No settings class??")
            return
        
        repos = self.settings.get_repos()

        for repo_url, info in repos.items():
            do_pull = info.get(Settings.KEY_DO_PULL)
            timestamp = info.get(Settings.KEY_LAST_PULLED)
            branches = info.get(Settings.KEY_BRANCHES)
            
            self.add_to_table(repo_url, do_pull, timestamp, branches=branches)

        self.tell("Status: Ready")

        self.url_input.clear()

    def add_entry(self):
        # Manual user entry submission
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
        
        entry = self.add_to_table(url, True, "n/a")

        # Save to settings
        self.settings.save_repo(url, entry.pull_checkbox.isChecked())

        # branch_task = BranchTask(url, lambda res: self._update_entry_branches(entry, res))
        # self.task_queue.add_task(branch_task)

        # entry.branches_label.setText("Fecthing...")

        self.url_input.clear()

    def add_to_table(self, url: str, do_pull: bool, timestamp: str = "", branches: list = []) -> TableEntry:
        entry = TableEntry(url)

        row_pos = self.entry_table.rowCount()
        self.entry_table.insertRow(row_pos)

        self.entry_table.setCellWidget(row_pos, 0, entry.pull_checkbox_widget)
        self.entry_table.setCellWidget(row_pos, 1, entry.url_label)
        self.entry_table.setCellWidget(row_pos, 2, entry.branches_label_widget)
        self.entry_table.setCellWidget(row_pos, 3, entry.timestamp_widget)

        # Handle pull checkbox
        entry.set_pull(do_pull)

        # Handle timestamp
        if timestamp:
            entry.set_timestamp(timestamp)

        # Handle branches
        if branches:
            entry.set_branches(branches)

        self.entries.append(entry)

        logger.info(f"Added entry: {url}")
        self.tell(f"Added entry: {url}")

        return entry

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
                entry_url = entry_item.get_url()
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
                        logger.info(f"Edited {entry_url} to {new_url}")
                        self.tell(f"Edited {entry_url} to {new_url}")
            elif col == clickable_cols[1]:
                item = self.entry_table.item(row, col)
                entry_item = self.entries[row]
                entry_url = entry_item.get_url()
                entry_branches = entry_item.get_branches()
                prefilled = ', '.join(entry_branches)

                logger.debug(f"Entry: {entry_item} {entry_branches}")
                logger.debug(f"{prefilled=}")

                input_dialog = QInputDialog(self)
                input_dialog.setWindowTitle("Edit Branches")
                input_dialog.setLabelText("Branches (comma separated)")
                input_dialog.setTextValue(prefilled)
                input_dialog.resize(400, 200)

                if input_dialog.exec_() == QDialog.Accepted:
                    branches = [b.strip() for b in input_dialog.textValue().split(',')]
                    entry_item.set_branches(branches)
                    logger.info(f"Updated branches of {entry_url}: {branches}")
                    self.tell(f"Updated branches of {entry_url.split('/')[-1]}: {branches}")

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
            entry_url = entry_to_remove.get_url()

            self.settings.remove_repo(entry_url)

            self.entries.remove(entry_to_remove)
            self.entry_table.removeRow(index.row())

    def set_selection_selected(self):
        selected_indices = [n.row() for n in self.entry_table.selectionModel().selectedRows()]
        logger.debug(f"{selected_indices=}")

        for index in selected_indices:
            entry = self.entries[index]
            entry.set_pull(True)

        self.tell("Selected selection.")

    def set_selection_deselected(self):
        selected_indices = [n.row() for n in self.entry_table.selectionModel().selectedRows()]
        logger.debug(f"{selected_indices=}")

        for index in selected_indices:
            entry = self.entries[index]
            entry.set_pull(False)

        self.tell("Deselected selection.")

    def set_all_selected(self):
        for entry in self.iter_entries():
            entry.set_pull(True)

        self.tell("Selected all.")

    def set_all_deselected(self):
        for entry in self.iter_entries():
            entry.set_pull(False)

        self.tell("Deselected all.")

    def pick_backup_path(self):
        choice = QFileDialog.getExistingDirectory(self, "Select root folder", dir=str(self.repo_backup_path))

        if choice:
            self.set_backup_path()
        else:
            logger.info(f"User aborted backup path selection.")

    def set_backup_path(self):
        choice = self.backup_path_input.text()

        if choice:
            folder_path = Path(self.backup_path_input.text()).resolve()
            self.backup_path_input.setText(str(folder_path))
            self.repo_backup_path = folder_path
            logger.info(f"Backup path: {folder_path}")

    def tell(self, what: str):
        self.info_label.setText(what.strip())

    def pull_repos(self):
        self.set_buttons_state_while_task(False)

        repos = []

        for entry in self.iter_entries():
            is_checked = entry.get_pull()
            url = entry.get_url()
            
            logger.debug(f"{url=}")
            logger.debug(f"{is_checked=}")
            
            if is_checked:
                repos.append((Repository(url), entry))
                entry.set_timestamp("Fetching...")

        if not repos:
            self.tell("Nothing is checked.")
            return

        for repo, entry in repos:
            clone_task = CloneRepoTask(repo, self.repo_backup_path, entry)
            logger.debug(f"Task {entry.get_url()}")

            # Connect the signals
            clone_task.signals.finished.connect(self.on_clone_success)
            clone_task.signals.error.connect(self.on_clone_error)

            self.task_queue.add_task(clone_task)

        self.set_buttons_state_while_task(True)

    @staticmethod
    def pull_repos_no_ui():
        logger.warning("Pull Repos lacks full implementation.")
        repos: list[Repository] = []

        settings = Settings()
        settings.load_config()
        saved_repos = settings.get_repos()

        logger.info("Iterating saved repos...")
        for url, info in saved_repos.items():
            logger.info(f"{url}")
            logger.info(f"{info=}")
            if info.get(settings.KEY_DO_PULL, False):
                repos.append(Repository(url))
                logger.info(f"Collected repo {url}")

        save_to = settings.get_save_root_dir(fallback=(Path(__name__).parent.parent / "tests/gitclone/repos").resolve())
        logger.info(f"Cloning to root directory: {str(save_to)}")

        # Function to clone a repository and update the settings
        def clone_and_update_repo(repo: Repository):
            repo.clone_from(save_to)
            url = repo.url
            do_pull = saved_repos[url].get(settings.KEY_DO_PULL)
            timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
            branches = saved_repos[url].get(settings.KEY_BRANCHES, [])
            settings.save_repo(url, do_pull=do_pull, timestamp=timestamp, branches=branches)
            logger.info(f"Finished processing {url}")

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS) as executor:
            future_to_repo = {executor.submit(clone_and_update_repo, repo): repo for repo in repos}

            for future in as_completed(future_to_repo):
                repo = future_to_repo[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Error pulling repository: {repo.url}: {e}")
            
        logger.info("Pull Repos No UI finished")

    def on_clone_success(self, repo_name):
        logger.info(f"Cloning completed for: {repo_name}")

        for entry in self.entries:  
            if entry.url_label.text() == repo_name:
                entry.set_timestamp_now()

        self.tell(f"Cloning completed for: {repo_name}")

    def set_button_state(self,button_widget: QPushButton, state: bool):
        button_widget.setEnabled(state)

    def set_buttons_state_while_task(self, state: bool):
        self.set_button_state(self.submit_button, state)
        self.set_button_state(self.set_selection_selected_button, state)
        self.set_button_state(self.set_selection_deselected_button, state)
        self.set_button_state(self.set_all_selected_button, state)
        self.set_button_state(self.set_all_deselected_button, state)
        self.set_button_state(self.remove_selected_button, state)
        self.set_button_state(self.pick_backup_path_button, state)
        self.set_button_state(self.service_options_button, state)
        self.set_button_state(self.register_service_button, state)
        self.set_button_state(self.unregister_service_button, state)
        self.set_button_state(self.pull_button, state)
                
    def on_clone_error(self, repo_name, error_msg):
        logger.error(f"Error cloning repository {repo_name}: {error_msg}")
        self.tell(f"Error cloning {repo_name}: {error_msg}")

        for entry in self.entries:  
            if entry.url_label.text() == repo_name:
                entry.set_timestamp("Error")

    def show_service_options_dialog(self):
        service_dialog = ServiceConfigWindow(self)
        result = service_dialog.exec()

        # Handle results
        if result == QDialog.DialogCode.Accepted:
            logger.info("Accepted new service settings")
            day, time = service_dialog.get_selected_values()
            logger.info(f"Set new schedule: {day}, {time}")
            self.settings.set_scheduled_day(day)
            self.settings.set_scheduled_time(time)
            self.settings.save_config()
        else:
            logger.info("Cancelled service settings")

    def register_background_service(self):
        day = self.settings.get_scheduled_day()
        time = self.settings.get_scheduled_time()

        if day or time:
            logger.info(f"Want to register service with custom schedule: {day} - {time}")
            success, status = systemd.register_service(day=day, time=time)
        else:
            logger.info(f"Want to register service with default schedule")
            success, status = systemd.register_service(day=day, time=time)
        if success:
            self.tell("Command copied to clipboard. Run in Terminal to register.")
            clipboard = self.app.clipboard()
            clipboard.setText(status)
            AlertDialog("Some code has been copied to the clipboard. Please run it in your preferred Terminal application.", title="Set Background Service")

    def unregister_background_service(self):            
        success, status = systemd.unregister_service()
        if success:
            self.tell("Command copied to clipboard. Run in Terminal to unregister.")
            clipboard = self.app.clipboard()
            clipboard.setText(status)
            AlertDialog("Some code has been copied to the clipboard. Please run it in your preferred Terminal application.", title="Set Background Service")

    def show(self):
        super().show()
        self._adjust_app_size()
        sys.exit(self.app.exec())

    def closeEvent(self, event):
        logger.info("Application is closing. Shutting down procedure")
        self.task_queue.stop()
        
        # Save root directory for repo backups
        self.settings.set_save_root_dir(self.repo_backup_path)
        
        # Save state of each widget entry in the table
        for entry in self.iter_entries():
            repo_url = entry.url_label.text()
            branches = entry.branches_to_pull
            do_pull = entry.pull_checkbox.isChecked()
            timestamp = entry.timestamp_label.text()
            if timestamp in ["n/a", "Fetching..."] or not timestamp:
                timestamp = ""

            self.settings.save_repo(repo_url, do_pull=do_pull, timestamp=timestamp, branches=branches)

        # Save the window size
        width = self.frameGeometry().width()
        height = self.frameGeometry().height() - 36
        self.settings.save_window_size(width, height)

        self.settings.save_config()
        
        logger.info("Shutdown")
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

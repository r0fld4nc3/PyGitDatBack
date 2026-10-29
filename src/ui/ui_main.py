import logging
import sys
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSize, QThreadPool
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import settings
import systemd
from backups import AccountProgress, BackupRun
from defines import APP_NAME, APP_VERSION_STR, DRY_RUN, EntryKind
from libgit import (
    AccountPlan,
    Repository,
    existing_backups,
    github_url,
    owner_backup_dir,
    parse_github_url,
    plan_account,
    remove_dir,
)
from utils import TimestampFormat, timestamp

from .classes import (
    AlertDialog,
    BackupTask,
    Column,
    EntryStatus,
    FunctionTask,
    RepoPickerDialog,
    ServiceConfigWindow,
    TableRepoEntry,
)
from .utils import get_screen_info

logger = logging.getLogger(__name__)

SETTINGS_BUTTON_SIZE = 32  # px, square
SETTINGS_ICON_SIZE = 20  # px, for the future cogwheel image


class PullScope(Enum):
    """Which rows the tick/untick buttons apply to."""

    SELECTED = auto()
    ALL = auto()


class GitDatBackUI(QWidget):
    APP_VERSION_STR = f"{APP_VERSION_STR}"

    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)

        super().__init__()

        # Settings manager. Values in `self.config.settings`
        self.config = settings.get()

        self.setWindowTitle(f"{APP_NAME} ({self.APP_VERSION_STR})")
        self.resize(QSize(self.config.settings.window_width, self.config.settings.window_height))

        # Background work, at most `max_concurrent_tasks` at a time
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(self.config.settings.max_concurrent_tasks)

        # Each row is a repository or an account, see TableRepoEntry
        self.entries: list[TableRepoEntry] = []

        # State of the pull in progress, see pull_repos()
        self._run: Optional[BackupRun] = None
        self._run_pending = 0  # Tasks still to report back. The run is over at 0
        self._run_rows: dict[str, TableRepoEntry] = {}  # Repository URL -> row it is reported on

        self._build_ui()
        self.load_saved_repos()

    # ---------- Building the window ----------

    def _build_ui(self):
        main_layout = QVBoxLayout()
        # Settings layout/row
        # main_layout.addLayout(self._build_settings_row())

        # Add url row
        main_layout.addLayout(self._build_input_row())

        self.info_label = QLabel()
        main_layout.addWidget(self.info_label)

        # Table Actions Buttons
        main_layout.addLayout(self._build_table_actions_buttons_row())
        main_layout.addWidget(self._build_table())

        # Remove Selected
        self.remove_selected_button = self._button("Remove Selected", self.remove_selected_entries, fixed=True)
        main_layout.addLayout(self._row([self.remove_selected_button], margins=(0, 5, 0, 10), stretch=True))

        # Backup Path Edit and Layout
        main_layout.addLayout(self._build_backup_path_rows())

        # Service Buttons
        self.service_options_button = self._button("Service Options", self.show_service_options_dialog)
        self.register_service_button = self._button("Register Service", self.register_background_service)
        self.unregister_service_button = self._button("Unregister Service", self.unregister_background_service)
        main_layout.addLayout(
            self._row(
                [self.service_options_button, self.register_service_button, self.unregister_service_button],
                stretch=True,
            )
        )

        # Pull Repos main button
        self.pull_button = self._button("Pull Repos", self.pull_repos)
        self.pull_button.setMinimumHeight(40)
        main_layout.addWidget(self.pull_button)

        self.setLayout(main_layout)

        # Disabled while a pull runs
        self._task_buttons = [
            self.submit_button,
            self.settings_button,
            self.set_selection_selected_button,
            self.set_selection_deselected_button,
            self.set_all_selected_button,
            self.set_all_deselected_button,
            self.remove_selected_button,
            self.pick_backup_path_button,
            self.service_options_button,
            self.register_service_button,
            self.unregister_service_button,
            self.pull_button,
        ]

    def _build_input_row(self) -> QHBoxLayout:
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "Repository URL, or account URL (https://github.com/<user>/) for all its repositories"
        )
        self.submit_button = self._button("Add", self.add_entry)
        self.settings_button = self._build_settings_button()
        return self._row([self.url_input, self.submit_button, self.settings_button])

    def _build_table_actions_buttons_row(self) -> QHBoxLayout:
        self.set_selection_selected_button = self._button(
            "Select Selected", lambda: self.set_pull(PullScope.SELECTED, True), fixed=True
        )
        self.set_selection_deselected_button = self._button(
            "Deselect Selected", lambda: self.set_pull(PullScope.SELECTED, False), fixed=True
        )
        self.set_all_selected_button = self._button(
            "Select All", lambda: self.set_pull(PullScope.ALL, True), fixed=True
        )
        self.set_all_deselected_button = self._button(
            "Deselect All", lambda: self.set_pull(PullScope.ALL, False), fixed=True
        )
        return self._row(
            [
                self.set_selection_selected_button,
                self.set_selection_deselected_button,
                self.set_all_selected_button,
                self.set_all_deselected_button,
            ],
            margins=(0, 5, 0, 5),
            stretch=True,
        )

    def _build_table(self) -> QTableWidget:
        self.entry_table = QTableWidget(0, len(Column))
        self.entry_table.setHorizontalHeaderLabels([column.header for column in Column])
        self.entry_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.entry_table.cellDoubleClicked.connect(self.handle_cell_doubleclick)
        self.entry_table.horizontalHeader().setStretchLastSection(True)
        for column in Column:
            self.entry_table.setColumnWidth(column, column.width)
        self.entry_table.setSelectionBehavior(QTableWidget.SelectRows)  # Select full rows
        return self.entry_table

    def _build_backup_path_rows(self) -> QVBoxLayout:
        self.backup_path_input = QLineEdit()
        self.backup_path_input.setPlaceholderText("Root folder for repositories...")
        self.backup_path_input.setText(str(self.repos_backup_path))
        self.backup_path_input.editingFinished.connect(self.set_backup_path)
        self.backup_path_input.setDisabled(False)

        self.pick_backup_path_button = self._button("Pick", self.pick_backup_path, fixed=True)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Backup Location:"))
        layout.addLayout(self._row([self.backup_path_input, self.pick_backup_path_button]))
        return layout

    def _build_settings_button(self) -> QToolButton:
        # Tool button: Qt's widget for icon buttons. Fixed size keeps it square whatever the window does.
        settings_button = QToolButton()
        settings_button.setFixedSize(SETTINGS_BUTTON_SIZE, SETTINGS_BUTTON_SIZE)
        settings_button.setToolTip("Settings")
        settings_button.clicked.connect(self.open_settings_dialog)

        # Placeholder until there is an image.
        #   settings_button.setIcon(QIcon("<path to icon>"))
        #   settings_button.setIconSize(QSize(SETTINGS_ICON_SIZE, SETTINGS_ICON_SIZE))
        settings_button.setText("⚙")
        font = settings_button.font()
        font.setPointSize(16)
        settings_button.setFont(font)

        return settings_button

    def _build_settings_row(self) -> QHBoxLayout:
        self.settings_button = self._build_settings_button()

        # The stretch takes all free space on the left, pinning the button to the window's right edge
        layout = QHBoxLayout()
        layout.addStretch()
        layout.addWidget(self.settings_button)
        return layout

    def open_settings_dialog(self):
        # TODO: dialog for editable settings (max concurrent tasks, ...)
        logger.info("Settings dialog not implemented yet")

    @staticmethod
    def _button(text: str, slot: Callable, fixed: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        if fixed:
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return button

    @staticmethod
    def _row(widgets: list[QWidget], margins: Optional[tuple] = None, stretch: bool = False) -> QHBoxLayout:
        layout = QHBoxLayout()
        if margins:
            layout.setContentsMargins(*margins)
            layout.setSpacing(10)
        for widget in widgets:
            layout.addWidget(widget)
        if stretch:
            layout.addStretch()
        return layout

    # ---------- Rows ----------

    @property
    def repos_backup_path(self) -> Path:
        """Root folder for backups, always read from settings."""
        return self.config.settings.backup_root_path()

    def load_saved_repos(self):
        for owner, account_settings in self.config.settings.accounts.items():
            self.add_account_row(owner, account_settings.do_pull, account_settings.last_pulled)

        for url, repo_settings in self.config.settings.repos.items():
            try:
                self.add_repo_row(url, repo_settings.do_pull, repo_settings.last_pulled)
            except ValueError as e:
                logger.warning(f"Skipping saved repository: {e}")

        self.tell("Status: Ready")
        self.url_input.clear()

    def add_entry(self):
        url = self.url_input.text().strip()

        if not url:
            self.tell("Nothing to add.")
            return

        target = parse_github_url(url)
        if target is None:
            logger.info(f"Unable to validate URL: {url}")
            self.tell(f"Unable to validate {url}")
            return

        if target.kind == EntryKind.ACCOUNT:
            if self.find_entry(EntryKind.ACCOUNT, target.owner):
                self.tell(f"Account {target.owner} already added.")
                return

            self.config.account(target.owner)  # Adds and saves it
            entry = self.add_account_row(target.owner, True, "n/a")
            self.url_input.clear()
            # Let the user untick repositories straight away
            self.choose_account_repos(entry)
            return

        if self.find_entry(EntryKind.REPO, target.url) or self.find_entry(EntryKind.REPO, url):
            self.tell(f"{url} already exists.")
            return

        self.config.repo(target.url)  # Adds and saves it
        self.add_repo_row(target.url, True, "n/a")
        self.url_input.clear()

    def add_repo_row(self, url: str, do_pull: bool, last_pulled: str = "") -> TableRepoEntry:
        repo = Repository(url)
        entry = TableRepoEntry(url, EntryKind.REPO, url, repo=repo)
        entry.set_branch_count(repo.branch_count(self.repos_backup_path))
        return self._insert_row(entry, do_pull, last_pulled)

    def add_account_row(self, owner: str, do_pull: bool, last_pulled: str = "") -> TableRepoEntry:
        entry = TableRepoEntry(github_url(owner), EntryKind.ACCOUNT, owner)
        entry.url_label.setToolTip("Double-click to choose which repositories to back up")
        self._update_account_summary(entry)
        return self._insert_row(entry, do_pull, last_pulled)

    def _insert_row(self, entry: TableRepoEntry, do_pull: bool, last_pulled: str) -> TableRepoEntry:
        row_pos = self.entry_table.rowCount()
        self.entry_table.insertRow(row_pos)

        for column, widget in entry.cell_widgets().items():
            self.entry_table.setCellWidget(row_pos, column, widget)

        # Connected after setting it, so loading doesn't write anything
        entry.set_pull(do_pull)
        entry.pull_checkbox.toggled.connect(lambda checked, e=entry: self._on_pull_toggled(e, checked))

        if last_pulled:
            entry.set_timestamp(last_pulled)

        self.entries.append(entry)

        logger.info(f"Added entry: {entry.get_url()}")
        self.tell(f"Added entry: {entry.get_url()}")
        return entry

    def find_entry(self, kind: EntryKind, key: str) -> Optional[TableRepoEntry]:
        """The row for a repository URL or account owner, or None."""
        key = key.strip()
        return next((e for e in self.entries if e.kind == kind and e.key == key), None)

    def _on_pull_toggled(self, entry: TableRepoEntry, checked: bool):
        self.config.entry(entry.kind, entry.key).do_pull = checked

    def set_pull(self, scope: PullScope, checked: bool):
        """Tick or untick the selected rows, or all rows, with a single settings write."""
        if scope == PullScope.SELECTED:
            rows = [self.entries[index.row()] for index in self.entry_table.selectionModel().selectedRows()]
        else:
            rows = self.entries

        with self.config.batch():
            for entry in rows:
                entry.set_pull(checked)

        what = "selection" if scope == PullScope.SELECTED else "all"
        self.tell(f"{'Selected' if checked else 'Deselected'} {what}.")

    def _update_account_summary(self, entry: TableRepoEntry):
        """Branches column of an account row: how many repositories are backed up, and how many are skipped."""
        backed_up = len(existing_backups(self.repos_backup_path, entry.key))
        skipped = len(self.config.account(entry.key).skipped)
        text = f"{backed_up} repos" if backed_up or skipped else "-"
        if skipped:
            text += f", {skipped} skipped"
        entry.set_branches_text(text)

    # ---------- Editing rows ----------

    def handle_cell_doubleclick(self, row, col):
        entry = self.entries[row]

        if entry.is_account:
            if col in (Column.URL, Column.BRANCHES):
                self.choose_account_repos(entry)
        elif col == Column.URL:
            self.edit_repo_url(entry)

    def choose_account_repos(self, entry: TableRepoEntry):
        """Open the repository picker for an account row and save the choices on OK."""
        account = self.config.account(entry.key)
        dialog = RepoPickerDialog(self, entry.key, self.repos_backup_path, account.skipped, account.include_forks)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            logger.info(f"Kept repository choices for {entry.key}")
            return

        with self.config.batch():
            account.skipped = dialog.skipped()
            account.include_forks = dialog.include_forks()

        self._update_account_summary(entry)
        self.tell(f"{entry.key}: {len(account.skipped)} repositories skipped")

    def edit_repo_url(self, entry: TableRepoEntry):
        entry_url = entry.get_url()

        input_dialog = QInputDialog(self)
        input_dialog.setWindowTitle("Edit URL")
        input_dialog.setLabelText("New URL:")
        input_dialog.setTextValue(entry_url)
        input_dialog.resize(400, 200)

        if input_dialog.exec() != QDialog.Accepted:
            return

        new_url = input_dialog.textValue().strip()
        if new_url == entry_url:
            return

        target = parse_github_url(new_url)
        if target is None or target.kind != EntryKind.REPO:
            self.tell(f"Unable to validate {new_url}. Add accounts as a new entry.")
            return

        if self.find_entry(EntryKind.REPO, new_url):
            self.tell(f"{new_url} already exists.")
            return

        entry.set_url(new_url)
        entry.repo = Repository(new_url)
        entry.set_branch_count(entry.repo.branch_count(self.repos_backup_path))

        # Move the saved entry to the new URL, otherwise the old one comes back on next launch
        self.config.rename_repo(entry_url, new_url)

        logger.info(f"Edited {entry_url} to {new_url}")
        self.tell(f"Edited {entry_url} to {new_url}")

    # ---------- Removing rows ----------

    def remove_selected_entries(self):
        selected = self.entry_table.selectionModel().selectedRows()

        if not selected:
            logger.info("Nothing selected to remove.")
            return

        display_cap = 20
        rows = [self.entries[index.row()] for index in selected]
        names = [f"{entry.key} (account: all its backups)" if entry.is_account else entry.repo.name for entry in rows]
        if len(names) > display_cap:
            names = names[:display_cap] + ["(...)"]

        names_to_remove_joined = "\n".join(names)
        query = f"Also remove from Disk?\n\nChoosing Yes will remove the backup(s) from known locations.\nThis operation is irreversible.\n\n{names_to_remove_joined}"
        qm = QMessageBox
        query_ans = qm.question(self, "Remove from Disk?", query, qm.Yes | qm.No | qm.Cancel)

        if query_ans not in (qm.Yes, qm.No):
            logger.debug("[remove_selected_entries] MessageBox: Cancel")
            return

        if query_ans == qm.Yes:
            self._remove_backups_from_disk(rows)

        # Remove from UI and settings, with one settings write
        with self.config.batch():
            for index in sorted(selected, key=lambda i: i.row(), reverse=True):
                entry = self.entries[index.row()]
                self.config.remove(entry.kind, entry.key)
                self.entries.remove(entry)
                self.entry_table.removeRow(index.row())

    def _remove_backups_from_disk(self, rows: list[TableRepoEntry]):
        """
        Delete the backups of the given rows from every place they were backed up to.

        A backup still used by a row that is staying is kept: a repository that is also part of a
        remaining account, or an account repository that is also added on its own.
        """
        removing = set(map(id, rows))
        staying = [e for e in self.entries if id(e) not in removing]
        staying_accounts = {e.key for e in staying if e.is_account}
        staying_repo_names = {(e.repo.owner, e.repo.name) for e in staying if not e.is_account}

        def locations(entry: TableRepoEntry) -> list[Path]:
            saved = self.config.find(entry.kind, entry.key)
            known = saved.locations if saved else []
            return [Path(loc) for loc in dict.fromkeys([*known, str(self.repos_backup_path)])]

        def tidy_owner_dir(owner_dir: Path):
            if owner_dir.is_dir() and not any(owner_dir.iterdir()):
                owner_dir.rmdir()

        for entry in rows:
            for loc_path in locations(entry):
                if entry.is_account:
                    for name in existing_backups(loc_path, entry.key):
                        if (entry.key, name) in staying_repo_names:
                            logger.info(f"Keeping {entry.key}/{name}: it is also added on its own")
                            continue
                        remove_dir(Repository.of(entry.key, name).backup_path(loc_path))
                    tidy_owner_dir(owner_backup_dir(loc_path, entry.key))
                    continue

                repo = entry.repo
                if repo.owner in staying_accounts:
                    logger.info(f"Keeping {repo.owner}/{repo.name}: it is still backed up as part of the account")
                    continue

                # Current backup, then folders left behind by the old working-copy layout
                for target in (repo.backup_path(loc_path), loc_path / repo.name, loc_path / f"backup-{repo.name}"):
                    if target.exists():
                        logger.info(f"Removing {target}")
                        remove_dir(target)
                tidy_owner_dir(repo.backup_path(loc_path).parent)

    # ---------- Backup folder ----------

    def pick_backup_path(self):
        choice = QFileDialog.getExistingDirectory(self, "Select root folder", dir=str(self.repos_backup_path))

        if choice:
            self.backup_path_input.setText(choice)
            self.set_backup_path(choice)
        else:
            logger.info("User aborted backup path selection.")

    def set_backup_path(self, path: str | Path = None):
        # Use the given path, or what is written in the text field
        choice = Path(path if path is not None else self.backup_path_input.text()).resolve()

        self.backup_path_input.setText(str(choice))
        self.config.settings.backup_root = str(choice)
        logger.info(f"Backup path: {choice}")

    def tell(self, what: str):
        self.info_label.setText(what.strip())

    # ---------- Pulling ----------

    def pull_repos(self):
        rows = [entry for entry in self.entries if entry.get_pull()]
        if not rows:
            self.tell("Nothing is checked.")
            return

        self.set_buttons_state_while_task(False)
        self._run = BackupRun(self.repos_backup_path)
        self._run_pending = 0
        self._run_rows = {}

        for entry in rows:
            entry.set_status(EntryStatus.FETCHING)

        # Single repositories first, so a repo that is also in an account is reported on its own row
        for entry in rows:
            if not entry.is_account:
                self._queue_backup(entry.repo, entry)

        # Accounts: list their repositories in the background, then queue them (see on_account_planned)
        for entry in rows:
            if entry.is_account:
                account = self.config.account(entry.key)
                task = FunctionTask(
                    plan_account, entry.key, self._run.root, list(account.skipped), account.include_forks, context=entry
                )
                task.signals.succeeded.connect(self._on_account_task_done)
                task.signals.failed.connect(self._on_account_task_failed)
                self._run_pending += 1
                self.thread_pool.start(task)

        prefix = "[DRY_RUN] " if DRY_RUN else ""
        self.tell(f"{prefix}Backing up {len(rows)} entries")

    def _queue_backup(self, repo: Repository, entry: TableRepoEntry) -> bool:
        """Queue one repository backup for a row. Returns False if it is already queued this run."""
        if not self._run.claim(repo):
            return False

        self._run_rows[repo.url] = entry
        self._run_pending += 1

        task = BackupTask(repo, self._run.root)
        task.signals.succeeded.connect(self._on_backup_task_done)
        task.signals.failed.connect(self._on_backup_task_failed)
        task.signals.progress.connect(self._on_backup_task_progress)
        self.thread_pool.start(task)
        return True

    # Task results. Methods (not lambdas) so Qt delivers them on the main thread

    def _on_account_task_done(self, task: FunctionTask, plan: AccountPlan):
        self.on_account_planned(task.context, plan)

    def _on_account_task_failed(self, task: FunctionTask, error: Exception):
        # plan_account handles GitHub failures itself; this is a last resort so the run still finishes
        entry = task.context
        self.on_account_planned(entry, AccountPlan(entry.key, listing_error=f"Unexpected error: {error}"))

    def _on_backup_task_done(self, task: BackupTask, _repo):
        logger.info(f"Backup completed for: {task.repo.url}")
        self._on_backup_result(task.repo.url, ok=True)

    def _on_backup_task_failed(self, task: BackupTask, error: Exception):
        self.tell(f"Error backing up {task.repo.url}: {error}")
        self._on_backup_result(task.repo.url, ok=False, error_msg=str(error))

    def _on_backup_task_progress(self, task: BackupTask, status: str):
        entry = self._run_rows.get(task.repo.url)
        if entry is not None and not entry.is_account:  # Account rows show their own progress
            entry.set_status(status)

    def on_account_planned(self, entry: TableRepoEntry, plan: AccountPlan):
        self._run_pending -= 1

        queued = sum(self._queue_backup(repo, entry) for repo in plan.repos)
        progress = self._run.start_account(entry.key, plan, queued)

        if plan.listing_error:
            self.tell(f"{entry.key}: {plan.listing_error} Updating existing backups instead.")

        self._show_account_progress(entry, progress)
        self._finish_run_if_done()

    def _on_backup_result(self, repo_url: str, ok: bool, error_msg: str = ""):
        """One repository finished: update its row (or its account's row) and the run."""
        self._run_pending -= 1
        entry = self._run_rows.pop(repo_url, None)
        progress = self._run.result(ok, entry.key if entry is not None and entry.is_account else None)

        if progress is not None:
            self._show_account_progress(entry, progress)
        elif entry is not None and ok:
            entry.set_timestamp_now()
            entry.set_status(EntryStatus.DONE)
            entry.set_branch_count(entry.repo.branch_count(self._run.root))
            self.config.repo(entry.key).record_backup(self._run.root, when=entry.get_timestamp())
        elif entry is not None:
            entry.set_status(f"Error: {error_msg}")

        self._finish_run_if_done()

    def _show_account_progress(self, entry: TableRepoEntry, progress: AccountProgress):
        """Status of an account row while its repositories are backed up, and its result once complete."""
        if not progress.complete:
            entry.set_status(f"Backing up {progress.finished}/{progress.total}")
            return

        plan = progress.plan
        if progress.failed:
            status = f"{progress.failed} of {progress.total} failed"
        else:
            status = f"{EntryStatus.DONE} ({progress.total})"
        if plan.listing_error:
            status += ", GitHub unreachable"
        if plan.gone:
            status += f", {len(plan.gone)} gone upstream"
        entry.set_status(status)
        entry.status_label.setToolTip(plan.listing_error)

        if not progress.failed:
            entry.set_timestamp_now()
        progress.record(self.config.account(entry.key), self._run.root, entry.get_timestamp())
        self._update_account_summary(entry)

    def _finish_run_if_done(self):
        if self._run_pending > 0:
            return

        if self._run.should_record_last_run():
            self.config.settings.last_run = timestamp(TimestampFormat.LAST_RUN)

        self.tell("Backup completed")
        self.set_buttons_state_while_task(True)
        # Save now so pull results survive a crash before the window closes
        self.save_state()

    def set_buttons_state_while_task(self, state: bool):
        logger.info(f"Set buttons state {state}")
        for button in self._task_buttons:
            button.setEnabled(state)

    def stop_tasks(self):
        """Drop backups that haven't started yet. Running ones finish on their own."""
        logger.info("Stopping background tasks")
        self.thread_pool.clear()

    # ---------- Background service ----------

    def show_service_options_dialog(self):
        service_dialog = ServiceConfigWindow(self)

        if service_dialog.exec() != QDialog.DialogCode.Accepted:
            logger.info("Cancelled service settings")
            return

        sch_type, month, month_day, week_day, time = service_dialog.get_selected_values()
        logger.info(f"Set new schedule: {sch_type} {month} {month_day} {week_day}, {time}")
        with self.config.batch() as s:
            s.schedule_type = sch_type
            s.schedule_month = month
            s.schedule_month_day = month_day
            s.schedule_week_day = week_day
            s.schedule_time = time

    def register_background_service(self):
        s = self.config.settings

        if s.schedule_week_day or s.schedule_time:
            logger.info(f"Register service with schedule: {s.schedule_type} {s.schedule_week_day} - {s.schedule_time}")
            success, status = systemd.register_service(
                schedule_type=s.schedule_type,
                week_day=s.schedule_week_day,
                month=s.schedule_month,
                month_day=s.schedule_month_day,
                time=s.schedule_time,
            )
        else:
            logger.info("Register service with default schedule")
            success, status = systemd.register_service()

        self._offer_command(success, status)

    def unregister_background_service(self):
        self._offer_command(*systemd.unregister_service())

    def _offer_command(self, success: bool, command: str):
        """Copy a terminal command for the user to run, and tell them."""
        if not success:
            return
        self.app.clipboard().setText(command)
        AlertDialog(
            "Command copied to the clipboard. Please run it in your preferred Terminal application.",
            title="Set Background Service",
        )

    # ---------- Window ----------

    def show(self):
        super().show()
        self._adjust_app_size()
        sys.exit(self.app.exec())

    def closeEvent(self, event):
        logger.info("Application close.")
        self.stop_tasks()
        self.save_state()
        logger.info("Shutdown")
        event.accept()

    def save_state(self):
        """Store the window size and write any settings not yet on disk."""
        self.config.settings.window_width = self.frameGeometry().width()
        self.config.settings.window_height = self.frameGeometry().height() - 36

        self.config.save_settings()

    def _adjust_app_size(self):
        width, height, scale = get_screen_info(self.app)
        logger.debug(f"Screen: {width}x{height} @ {scale}")

        if width <= 2000 or height <= 1200 or scale <= 0.7:
            logger.info("Resizing application")
            self.resize(QSize(650, 500))

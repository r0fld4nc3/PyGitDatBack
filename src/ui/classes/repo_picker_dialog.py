import logging
from enum import IntEnum
from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from libgit import (
    GitHubError,
    RemoteRepo,
    Repository,
    existing_backups,
    list_account_repos,
)

from .tasks import FunctionTask

logger = logging.getLogger(__name__)


class PickerColumn(IntEnum):
    NAME = 0
    BACKUP = 1
    NOTES = 2


class RepoPickerDialog(QDialog):
    """
    Choose which of an account's repositories to back up. Everything is ticked by default.

    Read the result with `skipped()` and `include_forks()` after `exec()` returns Accepted.
    Nothing is saved by the dialog itself.
    """

    def __init__(
        self,
        parent,
        owner: str,
        root: Path,
        skipped: Iterable[str],
        include_forks: bool,
        lister: Callable[[str], list[RemoteRepo]] = list_account_repos,
    ):
        super().__init__(parent)
        self.owner = owner
        self.root = root
        self._initial_skipped = list(skipped)

        # Ticked state per repository name, kept for hidden rows (forks, filtered out) too
        self._checked: dict[str, bool] = {}
        self._items: dict[str, QTreeWidgetItem] = {}
        self._forks: set[str] = set()
        # Set once GitHub has listed the account, for the status text
        self._listed_count: int | None = None
        self._gone_count = 0

        self.setWindowTitle(f"Repositories of {owner}")
        self.setModal(True)
        self.resize(640, 480)

        self.status_label = QLabel(f"Loading repositories of {owner} from GitHub...")
        self.status_label.setWordWrap(True)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by name...")
        self.filter_input.textChanged.connect(self._apply_visibility)

        self.forks_checkbox = QCheckBox("Include forks")
        self.forks_checkbox.setChecked(include_forks)
        self.forks_checkbox.toggled.connect(self._apply_visibility)
        self.forks_checkbox.toggled.connect(self._update_status)

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(lambda: self._set_visible_checked(True))
        self.select_none_button = QPushButton("Select None")
        self.select_none_button.clicked.connect(lambda: self._set_visible_checked(False))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Repository", "Backup", "Notes"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(PickerColumn.NAME, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._on_item_changed)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        tools = QHBoxLayout()
        tools.addWidget(self.filter_input)
        tools.addWidget(self.forks_checkbox)
        tools.addWidget(self.select_all_button)
        tools.addWidget(self.select_none_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addLayout(tools)
        layout.addWidget(self.tree)
        layout.addWidget(self.buttons)

        self._set_controls_enabled(False)

        # List in the background so the dialog doesn't freeze
        task = FunctionTask(lister, owner)
        task.signals.succeeded.connect(self._on_listed)
        task.signals.failed.connect(self._on_failed)
        self._task = task  # Keep the signals object alive until it reports back
        QThreadPool.globalInstance().start(task)

    # ---------- Results ----------

    def skipped(self) -> list[str]:
        """Unticked repositories, plus earlier skips for repositories not listed now (kept, not forgotten)."""
        unticked = [name for name, checked in self._checked.items() if not checked]
        kept = [name for name in self._initial_skipped if name not in self._checked]
        return sorted(set(unticked + kept), key=str.lower)

    def include_forks(self) -> bool:
        return self.forks_checkbox.isChecked()

    # ---------- Loading ----------

    def _on_listed(self, _task, listed: list[RemoteRepo]):
        on_disk = set(existing_backups(self.root, self.owner))
        listed_names = {r.name for r in listed}

        for repo in listed:
            notes = [label for label, flag in (("fork", repo.fork), ("archived", repo.archived)) if flag]
            if repo.description:
                notes.append(repo.description)
            if repo.fork:
                self._forks.add(repo.name)
            self._add_row(repo.name, " · ".join(notes))

        # Backed up before but gone from GitHub: shown for information, always kept
        for name in sorted(on_disk - listed_names, key=str.lower):
            item = self._add_row(name, "No longer on GitHub. Backup kept.", checkable=False)
            item.setDisabled(True)

        self._listed_count = len(listed)
        self._gone_count = len(on_disk - listed_names)

        if self._forks:
            self.forks_checkbox.setText(f"Include forks ({len(self._forks)})")

        self._update_status()
        self._finish_loading()

    def _update_status(self, *_):
        """Explain what the list shows, so hidden forks don't look like missing repositories."""
        if self._listed_count is None:
            return  # Still loading, or GitHub couldn't be reached (see _on_failed)

        forks = len(self._forks)
        own = self._listed_count - forks

        if not forks:
            text = f"{own} repositories on GitHub."
        elif self.forks_checkbox.isChecked():
            text = f"{self._listed_count} repositories on GitHub, including {forks} forks."
        else:
            text = f"{own} repositories on GitHub. ({forks} hidden. Tick Include forks to also back them up)."

        text += " Untick any to skip. New repositories are included automatically."

        if self._gone_count:
            text += f"\n{self._gone_count} backed up repositories are no longer on GitHub but their backups are kept."
        self.status_label.setText(text)

    def _on_failed(self, _task, error: Exception):
        if not isinstance(error, GitHubError):
            logger.error(f"Listing repositories for {self.owner} failed: {error}")
            error = f"Listing failed: {error}"
        names = existing_backups(self.root, self.owner)
        for name in names:
            self._add_row(name, "From existing backup")

        self.status_label.setText(
            f"{error}\nShowing the {len(names)} repositories already backed up. Choices still apply to future runs."
        )
        self._finish_loading()

    def _add_row(self, name: str, notes: str, checkable: bool = True) -> QTreeWidgetItem:
        branches = Repository.of(self.owner, name).branch_count(self.root)

        item = QTreeWidgetItem([name, f"{branches} branches" if branches else "Not yet", notes])
        item.setToolTip(PickerColumn.NOTES, notes)

        if checkable:
            checked = name not in self._initial_skipped
            self._checked[name] = checked
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(PickerColumn.NAME, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._items[name] = item

        self.tree.addTopLevelItem(item)
        return item

    def _finish_loading(self):
        self.tree.resizeColumnToContents(PickerColumn.BACKUP)
        self._apply_visibility()
        self._set_controls_enabled(True)

    # ---------- Interaction ----------

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        name = item.text(PickerColumn.NAME)
        if column == PickerColumn.NAME and name in self._checked:
            self._checked[name] = item.checkState(PickerColumn.NAME) == Qt.CheckState.Checked

    def _apply_visibility(self, *_):
        text = self.filter_input.text().strip().lower()
        show_forks = self.forks_checkbox.isChecked()

        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            name = item.text(PickerColumn.NAME)
            hidden = (text and text not in name.lower()) or (name in self._forks and not show_forks)
            item.setHidden(bool(hidden))

    def _set_visible_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in self._items.values():
            if not item.isHidden():
                item.setCheckState(PickerColumn.NAME, state)

    def _set_controls_enabled(self, enabled: bool):
        for widget in (self.filter_input, self.forks_checkbox, self.select_all_button, self.select_none_button):
            widget.setEnabled(enabled)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enabled)

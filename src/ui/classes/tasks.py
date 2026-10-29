"""
Background work for the UI.

Every task runs `work()` on a worker thread and reports through `task.signals`, never by touching
widgets itself. Signals carry the task, so one slot can tell which repository or row a result is
for. Connect them to methods of Qt objects (windows, dialogs), not lambdas: Qt then delivers them
on the main thread.
"""

import logging
import secrets
from pathlib import Path
from time import sleep
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from defines import DRY_RUN
from libgit import Repository

from .table_entry_repos import EntryStatus

logger = logging.getLogger(__name__)


class TaskSignals(QObject):
    succeeded = Signal(object, object)  # task, result of work()
    failed = Signal(object, object)  # task, exception raised by work()
    progress = Signal(object, str)  # task, status text


class Task(QRunnable):
    """Base class: subclasses implement `work()`."""

    # Due to garbage collection, Tasks stay in here from creation until run() has reported back.
    _alive: set["Task"] = set()

    def __init__(self, context: Any = None):
        super().__init__()
        self.context = context  # Whatever the caller needs back with the result (ex.: a table row)
        self.signals = TaskSignals()
        Task._alive.add(self)

    def work(self) -> Any:
        raise NotImplementedError

    def run(self):
        try:
            result = self.work()
        except Exception as e:
            logger.error(f"{type(self).__name__} failed: {e}")
            self.signals.failed.emit(self, e)
        else:
            self.signals.succeeded.emit(self, result)
        finally:
            Task._alive.discard(self)


class FunctionTask(Task):
    """Runs `fn(*args)` on a worker thread."""

    def __init__(self, fn: Callable, *args, context: Any = None):
        super().__init__(context)
        self.fn = fn
        self.args = args

    def work(self) -> Any:
        return self.fn(*self.args)


class BackupTask(Task):
    """Backs up one repository. With DRY_RUN, waits a random time instead."""

    def __init__(self, repo: Repository, root: Path, context: Any = None):
        super().__init__(context)
        self.repo = repo
        self.root = root

    def work(self) -> Repository:
        if DRY_RUN:
            seconds = secrets.choice(range(1, 11))
            logger.info(f"Dry run repository {self.repo.url} into {self.root} ({seconds}s)")
            self.signals.progress.emit(self, f"{EntryStatus.FETCHING} ({seconds})")
            sleep(seconds)
            return self.repo

        logger.info(f"Backing up repository {self.repo.url} into {self.root}")
        if not self.repo.backup(self.root):
            raise RuntimeError("Backup failed after all retries")
        return self.repo

import logging
import secrets
from time import sleep

from PySide6.QtCore import QRunnable

from defines import DRY_RUN
from libgit import Repository

from .table_entry_repos import TableRepoEntry
from .worker_signals import WorkerSignals

logger = logging.getLogger(__name__)


class CloneRepoTask(QRunnable):
    """
    Backs up one repository on a worker thread.

    Never touch Qt widgets from `run()`.
    Report through `self.signals` for UI updates on main thread.
    """

    def __init__(self, repo, path, entry):
        super().__init__()
        self.repo: Repository = repo
        self.path = path
        self.entry: TableRepoEntry = entry
        self.signals = WorkerSignals()

    def run(self):
        try:
            if not DRY_RUN:
                logger.info(f"Backing up repository {self.repo.url} into {self.path}")
                if not self.repo.backup(self.path):
                    raise RuntimeError("Backup failed after all retries")
            else:
                logger.info(f"Dry run repository {self.repo.url} into {self.path}")

                _sleep = secrets.choice(range(1, 11))
                logger.debug(f"[{self.repo.url}] Sleeping for {_sleep}")
                self.signals.status.emit(self.repo.url, f"{self.entry.status_fetching} ({_sleep})")

                sleep(_sleep)
            self.signals.finished.emit(self.repo.url)
        except Exception as e:
            logger.error(f"Error backing up repository {self.repo.url}: {e}")
            self.signals.error.emit(self.repo.url, str(e))

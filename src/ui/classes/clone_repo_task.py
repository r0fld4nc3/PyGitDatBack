from PySide6.QtCore import QRunnable
from time import sleep
import secrets

from .table_entry_repos import TableRepoEntry
from .worker_signals import WorkerSignals
from conf_globals import G_LOG_LEVEL, DRY_RUN
from log import create_logger

logger = create_logger(__name__, G_LOG_LEVEL)

class CloneRepoTask(QRunnable):
    def __init__(self, repo, path, entry):
        super().__init__()
        self.repo = repo
        self.path = path
        self.entry: TableRepoEntry = entry
        self.signals = WorkerSignals()

    def run(self):
        try:
            if not DRY_RUN:
                logger.info(f"Cloning repository {self.repo.url} into {self.path}")
                self.repo.clone_from(self.path)
                self.entry.set_branches(self.repo.active_branches_str)
            else:
                logger.info(f"Dry run repository {self.repo.url} into {self.path}")
                
                _sleep = secrets.choice(range(1, 11))
                logger.debug(f"[{self.repo.url}] Sleeping for {_sleep}")
                self.entry.set_status(f"{self.entry.status_fetching} ({_sleep})")

                if _sleep == 7:
                    raise Exception("Test exception, hit 7")
                sleep(_sleep)
            self.signals.finished.emit(self.repo.url)
        except Exception as e:
            logger.error(f"Error cloning repository {self.repo.url}: {e}")
            self.signals.error.emit(self.repo.url, str(e))

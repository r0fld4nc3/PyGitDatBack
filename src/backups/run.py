"""
Location for one backup run, shared by the window and the headless (scheduled) run.

- Each backup folder is backed up at most once per run, even when a repository is added on its own and is also part of an account.

- Account progress is counted per account, so its result can be recorded once all of its repositories are done.

- The run is recorded as `last_run` unless 40% or more of the backups failed.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import settings
from libgit import AccountPlan, Repository, plan_account
from settings import AccountSettings
from utils import TimestampFormat, timestamp

logger = logging.getLogger(__name__)

# The run counts as successful unless this share of backups (or more) failed
FAILURE_THRESHOLD = 0.4


@dataclass
class AccountProgress:
    """How far an account's repositories are through this run."""

    plan: AccountPlan
    total: int
    done: int = 0
    failed: int = 0

    @property
    def finished(self) -> int:
        return self.done + self.failed

    @property
    def complete(self) -> bool:
        return self.finished >= self.total

    def step(self, ok: bool) -> None:
        if ok:
            self.done += 1
        else:
            self.failed += 1

    def record(self, account: AccountSettings, root: Path, when: str) -> None:
        """Save the result: the location if anything was backed up, the time only if nothing failed."""
        account.record_backup(root if self.done else None, when="" if self.failed else when)


class BackupRun:
    """One run over the selected repositories and accounts."""

    def __init__(self, root: Path):
        self.root = root
        self.total = 0
        self.failures = 0
        self.accounts: dict[str, AccountProgress] = {}
        self._seen: set[Path] = set()

    def claim(self, repo: Repository) -> bool:
        """Reserve a repository for this run. False when its backup folder is already taken."""
        path = repo.backup_path(self.root)
        if path in self._seen:
            return False
        self._seen.add(path)
        self.total += 1
        return True

    def start_account(self, owner: str, plan: AccountPlan, queued: int) -> AccountProgress:
        self.accounts[owner] = AccountProgress(plan, queued)
        return self.accounts[owner]

    def result(self, ok: bool, owner: Optional[str] = None) -> Optional[AccountProgress]:
        """Count one finished backup. Returns the account's progress when it belongs to one."""
        if not ok:
            self.failures += 1
        progress = self.accounts.get(owner) if owner is not None else None
        if progress is not None:
            progress.step(ok)
        return progress

    def should_record_last_run(self) -> bool:
        return not self.failures or self.failures < self.total * FAILURE_THRESHOLD


def run_headless() -> None:
    """Back up everything that is ticked, without a window. Used by the scheduled service (`--no-ui`)."""
    config = settings.get()
    root = config.settings.backup_root_path()
    logger.info(f"Backing up to root directory: {root}")

    run = BackupRun(root)
    units: list[tuple[Repository, Optional[str]]] = []  # (repository, owning account or None)

    # Single repositories first, so a repo that is also in an account is recorded on its own entry
    for url, repo_settings in config.settings.repos.items():
        if not repo_settings.do_pull:
            continue
        try:
            repo = Repository(url)
        except ValueError as e:
            logger.warning(f"Skipping saved repository: {e}")
            continue
        if run.claim(repo):
            units.append((repo, None))

    for owner, account in config.settings.accounts.items():
        if not account.do_pull:
            continue
        plan = plan_account(owner, root, account.skipped, account.include_forks)
        queued = [repo for repo in plan.repos if run.claim(repo)]
        run.start_account(owner, plan, len(queued))
        units += [(repo, owner) for repo in queued]

    logger.info(f"Collected {len(units)} repositories to back up ({len(run.accounts)} accounts)")

    with ThreadPoolExecutor(max_workers=config.settings.max_concurrent_tasks) as executor:
        futures = {executor.submit(repo.backup, root): (repo, owner) for repo, owner in units}

        for future in as_completed(futures):
            repo, owner = futures[future]
            try:
                ok = future.result()
                if not ok:
                    logger.error(f"Error pulling repository: {repo.url}: Backup failed after all retries")
            except Exception as e:
                logger.error(f"Error pulling repository: {repo.url}: {e}")
                ok = False

            run.result(ok, owner)
            if ok and owner is None:
                config.repo(repo.url).record_backup(root, when=timestamp(TimestampFormat.PULLED))
            if ok:
                logger.info(f"Finished processing {repo.url}")

    # Record each account once all its repositories are done
    now = timestamp(TimestampFormat.PULLED)
    for owner, progress in run.accounts.items():
        progress.record(config.account(owner), root, now)
        gone = len(progress.plan.gone)
        logger.info(
            f"Account {owner}: {progress.done} backed up, {progress.failed} failed , {gone} no longer on GitHub (kept)"
            if gone
            else ""
        )

    if run.should_record_last_run():
        config.settings.last_run = timestamp(TimestampFormat.LAST_RUN)

    config.save_if_dirty()
    logger.info("Pull Repos No UI finished")

"""
Account backups: which of an account's repositories to back up on a run.
Combines the GitHub listing (github.py) with what is already on disk (git.py).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Union

from . import github
from .git import Repository, existing_backups
from .github import RemoteRepo

logger = logging.getLogger(__name__)


@dataclass
class AccountPlan:
    """Which of an account's repositories to back up on this run."""

    owner: str
    repos: list[Repository] = field(default_factory=list)
    # Backed up before, but no longer listed on GitHub (deleted, renamed or made private). Kept, not fetched.
    gone: list[str] = field(default_factory=list)
    # Empty when the listing worked. Otherwise explanation of error.
    listing_error: str = ""


def selected_repos(listed: Iterable[RemoteRepo], skipped: Iterable[str], include_forks: bool) -> list[RemoteRepo]:
    """The listed repositories to back up: not skipped, and forks only when wanted."""
    skipped = set(skipped)
    return [r for r in listed if r.name not in skipped and (include_forks or not r.fork)]


def plan_account(owner: str, root: Union[Path, str], skipped: Iterable[str], include_forks: bool) -> AccountPlan:
    """
    Work out which of an account's repositories to back up.

    New repositories are included automatically.
    Only the ones in `skipped` are left out.

    If GitHub can't be reached, the account's existing backups are updated instead, so a listing failure never stops them from being kept up to date.
    """
    skipped = list(skipped)
    plan = AccountPlan(owner)
    on_disk = existing_backups(root, owner)

    def repo(name: str) -> Repository:
        return Repository.of(owner, name)

    try:
        listed = github.list_account_repos(owner)  # For tests purpose, looked-up at module level
    except github.GitHubError as e:
        plan.listing_error = str(e)
        plan.repos = [repo(name) for name in on_disk if name not in skipped]
        logger.warning(f"[{owner}] {e} Updating {len(plan.repos)} existing backups instead.")
        return plan

    plan.repos = [repo(r.name) for r in selected_repos(listed, skipped, include_forks)]

    listed_names = {r.name for r in listed}
    plan.gone = [name for name in on_disk if name not in listed_names]
    if plan.gone:
        logger.info(f"[{owner}] No longer on GitHub, backups kept: {', '.join(plan.gone)}")

    return plan

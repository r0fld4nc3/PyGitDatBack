import logging
import os
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Union
from urllib.parse import urlparse

import git

logger = logging.getLogger(__name__)

ACCEPTED_DOMAINS = ("github.com",)

# Upstream branches and tags are fetched into a staging area first, never straight over
# the backup's own refs. Only branches and tags: a plain `--mirror` would also pull
# GitHub's refs/pull/* (every pull request ever opened), which can be very large.
STAGING_PREFIX = "refs/staging/"
STAGING_REFSPECS = ("+refs/heads/*:refs/staging/heads/*", "+refs/tags/*:refs/staging/tags/*")

# When upstream rewrites a branch or moves a tag (force-push, history rewrite), the
# backup's previous version is kept here, so those commits are never lost:
#   refs/preserved/<UTC timestamp>/heads/<branch>
#   refs/preserved/<UTC timestamp>/tags/<tag>
PRESERVED_PREFIX = "refs/preserved/"

# Never let git stop and wait for a username/password. A private or missing repo
# would otherwise hang the background service forever.
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}


class Repository:
    """
    A GitHub repository and its local backup.

    The backup is a bare clone holding every branch and tag, stored at
    `<root>/<owner>/<name>.git`. Each run fetches new commits into it.

    Nothing already backed up is ever dropped:
    * Branches and tags deleted upstream are kept.
    * If upstream rewrites a branch or moves a tag, the old version is kept under `refs/preserved/`.
    """

    def __init__(self, url: str):
        self.url: str = url.strip()
        self.owner, self.name = parse_owner_name_from_url(self.url)

        self.max_retries = 3
        self.retry_delay = 30  # seconds

    def backup_path(self, root: Union[Path, str]) -> Path:
        return Path(root).expanduser().resolve() / self.owner / f"{self.name}.git"

    def has_backup(self, root: Union[Path, str]) -> bool:
        return (self.backup_path(root) / "HEAD").is_file()

    def branch_count(self, root: Union[Path, str]) -> int:
        """Number of branches in the local backup, or 0 when there is none yet."""
        if not self.has_backup(root):
            return 0

        try:
            return len(git.Repo(self.backup_path(root)).heads)
        except Exception as e:
            logger.warning(f"[{self.name}] Unable to read branches from backup: {e}")
            return 0

    def backup(self, root: Union[Path, str]) -> bool:
        """
        Create the backup on first run, otherwise fetch new commits into it.
        Retries on failure. Returns `True` when the backup is up to date.
        """
        dest = self.backup_path(root)

        for attempt in range(1, self.max_retries + 1):
            try:
                if dest.exists():
                    logger.info(f"[{self.name}] Attempt {attempt}/{self.max_retries}: Updating backup {dest}")
                    self._fetch(dest)
                else:
                    logger.info(f"[{self.name}] Attempt {attempt}/{self.max_retries}: Creating backup {dest}")
                    self._clone(dest)

                logger.info(f"[{self.name}] Backup up to date: {dest}")
                return True
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"[{self.name}] Attempt {attempt} failed: {e}")
                    logger.info(f"[{self.name}] Waiting {self.retry_delay} seconds before retry...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"[{self.name}] All {self.max_retries} attempts failed: {e}")

        return False

    def _clone(self, dest: Path):
        # Clone next to the final folder and rename once complete, so an interrupted
        # clone never leaves a half-made backup that later runs would try to update
        partial = dest.with_name(dest.name + ".partial")
        if partial.exists():
            remove_dir(partial)

        partial.parent.mkdir(parents=True, exist_ok=True)

        try:
            repo = git.Repo.clone_from(self.url, partial, bare=True, env=GIT_ENV)
            _use_staging_refspecs(repo)
            repo.close()
        except Exception:
            remove_dir(partial)
            raise

        partial.rename(dest)

    def _fetch(self, dest: Path):
        repo = git.Repo(dest)
        try:
            # Also upgrades backups made before staging existed
            _use_staging_refspecs(repo)

            # --refmap= stops git also applying the configured refspecs, so only staging is written.
            # --prune only removes staging refs; the backup's own branches and tags are never deleted.
            repo.git.fetch("origin", "--no-tags", "--prune", "--refmap=", *STAGING_REFSPECS, env=GIT_ENV)

            preserved = self._apply_staged_refs(repo)
            if preserved:
                logger.warning(f"[{self.name}] Upstream rewrote history. Kept {preserved} old version(s) under {PRESERVED_PREFIX}")
        finally:
            repo.close()

    def _apply_staged_refs(self, repo: git.Repo) -> int:
        """
        Move the backup's branches and tags to match upstream. A plain fast-forward just moves.
        Anything else (force-push, moved tag) first saves the old version under `refs/preserved/`.
        Returns how many old versions were preserved.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        current = _list_refs(repo, "refs/heads/") | _list_refs(repo, "refs/tags/")
        preserved = 0

        for staged_ref, new_sha in _list_refs(repo, STAGING_PREFIX).items():
            target = "refs/" + staged_ref.removeprefix(STAGING_PREFIX)
            old_sha = current.get(target)

            if old_sha == new_sha:
                continue

            # Tags are meant to be fixed, so any move is kept. Branches only when history was rewritten.
            is_tag = target.startswith("refs/tags/")
            if old_sha and (is_tag or not _is_ancestor(repo, old_sha, new_sha)):
                keep_ref = f"{PRESERVED_PREFIX}{stamp}/{target.removeprefix('refs/')}"
                repo.git.update_ref(keep_ref, old_sha)
                logger.warning(f"[{self.name}] {target} was rewritten upstream. Old version kept as {keep_ref}")
                preserved += 1

            repo.git.update_ref(target, new_sha)

        return preserved


def _use_staging_refspecs(repo: git.Repo):
    """Point the backup's fetch config at staging, so even a manual `git fetch` cannot overwrite history."""
    repo.git.config("--replace-all", "remote.origin.fetch", STAGING_REFSPECS[0])
    repo.git.config("--add", "remote.origin.fetch", STAGING_REFSPECS[1])


def _list_refs(repo: git.Repo, prefix: str) -> dict[str, str]:
    """`{ref name: object id}` for every ref under `prefix`."""
    out = repo.git.for_each_ref("--format=%(refname) %(objectname)", prefix)
    return dict(line.split(" ", 1) for line in out.splitlines() if line)


def _is_ancestor(repo: git.Repo, old: str, new: str) -> bool:
    """True when `new` simply builds on `old`, so moving to it loses nothing."""
    try:
        repo.git.merge_base("--is-ancestor", old, new)
        return True
    except git.GitCommandError:
        # Not an ancestor, or not comparable (e.g. a tag on a non-commit): treat as a rewrite and keep it
        return False


def remove_dir(path: Path) -> bool:
    """Delete a folder tree, including read-only git object files. Returns `True` when it is gone."""
    if not path.exists():
        return True

    try:
        shutil.rmtree(path, onexc=_rmtree_on_error)
    except Exception as e:
        logger.error(f"Unable to remove {path}: {e}")
        return False

    return True


def _rmtree_on_error(func, path, exc):
    # https://stackoverflow.com/a/2656405
    # Git marks object files read-only, which blocks deletion on Windows. Make writable and retry.
    if not os.access(path, os.W_OK):
        logger.info(f"Re-attempting delete path {path}")
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        logger.error(f"Raising undeletable error for path {path}")
        raise exc


def parse_owner_name_from_url(url: str) -> Tuple[str, str]:
    owner: str = ""
    name: str = ""

    parsed = urlparse(url.strip())
    _path_split = [i for i in parsed.path.split("/") if i]  # Also remove empty values

    if len(_path_split) > 1:
        owner = _path_split[0]
        name = _path_split[1].removesuffix(".git")

    logger.debug(f"Parsed {url}: {owner=} {name=}")

    return owner, name


def validate_github_url(url: str) -> bool:
    """
    Checks the URL is a GitHub repository URL (`https://github.com/<owner>/<name>`).
    It does not check the repository exists. A missing repo fails when it is backed up.
    """
    parsed = urlparse(url.strip())
    owner, name = parse_owner_name_from_url(url)

    if parsed.netloc.lower() not in ACCEPTED_DOMAINS:
        logger.info(f"{parsed.netloc} is not a valid {ACCEPTED_DOMAINS} domain.")
        return False

    if not owner or not name:
        logger.info(f"Owner and Name must be valid: {owner=} | {name=}")
        return False

    return True

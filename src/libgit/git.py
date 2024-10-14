import os
import git
import stat
import shutil
from pathlib import Path
from typing import Tuple, Union
from urllib.parse import urlparse
from datetime import datetime, timedelta

from log import create_logger
from conf_globals import G_LOG_LEVEL, COMMIT_CUTOFF_DAYS

logger = create_logger(__name__, G_LOG_LEVEL)

def _parse_repo_url(url: str) -> Tuple[str, str]:
    owner: str = ""
    name: str = ""
    
    parsed = urlparse(url)
    _path = parsed.path
    _path_split = [i for i in _path.split('/') if i] # Also remove empty values

    if len(_path_split) > 1:
        owner = _path_split[0]
        name = _path_split[1]
    else:
        owner = _path_split[0]

    return owner, name

class Repository(git.Repo):
    def __init__(self, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url: str  = url
        self.name: str  = ""
        self.owner: str = ""
        self.cloned_to: Path = ""
        self.repo: git.Repo = None
        self.repo_branches: list[git.RemoteReference] = list()
        
        self.owner, self.name = _parse_repo_url(url)

    # TODO: Filter branches by commit date so we can gatekeep some branches from being cloned, referring to them as "active branches"
    def clone_from(self, dest: Union[Path, str], branch: git.RemoteReference = None, *args, **kwargs):
        """`@Override`
        
        Override method to use to clone the designated GitHub URL to disk.

        Performs some necessary preparations for the `Repository` class before calling 
        `git.clone_from()` for the ``git`` library. It does not replace `git.clone_from()`,
        instead builds to it.

        * When no :param:`branch` is specified, the destination folder will be called `main`
        to indicate that it is the main branch that is being cloned.

        * If :param:`branch` is specified, it will attempt to clone a branch from the repository
        and name the corresponding destination folder accordingly.

        Attributes it uses/modifies:

        * :param:`cloned_to`
        """

        # =================================
        #          PREPARATION
        # =================================

        if not isinstance(dest, Path):
            dest = Path(dest).resolve()
        else:
            dest = dest.resolve()

        logger.debug(f"[{self.name}] [{branch}] Resolved destination: {dest}")
        
        if not dest.exists():
            logger.debug(f"[{self.name}] os.makedirs({dest}, exist_ok=True)")
            os.makedirs(dest, exist_ok=True)
        
        if f"{self.name.lower()}" not in dest.name.lower():
            logger.debug(f"[{self.name}] {self.name.lower()} not in {dest}, therefore append {self.name} to {dest}")
            dest = dest / self.name

        if not branch:
            logger.debug(f"[{self.name}] No branch set, {branch=}")
            dest_end = "main"
        else:
            logger.debug(f"[{self.name}] Branch set, {branch=}")
            dest_end = branch.name.split('/', 1)[-1]

        # The final destination for the specific branch inside the main dest folder
        branch_dest = dest / dest_end

        # =================================
        #             CLONING
        # =================================
            
        # Filter active commits
        if branch:
            active = self._filter_active(branch)
            if not active:
                logger.info(f"[{self.name}] Not cloning branch {branch.name} as it is considered inactive.")
                return self
            else:
                logger.info(f"[{self.name}] Cloning branch {branch.name} as it is considered active.")

        # If directory exists and is a cloned repo already, rename existing to avoid conflict
        if branch_dest.exists():
            logger.debug(f"[{self.name}] Destination exists: {branch_dest}")
            
            self.cloned_to = branch_dest
            backup_dir = self.set_backup_dir(branch_dest)
            self.__remove_dir(branch_dest) # Remove target directory avoid fatal clone error
            
            # Clone the repo/branch
            successful_clone, _ = self.__clone_from_basecls(self.url, branch_dest, args, kwargs)
            
            # Try to remove the backup directory after successful clone
            if successful_clone:
                logger.info(f"[{self.name}] Deleting {backup_dir.name} after successful clone.")
                self.__remove_dir(backup_dir)
            else:
                logger.warning(f"[{self.name}] Cloning was unsuccesful. Attempting to revert state.")
                # Remove the possible lingering destination directory
                if branch_dest.exists():
                    self.__remove_dir(branch_dest)
                
                # Set backup dir back
                backup_dir.rename(branch_dest)
        else:
            successful_clone, _ = self.__clone_from_basecls(self.url, branch_dest, args, kwargs)

            if successful_clone:
                self.cloned_to = branch_dest

        if not branch:
            # Don't collect branch names if we're cloning a specific branch already
            self.collect_branch_names()

        if branch:
            logger.info(f"[{self.name}] [{branch.name}] Clone finished.")
        else:
            logger.info(f"[{self.name}] Clone finished.")

        return self

    def collect_branch_names(self) -> "Repository":
        """From a cloned local repository, attempts to collect names of existing 
        branches and stores them in a list `self.repo_branches`. This list only 
        contains the names of branches that are not `origin/HEAD` and `origin/main`.

        This method is already called automatically in `self.clone_to` method but can
        be useful to call when the repository already exists on disk and it is needed
        to retrieve branch information when no cloning has happened in the same session
        or instance.

        Attributes it uses/modifies:

        * :param:`repo_branches`
        """
        logger.info(f"[{self.name}] Collecting branch names for {self.name}")

        self.repo_branches.clear()

        if self.cloned_to and self.cloned_to.exists():
            logger.info(f"[{self.name}] {self.repo=}")

            # self.repo_branches = [head.name.split('/', 1)[-1] for head in self.repo.remote().refs]
            self.repo_branches = [head for head in self.repo.remote().refs]
            logger.debug(f"[{self.name}] Repo branches ({len(self.repo_branches)}): {self.repo_branches}")

            # Remove origin/HEAD & main branch/master since we already have it
            _removes = ["HEAD", "main", "master"]
            for branch in self.repo_branches:
                if branch.name.split('/', 1)[-1] in _removes:
                    try:
                        self.repo_branches.remove(branch)
                    except ValueError:
                        logger.info(f"{branch.name} not in branches")
            
            logger.info(f"[{self.name}] {len(self.repo_branches)} branches for Repository {self.name}: {self.repo_branches}")
        
        return self
    
    def _filter_active(self, branch_ref: git.RemoteReference, active_cutoff_days: int = COMMIT_CUTOFF_DAYS) -> bool:
        """
        Check if a branch has been active (committed to) within the given number of days.

        :param branch_name: The name of the branch to check.
        :param active_cutoff_days: The number of days to consider a branch as active (default: 30).
        :return: True if the branch has commits within the cutoff period, False otherwise.
        """
        
        if active_cutoff_days <= 0:
            logger.debug(f"{active_cutoff_days=}")
            return True
        
        # Branch is None or empty
        if not branch_ref:
            return False
        
        branch = branch_ref.name
        
        self.repo.remote().fetch()
        
        try:
            logger.debug(f"[{self.name}] {branch=}")
            commit = branch_ref.commit
            commit_date = datetime.fromtimestamp(commit.committed_date).date()
            cutoff_date = (datetime.now() - timedelta(days=active_cutoff_days)).date()
            
            logger.info(f"[{self.name}] Commit date for branch {branch}: {commit_date}")
            logger.debug(f"[{self.name}] Cutoff date for branch {branch}: {cutoff_date}")
            
            days_ago = (datetime.now().date() - commit_date).days
            logger.info(f"[{self.name}] Last commit for branch {branch}: {days_ago} days ago")
            
            return commit_date >= cutoff_date
        except Exception as e:
            logger.error(f"[{self.name}] An error has occurred from params ({branch_ref=}, {active_cutoff_days=}): {e}")
            return False

    def set_backup_dir(self, dir_path: Path) -> Path:
        backup_dir: Path = dir_path.parent / f"backup-{dir_path.name}"

        if backup_dir.exists():
            logger.info(f"[{self.name}] Deleting backup-dir: {backup_dir}")
            self.__remove_dir(backup_dir)

        shutil.copytree(dir_path, backup_dir, dirs_exist_ok=True)
        
        return backup_dir


    def __remove_dir(self, to_remove: Path) -> bool:
        # Try to remove the directory
        logger.debug(f"[{self.name}] shutil.rmtree({to_remove}, onerror={_rmtree_on_error})")
        try:
            shutil.rmtree(to_remove, onerror=_rmtree_on_error)
        except Exception as e:
            logger.error(f"[{self.name}] {e}", exc_info=1)
            return False

        return True

    def __clone_from_basecls(self, url, dest, *args, **kwargs) -> Tuple[bool, Path]:
        successful_clone = False
        
        logger.debug(f"[{self.name}] Calling `git.Repo.clone_from({url}, {dest}, {args}, {kwargs})`")
        
        try:
            self.repo = git.Repo.clone_from(self.url, dest, *args, **kwargs)
            successful_clone = True
        except Exception as e:
            logger.error(f"[{self.name}] {e}", exc_info=1)

        return successful_clone, dest
    
def _rmtree_on_error(func, path, exc_info):
    # https://stackoverflow.com/a/2656405
    """
        Error handler for ``shutil.rmtree``.

        If the error is due to an access error (read only file)
        it attempts to add write permission and then retries.

        If the error is for another reason it re-raises the error.

        Usage : ``shutil.rmtree(path, onerror=onerror)``
        """
    # Is the error an access error?
    if not os.access(path, os.W_OK):
        logger.info(f"Re-attempting delete path {path}")
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        logger.error(f"Raising undeletable error for path {path}")
        raise

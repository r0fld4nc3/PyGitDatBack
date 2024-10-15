import os
import git
import stat
import shutil
import requests
import psutil
from pathlib import Path
from typing import Tuple, Union
from urllib.parse import urlparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from log import create_logger
from conf_globals import G_LOG_LEVEL, COMMIT_CUTOFF_DAYS, THREAD_TIMEOUT_SECONDS

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
        self.head_name = ""
        self.repo_branches: list[git.RemoteReference] = list()
        self.active_branches: list[git.RemoteReference] = list()
        
        self.owner, self.name = _parse_repo_url(url)
        self.head_name = self._get_head()

    def clone_from(self, dest: Union[Path, str], *args, **kwargs):
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
        
        if not dest.exists():
            logger.debug(f"[{self.name}] os.makedirs({dest}, exist_ok=True)")
            os.makedirs(dest, exist_ok=True)
        
        if f"{self.name.lower()}" not in dest.name.lower():
            logger.debug(f"[{self.name}] {self.name.lower()} not in {dest}, therefore append {self.name} to {dest}")
            dest = dest / self.name

        # The final destination for the specific branch inside the dest folder
        clone_dest = dest / self.head_name.replace('/', '-') # Needs to be sanitised
        if kwargs.get("branch"):
            sanitised_trail = kwargs.get("branch").split('/', 1)[-1].replace('/', '-') # Needs to be sanitised
            clone_dest = dest / sanitised_trail

        # =================================
        #             CLONING
        # =================================

        # If directory exists and is a cloned repo already, rename existing to avoid conflict
        if clone_dest.exists():
            logger.debug(f"[{self.name}] Destination exists: {clone_dest}")
            
            self.cloned_to = clone_dest
            backup_dir = self.set_backup_dir(clone_dest)
            self.__remove_dir(clone_dest) # Remove target directory avoid fatal clone error
            
            # Clone the repo/branch
            successful_clone, _ = self.__clone_from_basecls(self.url, clone_dest, args, kwargs)
            
            # Try to remove the backup directory after successful clone
            if successful_clone:
                logger.info(f"[{self.name}] Deleting {backup_dir.name} after successful clone.")
                self.__remove_dir(backup_dir)
            else:
                logger.warning(f"[{self.name}] Cloning was unsuccesful. Attempting to revert state.")
                # Remove the possible lingering destination directory
                if clone_dest.exists():
                    self.__remove_dir(clone_dest)
                
                # Set backup dir back
                backup_dir.rename(clone_dest)
        else:
            successful_clone, _ = self.__clone_from_basecls(self.url, clone_dest, args, kwargs)

            if successful_clone:
                self.cloned_to = clone_dest

        # Don't collect branch names if we're cloning a specific branch already
        if not kwargs.get("branch", None):
            self.collect_branches()

        return self
    
    def clone_branches(self, only_active=False) -> "Repository":
        if not self.repo_branches or not self.cloned_to or not self.repo:
            return
        
        branch_list = self.repo_branches
        if only_active:
            branch_list = self.active_branches
            logger.info(f"[{self.name}] {only_active=}")

        optimal_workers = _determine_max_workers(load_factor=0.75)
        with ThreadPoolExecutor(max_workers=optimal_workers) as executor:
            logger.info(f"Submitting clone_from for branches {', '.join(branch.name for branch in branch_list)} with {optimal_workers} workers")
            futures = [executor.submit(self.clone_from, self.cloned_to.parent, branch=branch.name) for branch in branch_list]
            
            for future in futures:
                try:
                    f = future.result(timeout=THREAD_TIMEOUT_SECONDS)
                    logger.info(f"{f.name} Result branch awaited successful")
                except Exception as e:
                    logger.error(f"Error cloning repository branch {e}")

            logger.info(f"Done awaiting all ({len(futures)}) futures")
        
        return self

    def collect_branches(self) -> "Repository":
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
            _removes = ["HEAD", self.head_name]
            for branch in self.repo_branches:
                if branch.name.split('/', 1)[-1] in _removes:
                    try:
                        self.repo_branches.remove(branch)
                    except ValueError:
                        logger.info(f"{branch.name} not in branches")
            
            logger.info(f"[{self.name}] {len(self.repo_branches)} branches for Repository {self.name}: {self.repo_branches}")

            self.collect_active_branches()
        
        return self
    
    def collect_active_branches(self, active_cutoff_days:int = COMMIT_CUTOFF_DAYS) -> "Repository":
        if not self.repo_branches:
            logger.info(f"[{self.name}] Repo branches is empty, no active to collect")
            return self

        self.active_branches.clear()

        for branch in self.repo_branches:
            active = self._filter_active(branch, active_cutoff_days=active_cutoff_days)
            if active:
                logger.info(f"[{self.name}] {branch.name} is active")
                self.active_branches.append(branch)

        logger.info(f"[{self.name}] {len(self.active_branches)} active branches: {', '.join([b.name for b in self.active_branches])}")

        return self
    
    def _get_head(self) -> str:
        try:
            api_url = f"https://api.github.com/repos/{self.owner}/{self.name}"
            response = requests.get(api_url)
            response.raise_for_status()

            repo_data = response.json()
            default_branch = repo_data.get("default_branch", "main") # Set main as fallback

            return default_branch
        except Exception as e:
            logger.error(f"[{self.name}] {e}")
            return ''

    def _filter_active(self, branch_ref: git.RemoteReference, active_cutoff_days: int = COMMIT_CUTOFF_DAYS) -> bool:
        """
        Check if a branch has been active (committed to) within the given number of days.

        :param branch_name: The name of the branch to check.
        :param active_cutoff_days: The number of days to consider a branch as active (default: 30).
        :return: True if the branch has commits within the cutoff period, False otherwise.
        """
        
        # Branch is None or empty
        if not branch_ref:
            return False
        
        branch_name = branch_ref.name

        if active_cutoff_days <= 0:
            logger.debug(f"{active_cutoff_days=} is off. Returning {branch_ref.name} as active.")
            return True
        
        try:
            logger.debug(f"[{self.name}] {branch_name=}")
            commit = branch_ref.commit
            commit_date = datetime.fromtimestamp(commit.committed_date).date()
            cutoff_date = (datetime.now() - timedelta(days=active_cutoff_days)).date()
            
            logger.info(f"[{self.name}] Commit date for branch {branch_name}: {commit_date}")
            logger.debug(f"[{self.name}] Cutoff date for branch {branch_name}: {cutoff_date}")
            
            days_ago = (datetime.now().date() - commit_date).days
            logger.info(f"[{self.name}] Last commit for branch {branch_name}: {days_ago} days ago")
            
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

def _determine_max_workers(load_factor: float = 1.0, max_limit: int = None) -> int:
    """
    Determine the optimal number of workers for ThreadPoolExecutor based on system resources.

    :param load_factor: A multiplier to adjust the number of threads per CPU core.
                        Use 1.0 for a balanced ratio, higher values for more concurrency.
    :param max_limit: An upper limit for max workers (optional), to avoid overloading the system.
    :return: The optimal number of workers for ThreadPoolExecutor.
    """

    cpus = os.cpu_count()
    available_memory_gb = psutil.virtual_memory().available / (1024 ** 3)
    optimal_workers = int(cpus * load_factor)
    mem_limit = int(available_memory_gb * 10) # ~100 MB per worker

    if max_limit is not None:
        optimal_workers = min(optimal_workers, max_limit)

    optimal_workers = min(optimal_workers, mem_limit)

    return max(1, optimal_workers)

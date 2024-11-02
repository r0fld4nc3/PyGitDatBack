import os
import git
import stat
import shutil
import requests
import psutil
import time
from pathlib import Path
from typing import Tuple, Union
from urllib.parse import urlparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from log import create_logger
from conf_globals import G_LOG_LEVEL, COMMIT_CUTOFF_DAYS, THREAD_TIMEOUT_SECONDS
from utils import get_env_tempdir

logger = create_logger(__name__, G_LOG_LEVEL)

API_GITHUB_NETLOC = "https://api.github.com"
API_GITHUB_REPOS = f"{API_GITHUB_NETLOC}/repos"
API_EXT_GITHUB_BRANCHES = "branches"


class Repository(git.Repo):
    def __init__(self, url):
        # super().__init__(*args, **kwargs)
        self.url: str  = url
        self.name: str  = ""
        self.owner: str = ""
        self.cloned_to: Path = ""
        self.repo: git.Repo = None # Will eventually reference self
        self.head_name = ""
        self.repo_branches: list[git.RemoteReference] = list()
        self.active_branches: list[git.RemoteReference] = list()

        self.max_retries = 3
        self.retry_delay = 30 # seconds
        
        self.owner, self.name = parse_owner_name_from_url(url)
        # self.head_name = self._get_head()

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
            logger.debug(f"[{self.name}] {self.name.lower()} not in {dest}: {self.name} to {dest}")
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
                # Now initialise the base class
                super().__init__(str(clone_dest))
                self.repo = self

        # Don't collect branch names if we're cloning a specific branch already
        # if not kwargs.get("branch", None):
            # self.collect_branches()

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
            api_url = f"{API_GITHUB_REPOS}/{self.owner}/{self.name}"
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
        logger.info(f"Backup dir: {backup_dir}")

        if backup_dir.exists():
            logger.info(f"[{self.name}] Deleting backup-dir: {backup_dir}")
            self.__remove_dir(backup_dir)

            if dir_path.exists():
                try:
                    os.rename(dir_path, backup_dir)
                except Exception as e:
                    logger.error(f"Error in rename: {e}")
        else:
            if dir_path.exists():
                logger.info(f"Removing tree {dir_path}")
                self.__remove_dir(dir_path) # Remove the clone destination. Avoid fatal error
        
        return backup_dir

    def __remove_dir(self, to_remove: Path) -> bool:
        # Try to remove the directory
        logger.debug(f"[{self.name}] shutil.rmtree({to_remove}")
        try:
            shutil.rmtree(to_remove, onerror=_rmtree_on_error) # 3.12 deprecates onerror
        except Exception as e:
            logger.error(f"[{self.name}] {e}", exc_info=1)
            logger.info(f"Python 3.12 deprecated `onerror` and uses `onexc`. Attempting with that...")
            try:
                shutil.rmtree(to_remove, onexc=_rmtree_on_error) # 3.12 replaced onerror with onexc
            except Exception as e:
                logger.error(f"[{self.name}] {e}", exc_info=1)
                return False

        return True

    def __clone_from_basecls(self, url, dest, *args, **kwargs) -> Tuple[bool, Path]:
        attempt = 0
        successful_clone = False

        # Configure longer timeouts
        git_options = {
            'git_options': {
                '-c': [
                    'http.lowSpeedLimit=1000',
                    'http.lowSpeedTime=60',
                    'http.postBuffer=524288000',
                    'http.timeout=300'
                ]
            }
        }
        # kwargs.update(git_options)

        while attempt < self.max_retries:
            try:
                logger.info(f"[{self.name}] Attempt {attempt + 1}/{self.max_retries}: Calling `git.Repo.clone_from({url}, {dest}, {args}, {kwargs})`")
                self.repo = git.Repo.clone_from(self.url, dest, *args, **kwargs)
                successful_clone = True
                logger.info(f"[{self.name}] Successful clone. Breaking attempt loop.")
                break # Important...
            except Exception as e:
                attempt += 1
                logger.warning(f"[{self.name}] Clone attempt {attempt} failed: {e}")

                if attempt < self.max_retries:
                    logger.info(f"[{self.name}] Waiting {self.retry_delay} seconds before retry...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"[{self.name}] All {self.max_retries} attempts failed", exc_info=1)

        return successful_clone, dest
    
def _rmtree_on_error(func, path, exc_info):
    # https://stackoverflow.com/a/2656405
    """
        Error handler for ``shutil.rmtree``.

        If the error is due to an access error (read only file)
        it attempts to add write permission and then retries.

        If the error is for another reason it re-raises the error.

        Usage : ``shutil.rmtree(path, onexc=onerror)``
        """
    # Is the error an access error?
    if not os.access(path, os.W_OK):
        logger.info(f"Re-attempting delete path {path}")
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        logger.error(f"Raising undeletable error for path {path}")
        raise


def parse_owner_name_from_url(url: str) -> Tuple[str, str]:
    logger.info(f"Parsing URL {url}")
    owner: str = ""
    name: str = ""
    
    parsed = urlparse(url)
    netloc = parsed.netloc

    if netloc.lower() != API_GITHUB_NETLOC:
        logger.warning(f"{url} netloc ({netloc} mismatch with API {API_GITHUB_NETLOC})")

    _path = parsed.path
    _path_split = [i for i in _path.split('/') if i] # Also remove empty values

    if len(_path_split) > 1:
        owner = _path_split[0]
        name = _path_split[1]

    logger.info(f"{owner=}")
    logger.info(f"{name=}")

    return owner, name

def validate_github_url(url: str) -> bool:
    """Validates a URL to be of family GitHub and if it exists on the network

    Accepted domain(s) are
    * `github.com`
    
    :return: `True` if domain is valid from accepted domains and repository is accessible.
    """

    logger.info(f"Validating URL {url}")
    
    accepted_domains = ["github.com"]

    parsed = urlparse(url)
    owner, name = parse_owner_name_from_url(url)
    logger.debug(f"{parsed=}")
    netloc = parsed.netloc
    path = parsed.path

    if netloc in accepted_domains:
        if not path:
            logger.info(f"Path must exist and not be a bare url.")
            return False
        
        # Some path exists. Validate if accessible and is valid for repo
        api_url = f"{API_GITHUB_REPOS}/{owner}/{name}"
        if not owner or not name:
            logger.info(f"Owner and Name must be valid: {owner=} | {name=}")
            return False
        
        """response = requests.get(api_url)
        if response.status_code == 200:
            logger.info(f"({response.status_code}) {url} is a valid repository")
            return True
        
        if response.status_code == 404:
            logger.info(f"({response.status_code}) {url} does not exist")
        elif response.status_code == 403:
            logger.info(f"({response.status_code}) {url} rate limit exceeded")
        else:
            logger.info(f"Error or unhandled branch for ({response.status_code}) {url}")"""
        
        return True
        
    else:
        logger.info(f"{netloc} is not a valid {accepted_domains} domain.")
    
    return False

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

def get_branches_and_commits(repo) -> Tuple[int, dict]:
    owner, repo = parse_owner_name_from_url(repo)

    # Endpoint API to list branches
    api_url = f"{API_GITHUB_REPOS}/{owner}/{repo}/{API_EXT_GITHUB_BRANCHES}"
    logger.info(f"{api_url=}")

    ret_info = {}

    response = requests.get(api_url)
    logger.info(f"Response Code: {response.status_code}")
    
    if response.status_code == 200:
        branches_info = response.json()

        for branch in branches_info:
            branch_name = branch["name"]
            last_commit_sha = branch["commit"]["sha"]
            last_commit_url = branch["commit"]["url"]

            ret_info[branch_name] = {
                "last_commit_sha": last_commit_sha,
                "last_commit_url": last_commit_url,
                "last_commit_date": ""
                }

            # Fetch commit details
            commit_response = requests.get(last_commit_url)
            if commit_response.status_code == 200:
                commit_info = commit_response.json()
                commit_date = commit_info["commit"]["committer"]["date"]
                ret_info[branch_name]["last_commit_date"] = commit_date

    elif response.status_code == 403:
        logger.info(f"API rate limit exceeded")

    logger.info(f"{ret_info}")

    return response.status_code, ret_info

def get_branches_shallow_clone(url: str) -> dict:
    temp_dir = get_env_tempdir() / "pygitdatback" / "tempclone"

    branches = {}
    
    try:
        logger.info(f"Cloning {url} to {temp_dir}")
        repo = git.Repo.clone_from(url, temp_dir, depth=1)

        for ref in repo.remote().refs:
            branch_name = ref.remote_head
            last_commmit_sha = ref.commit.hexsha
            last_commmit_date = ref.commit.committed_datetime.isoformat()

            branches[branch_name] = {
                "last_commit_sha": last_commmit_sha,
                "last_commit_date": last_commmit_date
            }
    except Exception as e:
        logger.error(f"{e}")

    logger.debug(f"{branches=}")
    
    return branches

def api_status():
    api_url = API_GITHUB_NETLOC
    logger.info(f"{api_url=}")

    response = requests.get(api_url)
    logger.info(f"Response Code: {response.status_code}")

    return response.status_code

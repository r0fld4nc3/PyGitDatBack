import os
import git
import shutil
from pathlib import Path
from typing import Tuple, Union
from urllib.parse import urlparse

from log import create_logger
from conf_globals import G_LOG_LEVEL

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
        self.repo_branches: list[str] = list()
        
        self.owner, self.name = _parse_repo_url(url)

    # TODO: Filter branches by commit date so we can gatekeep some branches from being cloned, referring to them as "active branches"
    def clone_from(self, dest: Union[Path, str], branch: str = None, *args, **kwargs):
        """`@Override`
        
        Override method to use to clone the designated GitHub URL to disk.

        Performs some necessary preparations for the `Repository` class before calling 
        `git.clone_from()` for the ``git`` library. It does not replace `git.clone_from()`,
        instead builds to it.

        * When no :attr:`branch` is specified, the destination folder will be called `main`
        to indicate that it is the main branch that is being cloned.

        * If :attr:`branch` is specified, it will attempt to clone a branch from the repository
        and name the corresponding destination folder accordingly.

        Attributes it uses/modifies:

        * :attr:`cloned_to`
        """

        # =================================
        #          PREPARATION
        # =================================

        if not isinstance(dest, Path):
            dest = Path(dest).resolve()
        else:
            dest = dest.resolve()

        logger.debug(f"[{self.name}] Resolved destination: {dest}")
        
        if not dest.exists():
            logger.debug(f"[{self.name}] os.makedirs({dest}, exist_ok=True)")
            os.makedirs(dest, exist_ok=True)
        
        if f"{self.name.lower()}" not in dest.name.lower():
            logger.debug(f"[{self.name}] {self.name.lower()} not in {dest}, therefore append {self.name} to {dest}")
            dest = dest / self.name

        if not branch and "branch" not in kwargs:
            logger.debug(f"[{self.name}] No branch set, {branch=}; {kwargs=}")
            dest_end = "main"
        else:
            logger.debug(f"[{self.name}] Branch set, {branch=}; {kwargs=}")
            dest_end = branch

        # The final destination for the specific branch inside the main dest folder
        branch_dest = dest / dest_end

        # =================================
        #             CLONING
        # =================================

        if kwargs.get("branch") or branch:
            if kwargs.get("branch"):
                b = kwargs.get("branch")
            else:
                b = branch
            logger.info(f"[{self.name}] Cloning branch {b} of {self.url} into {branch_dest}")
        else:
            logger.info(f"[{self.name}] Cloning {self.url} into {branch_dest}")

        # If directory exists and is a cloned repo already, rename existing to avoid conflict
        if branch_dest.exists():
            logger.debug(f"[{self.name}] Destination exists: {branch_dest}")
            
            self.cloned_to = branch_dest
            backup_dir = self.set_backup_dir(branch_dest)
            
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

                logger.info(f"[{self.name}] Moving {branch_dest} -> {backup_dir}")
                backup_dir.rename(branch_dest)
        else:
            successful_clone, _ = self.__clone_from_basecls(self.url, branch_dest, args, kwargs)

            if successful_clone:
                self.cloned_to = branch_dest

        if not kwargs.get("branch") and not branch:
            # Don't collect branch names if we're cloning a specific branch already
            self.collect_branch_names()

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

        * :attr:`repo_branches`
        """
        logger.info(f"[{self.name}] Collecting branch names for {self.name}")

        self.repo_branches.clear()

        if self.cloned_to and self.cloned_to.exists():
            git_repo = git.Repo(self.cloned_to)
            logger.info(f"[{self.name}] {git_repo=}")

            self.repo_branches = [head.name for head in git_repo.remote().refs]
            logger.info(f"[{self.name}] Repo branches: {self.repo_branches}")

            # Remove origin/HEAD & main branch/master since we already have it
            logger.info(f"[{self.name}] Deleting origin/HEAD from branch list")
            _removes = ["origin/HEAD", "origin/main", "origin/master"]
            for r in _removes:    
                try:
                    self.repo_branches.remove(r)
                except ValueError:
                    logger.info(f"{r} not in branches")
            
            for idx, value in enumerate(self.repo_branches):
                # Fix origin/name so path is correct
                fixed = value.replace("origin/", "")
                self.repo_branches[idx] = fixed
                logger.debug(f"[{self.name}] Fixed name {value} -> {fixed}")
            
            logger.info(f"[{self.name}] Branches for Repository {self.name}: {self.repo_branches}")
        
        return self

    def set_backup_dir(self, dir_path: Path) -> Path:
        backup_dir: Path = dir_path.parent / f"backup-{dir_path.name}"

        if backup_dir.exists():
            shutil.rmtree(backup_dir)
            logger.info(f"[{self.name}] Deleting backup-dir: {backup_dir}")

        dir_path.rename(backup_dir)
        
        return backup_dir

    def __remove_dir(self, backup_dir: Path) -> bool:
        # Try to remove the directory
        logger.debug(f"[{self.name}] shutil.rmtree({backup_dir})")
        try:
            shutil.rmtree(backup_dir)
        except Exception as e:
            logger.error(f"[{self.name}] {e}", exc_info=1)
            return False

        return True

    def __clone_from_basecls(self, url, dest, branch="", *args, **kwargs) -> Tuple[bool, Path]:
        successful_clone = False
        try:
            logger.debug(f"[{self.name}] Calling `git.Repo.clone_from({url}, {dest}, {args}, {kwargs})`")
            if kwargs.get("branch") or branch:
                logger.debug(f"[{self.name}] branch is valid in kwargs.")
                # Call the original method branch
                git.Repo.clone_from(self.url, dest, branch=branch, *args, **kwargs)
            else:
                # Call the original method no branch
                git.Repo.clone_from(self.url, dest, *args, **kwargs)
            successful_clone = True
        except Exception as e:
            logger.error(f"[{self.name}] {e}", exc_info=1)

        return successful_clone, dest

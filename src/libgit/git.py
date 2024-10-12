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
    owner = ""
    name = ""
    
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
        self.status: bool = False
        self.repo_branches: list[str] = list()
        
        self.owner, self.name = _parse_repo_url(url)

    def clone_to(self, dest: Union[Path, str], branch: str = None, *args, **kwargs):
        if not isinstance(dest, Path):
            dest = Path(dest).resolve()
        else:
            dest = dest.resolve()
        
        if not dest.exists():
            os.makedirs(dest, exist_ok=True)
        
        if f"{self.name.lower()}" not in dest.name.lower():
            dest = dest / self.name

        if not branch and "branch" not in kwargs:
            dest_end = "main"
        else:
            dest_end = branch
        dest = dest / dest_end
        
        self.cloned_to = dest
        logger.info(f"[{self.name}] Cloning {self.url} into {str(dest)}")

        # If directory exists and is a cloned repo already, rename existing to avoid conflict
        if dest.exists():
            logger.info(f"[{self.name}] Destination {dest} exists")
            backup_main = dest.parent / f"backup-{dest_end}"
            if backup_main.exists():
                shutil.rmtree(backup_main)
                logger.info(f"[{self.name}] Deleting backup-main {backup_main}")
            
            logger.info(f"[{self.name}] Moving {dest} -> {backup_main}")
            shutil.move(dest, backup_main)
            
            try:
                logger.info(f"[{self.name}] Calling `.clone_from({self.url}, {dest}, {args}, {kwargs})`")
                if branch or "branch" in kwargs:
                    self.clone_from(self.url, dest, branch=branch, *args, **kwargs)
                else:
                    self.clone_from(self.url, dest, *args, **kwargs)
                    logger.info(f"[{self.name}] Deleting {backup_main} after successful clone")
                shutil.rmtree(backup_main)
            except Exception as e:
                logger.error(f"[{self.name}] {e}")
        else:
            try:
                logger.info(f"[{self.name}] Calling `.clone_from({self.url}, {dest}, {args}, {kwargs})`")
                if branch or "branch" in kwargs:
                    self.clone_from(self.url, dest, branch=branch, *args, **kwargs)
                else:
                    self.clone_from(self.url, dest, *args, **kwargs)
            except Exception as e:
                logger.error(f"[{self.name}] {e}")

        self._collect_branch_names()

        return self

    def _collect_branch_names(self) -> "Repository":
        logger.info(f"[{self.name}] Collecting branch names for {self.name}")

        self.repo_branches.clear()

        if self.cloned_to and self.cloned_to.exists():
            git_repo = git.Repo(self.cloned_to)
            logger.info(f"[{self.name}] {git_repo=}")

            self.repo_branches = [head.name for head in git_repo.remote().refs]
            logger.info(f"[{self.name}] Repo branches: {self.repo_branches}")

            # Remove origin/HEAD & main branch/master since we already have it
            logger.info(f"[{self.name}] Deleting indexes 0:2 from branch list")
            del self.repo_branches[0:2]
            
            for idx, value in enumerate(self.repo_branches):
                # Fix origin/name so path is correct
                fixed = value.replace("origin/", "")
                self.repo_branches[idx] = fixed
                logger.info(f"[{self.name}] Fixed name {value} -> {fixed}")
            
            logger.info(f"[{self.name}] Branches for Repository {self.name}: {self.repo_branches}")
        
        return self

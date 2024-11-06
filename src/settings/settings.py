import os
import sys
import json
from pathlib import Path
from typing import Union

from conf_globals import G_LOG_LEVEL, HOST, APP_NAME
from utils import get_os_env_config_folder, get_home_folder
from log import create_logger

CONFIG_FOLDER = get_os_env_config_folder() / HOST / APP_NAME

logger = create_logger("Settings", G_LOG_LEVEL)


class Settings:
    """
    Singleton-like Settings class for storing and accessing application settings.
    """
    _instance = None
    _loaded = False

    KEY_SAVE_TO = "save_to"
    KEY_SERVICE_SET = "background_service_set"
    KEY_SCHEDULED_TYPE = "schedule_type"
    KEY_SCHEDULED_WEEK_DAY = "schedule_svc_week_day"
    KEY_SCHEDULED_MONTH_DAY = "schedule_svc_month_day"
    KEY_SCHEDULED_MONTH = "schedule_svc_month"
    KEY_SCHEDULED_TIME = "schedule_svc_time"
    KEY_REPOS = "repos"
    KEY_DO_PULL = "do_pull"
    KEY_LAST_PULLED = "last_pulled"
    KEY_BRANCHES = "branches"
    KEY_WIN_SIZE = "window_size"
    KEY_REPO_LOC = "locations"

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
            cls._instance.settings = {
            cls.KEY_SAVE_TO: "",
            cls.KEY_SCHEDULED_TYPE: "",
            cls.KEY_SCHEDULED_MONTH: "",
            cls.KEY_SCHEDULED_MONTH_DAY: "",
            cls.KEY_SCHEDULED_WEEK_DAY: "",
            cls.KEY_SCHEDULED_TIME: "",
            cls.KEY_SERVICE_SET: False,
            cls.KEY_REPOS: {},
            cls.KEY_WIN_SIZE: ""
            }
            cls._instance._config_file_name = "pygitdatback-settings.json"
            cls._instance.config_dir = Path(CONFIG_FOLDER)
            cls._instance.config_file = Path(CONFIG_FOLDER) / cls._instance._config_file_name

            logger.info(f"{CONFIG_FOLDER=}")

            cls._instance.load_config()

        return cls._instance

    def set_save_root_dir(self, p: Union[str, Path]):
        self.settings[self.KEY_SAVE_TO] = str(p).replace("\\\\", '/').replace( "\\", '/')

    def get_save_root_dir(self, fallback: Union[str, Path]=None) -> str:
        if fallback is None:
            fallback = get_home_folder() / HOST / APP_NAME / "Repositories"
            logger.info(f"No fallback set. Setting to: {fallback}")
        
        path = self.settings.get(self.KEY_SAVE_TO, Path(fallback))
        logger.info(f"Retrieved path {path}")
        
        if not path:
            # Path could be just empty
            logger.info(f"Retrieved non sensical path. Setting to fallback {fallback}")
            path = fallback
        
        self.set_save_root_dir(path)
        return path
    
    def save_repo(self, repo_url, do_pull, timestamp:str = "", branches: list = []):
        repo_url = str(repo_url).strip()

        logger.info(f"Save repository {repo_url}\n{do_pull=}, {timestamp=}, {branches=}")

        if self.KEY_REPOS not in self.settings:
            logger.info(f"Creating key {self.KEY_REPOS}")
            self.settings[self.KEY_REPOS] = {}

        if repo_url not in self.settings[self.KEY_REPOS]:
            logger.info(f"{repo_url} not in repo keys")
            logger.debug(f"{self.settings[self.KEY_REPOS]}")
            
            # Structure the repository data
            self.settings[self.KEY_REPOS][repo_url] = {
                self.KEY_DO_PULL: do_pull,
                self.KEY_LAST_PULLED: timestamp,
                self.KEY_BRANCHES: branches,
                self.KEY_REPO_LOC: []
            }
        else:
            self.settings[self.KEY_REPOS][repo_url][self.KEY_DO_PULL] = do_pull
            
            if timestamp:
                self.settings[self.KEY_REPOS][repo_url][self.KEY_LAST_PULLED] = timestamp

            if branches:
                # Technically empty?
                if len(branches) == 1:
                    if not branches[0]:
                        branches.clear()

                info_section = self.settings[self.KEY_REPOS][repo_url]
                if self.KEY_BRANCHES not in info_section:
                    info_section[self.KEY_BRANCHES] = branches
                info_section[self.KEY_BRANCHES] = branches

    def remove_repo(self, repo_url) -> bool:
        repo_url = str(repo_url).strip()

        logger.info(f"Remove repository {repo_url}")

        if self.KEY_REPOS not in self.settings:
            logger.error(f"Key {self.KEY_REPOS} not present.")
            return False

        if repo_url in self.settings[self.KEY_REPOS]:
            del self.settings[self.KEY_REPOS][repo_url]
            logger.info(f"Successfully removed {repo_url}")
        else:
            return False

        return True

    def get_repos(self) -> dict:
        return self.settings.get(self.KEY_REPOS, {})
    
    def save_window_size(self, width: int, height: int):
        self.settings[self.KEY_WIN_SIZE] = [width, height]

    def get_window_size(self) -> list:
        width_height = self.settings.get(self.KEY_WIN_SIZE, [])
        logger.info(f"{width_height=}")
        return width_height

    def save_config(self) -> Path:
        if self.config_dir == '' or not Path(self.config_dir).exists():
            os.makedirs(self.config_dir, exist_ok=True)
            logger.info(f"Generated config folder {self.config_dir}")

        with open(self.config_file, 'w', encoding="utf-8") as config_file:
            config_file.write(json.dumps(self.settings, indent=2))
            logger.info(f"Saved config {self.config_file}")

        return self.config_file
    
    def get_background_service_status(self) -> bool:
        return self.settings.get(self.KEY_SERVICE_SET)
    
    def set_background_service_status(self, status: bool):
        self.settings[self.KEY_SERVICE_SET] = status
        logger.info(f"Set background service status to: {status}")

    def get_schedule_type(self) -> str:
        return self.settings.get(self.KEY_SCHEDULED_TYPE, "")
    
    def set_schedule_type(self, schedule_type: str):
        self.settings[self.KEY_SCHEDULED_TYPE] = schedule_type
        logger.info(f"Set schedule type: {schedule_type}")
    
    def get_scheduled_week_day(self) -> str:
        return self.settings.get(self.KEY_SCHEDULED_WEEK_DAY, "")
    
    def set_scheduled_week_day(self, day: str):
        logger.info(f"Set Scheduled Day to {day}")
        self.settings[self.KEY_SCHEDULED_WEEK_DAY] = day

    def get_scheduled_month_day(self) -> str:
        return self.settings.get(self.KEY_SCHEDULED_MONTH_DAY, "")
    
    def set_scheduled_month_day(self, day: str):
        logger.info(f"Set Scheduled Month Day to {day}")
        self.settings[self.KEY_SCHEDULED_MONTH_DAY] = day
    
    def get_scheduled_month(self) -> int:
        return self.settings.get(self.KEY_SCHEDULED_MONTH, 1)
    
    def set_scheduled_month(self, month: int):
        logger.info(f"Set Scheduled Month to {month}")
        self.settings[self.KEY_SCHEDULED_MONTH] = month
    
    def get_scheduled_time(self) -> str:
        return self.settings.get(self.KEY_SCHEDULED_TIME, "")
    
    def set_scheduled_time(self, time: str) -> str:
        logger.info(f"Set Scheduled Time to {time}")
        self.settings[self.KEY_SCHEDULED_TIME] = time

    def add_repo_locations(self, url, locations: list):
        logger.info(f"Set locations for repository {url}")

        if not isinstance(locations, list):
            locations = [str(locations)]
        
        repo = self.settings[self.KEY_REPOS].get(url)

        if not repo:
            logger.info(f"No repository present: {url}")
            return []
        
        repo_locations: list = repo.get(self.KEY_REPO_LOC, [])

        # Extend avoid duplicates
        repo_locations.extend([str(loc) for loc in locations if str(loc) not in repo_locations])

        self.settings[self.KEY_REPOS][url][self.KEY_REPO_LOC] = repo_locations

        logger.info(f"New repository locations: {repo_locations}")

    def get_repo_locations(self, url) -> list:
        logger.info(f"Getting locations for repository {url}")
        
        repo = self.settings[self.KEY_REPOS].get(url)
        if not repo:
            logger.info(f"Unable to obtain repository: {url}")
            return []
        
        locations = repo.get(self.KEY_REPO_LOC, [])

        logger.info(f"Repository locations: {locations}")

        return locations

    def load_config(self) -> dict:
        if not self._loaded:
            if self.config_dir == '' or not Path(self.config_dir).exists()\
                    or not Path(self.config_file).exists():
                logger.debug(f"Config does not exist.")
                return self.settings

            self.clean_save_file()

            logger.debug(f"Loading config {self.config_file}")
            config_error = False
            with open(self.config_file, 'r', encoding="utf-8") as config_file:
                try:
                    self.settings = json.load(config_file)
                except Exception as e:
                    logger.error("An error occurred trying to read config file.")
                    logger.error(e)
                    config_error = True

            if config_error:
                logger.info("Generating new config file.")
                with open(self.config_file, 'w', encoding="utf-8") as config_file:
                    config_file.write(json.dumps(self.settings, indent=2))
            logger.debug(self.settings)

            self._loaded = True

        return self.settings

    def get_config_dir(self) -> Path:
        if not self.config_dir or not Path(self.config_dir).exists:
            return Path(os.path.dirname(sys.executable))

        return self.config_dir

    def clean_save_file(self) -> bool:
        """
        Removes unused keys from the save file.
        :return: `bool`
        """

        if not self.config_dir or not Path(self.config_dir).exists():
            logger.info("No config folder found.")
            return False

        if not self.config_file.exists():
            logger.info("No config file to cleanup")
            return False

        with open(self.config_file, 'r', encoding="utf-8") as config_file:
            settings = dict(json.load(config_file))
            logger.info(f"[clean_save_file] Loaded settings: {json.dumps(settings, indent=2)}")

        for setting in reversed(list(settings.keys())):
            if setting not in self.settings.keys():
                settings.pop(setting)
                logger.debug(f"Cleared unused settings key: {setting}")

        with open(self.config_file, 'w', encoding="utf-8") as config_file:
            config_file.write(json.dumps(settings, indent=2))
            logger.debug(f"Saved cleaned config: {self.config_file}")

        logger.info("Cleaned-up saved file")

        return True

"""
Settings data, as plain dataclasses.

Every public field is one setting, and its name is its key in the settings file.
How it is stored depends on how it is declared:

    backup_root: str = ""                            # plain field -> written to disk on assignment
    window_width: int = memory(810)                  # memory()    -> kept in memory, written by the next save
    app_version: str = memory("0.1.0", locked=True)  # locked    -> always the default, write-only

Used like normal attributes:

    settings = manager.settings
    settings.schedule_type = "daily"
    repo = manager.repo(url)
    repo.do_pull = False

Change a list by assigning a new one:
    `repo.locations = [*repo.locations, path]`

Not in place:
    `repo.locations.append(path)`

Only assignments are noticed and saved.
"""

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from defines import APP_NAME, APP_VERSION_STR, HOST
from utils import get_home_folder

if TYPE_CHECKING:
    from .settings import SettingsManager

_MEMORY = "MEMORY"
_LOCKED = "LOCKED"

DEFAULT_BACKUP_ROOT = get_home_folder() / HOST / APP_NAME / "Repositories"


def memory(default, locked: bool = False):
    """
    Setting that is kept in memory and only written by the next save.

    locked=True: the value can never change. It is always `default`, never loaded from the file.
    """
    return field(default=default, metadata={_MEMORY: True, _LOCKED: locked})


@dataclass
class AutoSaveHookedSettingsClass:
    """Base class: assigning a public field tells the manager, which then saves it."""

    _manager: Optional["SettingsManager"] = field(default=None, init=False, repr=False, compare=False)
    # Keys found in the file that this version doesn't know about.
    # Written back unchanged, so running an older/newer version of the app doesn't removed them.
    _unknown: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def __setattr__(self, name: str, value):
        manager = getattr(self, "_manager", None)

        # Internal fields, or not attached to a manager yet (ex.: during __init__): just set it.
        if name.startswith("_") or manager is None:
            object.__setattr__(self, name, value)
            return

        if name not in self.__dataclass_fields__:
            # Catches typos like `repo.do_pul = True`, which would otherwise silently do nothing
            raise AttributeError(f"'{type(self).__name__}' has no setting '{name}'.")

        if self._is_locked_field(name):
            raise AttributeError(f"Setting '{name}' is locked and can't be changed.")

        with manager.lock:
            object.__setattr__(self, name, value)
            manager._on_change(save_now=not self._is_memory_field(name))

    @classmethod
    def _is_memory_field(cls, name: str) -> bool:
        return cls._field_flag(name, _MEMORY)

    @classmethod
    def _is_locked_field(cls, name: str) -> bool:
        return cls._field_flag(name, _LOCKED)

    @classmethod
    def _field_flag(cls, name: str, flag: str) -> bool:
        """True if field `name` was declared with `flag` set in its metadata (see memory())."""
        f = cls.__dataclass_fields__.get(name)
        return f is not None and f.metadata.get(flag, False)


@dataclass
class BackupTargetSettings(AutoSaveHookedSettingsClass):
    """Settings shared by everything the app backs up: single repositories and whole accounts."""

    do_pull: bool = True
    last_pulled: str = ""
    # Every backup root this was backed up to, so "Remove from disk" can find all copies
    locations: list[str] = field(default_factory=list)

    def add_location(self, path) -> None:
        path = str(path)
        if path not in self.locations:
            self.locations = [*self.locations, path]

    def record_backup(self, root=None, when: str = "") -> None:
        """
        Record a backup run with a single settings write.

        root: backup root it was written to, added to `locations`. None when nothing was written.
        when: new `last_pulled`. Empty to leave it unchanged (ex.: some repositories failed).
        """
        manager = self._manager
        with manager.batch() if manager else nullcontext():
            if root is not None:
                self.add_location(root)
            if when:
                self.last_pulled = when


@dataclass
class RepoSettings(BackupTargetSettings):
    """One backed-up repository. Stored in `AppSettings.repos` under its URL."""


@dataclass
class AccountSettings(BackupTargetSettings):
    """
    A whole GitHub account. Stored in `AppSettings.accounts` under the owner name.

    Stores the repositories to *skip*, not the ones to include, so repositories the account creates later are backed up automatically.
    """

    include_forks: bool = False
    skipped: list[str] = field(default_factory=list)


@dataclass
class AppSettings(AutoSaveHookedSettingsClass):
    """Main application settings."""

    # --- Locked ---
    # Records which app version last wrote the file. Never read back.
    app_version: str = memory(APP_VERSION_STR, locked=True)

    # --- Saved immediately ---
    backup_root: str = ""  # Empty means DEFAULT_BACKUP_ROOT, see backup_root_path()
    schedule_type: str = ""
    schedule_week_day: str = ""
    schedule_month: int = 1
    schedule_month_day: str = ""
    schedule_time: str = ""
    last_run: str = ""
    repos: dict[str, RepoSettings] = field(default_factory=dict)
    accounts: dict[str, AccountSettings] = field(default_factory=dict)

    # --- Kept in memory ---
    window_width: int = memory(810)
    window_height: int = memory(450)
    max_concurrent_tasks: int = memory(20)  # Backups running at the same time

    def backup_root_path(self) -> Path:
        """Where backups go: the chosen folder, or the default when none is set."""
        return Path(self.backup_root).expanduser() if self.backup_root else DEFAULT_BACKUP_ROOT

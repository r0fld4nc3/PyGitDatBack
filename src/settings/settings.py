"""
Application settings, kept in memory and saved to a JSON file.

Explanation:
- The file is read once at startup (`init()` -> `SettingsManager.load()`).
- Everything reads and changes the in-memory dataclasses (`AppSettings`, `RepoSettings` in models.py).
- Changing a plain field saves the whole file right away.
- Changing a `memory()` field only marks the settings as changed. It is written by the next save, or by `save_if_dirty()`, which runs when the window closes.
- `batch()` groups many changes into one write, and undoes them all if something inside fails.
- `snapshot()` / `restore()` undo a set of changes made since the snapshot.

Safety rules:
- The file is always written and read as UTF-8, regardless of the OS language.
- Writes are atomic: we write a temp file and swap it in with `os.replace`, so the file on disk is always either the old version or the new one, never half written.
- One lock covers every change and every save, so threads (ex.: parallel backups) can't interleave writes.
- A file failed to read is never overwritten. It is renamed to `*.corrupt-<time>` first, and attempted to recover from `*.bak` (a copy of the last file that loaded correctly). If it can't be renamed, saving is turned off for this session.
"""

import copy
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Generator, Optional

from defines import APP_NAME, HOST, EntryKind
from utils import get_os_env_config_folder

from .models import AccountSettings, AppSettings, BackupTargetSettings, RepoSettings

log = logging.getLogger(__name__)

CONFIG_FOLDER = get_os_env_config_folder() / HOST / APP_NAME
SETTINGS_FILE_NAME = "pygitdatback-settings-v1.json"
LEGACY_SETTINGS_FILE_NAME = "pygitdatback-settings-unused.json"

_current: Optional["SettingsManager"] = None


class SettingsManager:
    """Owns the in-memory settings and saves them to disk."""

    def __init__(self, config_dir: Path = CONFIG_FOLDER, config_file_name: str = SETTINGS_FILE_NAME):
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / config_file_name
        self.backup_file = self.config_file.with_name(self.config_file.name + ".bak")
        self.legacy_file = self.config_dir / LEGACY_SETTINGS_FILE_NAME

        # RLock (re-entrant) because a save can happen while the same thread already holds the lock, ex.: assigning a field holds the lock and then saves.
        self.lock = threading.RLock()

        self.settings: AppSettings = self._attach(AppSettings())
        self._dirty = False  # Something changed in memory that isn't on disk yet

        # Inside batch(): saves are held back until the outermost batch ends
        self._batch_depth = 0
        self._save_pending = False

        self.can_save = True

        # Message when something went wrong while loading. Empty if all was fine.
        self.load_problem = ""

    # ---------- Loading ----------

    def load(self) -> bool:
        """
        Read settings from disk. Returns True if settings were loaded (or no file yet).

        Never raises: on any problem we fall back to the backup, then to defaults.
        """
        with self.lock:
            # Import old settings
            if not self.config_file.exists():
                return self._load_with_legacy()

            data = self._read_json(self.config_file)
            if data is not None:
                self.settings = self._from_dict(data)
                self._dirty = False
                log.info(f"Loaded settings from {self.config_file}")
                # Remember the good file in case the next one gets damaged
                self._write_text_atomic(self.backup_file, json.dumps(data, indent=2, ensure_ascii=False))
                return True

            # The file exists but is unusable.
            log.error(f"Settings file could not be read: {self.config_file}")
            corrupt_copy = self._move_aside(self.config_file)
            if corrupt_copy is None:
                self.can_save = False
                self.load_problem = (
                    f"Settings file could not be read:\n{self.config_file}\n\n"
                    "Default settings will be used and changes will NOT be saved this session, so the file is left unchanged."
                )
                return False

            data = self._read_json(self.backup_file)
            if data is not None:
                self.settings = self._from_dict(data)
                self.save_settings()
                self.load_problem = (
                    "Settings file could not be read, settings were restored from the last backup.\n\n"
                    f"The unreadable file was kept as:\n{corrupt_copy}"
                )
                log.warning(f"Restored settings from backup: {self.backup_file}")
                return True

            self.load_problem = (
                "Settings file could not be read and no usable backup was found. "
                "Default settings are used.\n\n"
                f"The unreadable file was kept as:\n{corrupt_copy}"
            )
            log.warning(self.load_problem)
            return False

    def _load_with_legacy(self) -> bool:
        """Carry settings over from the old file, if there is one."""

        # Settings carryover disabled for now
        """
        if not self.legacy_file.exists():
            log.info(f"No settings file yet, using defaults: {self.config_file}")
            return True

        data = self._read_json(self.legacy_file)
        if data is None:
            log.warning(f"Old settings file could not be read, using defaults: {self.legacy_file}")
            return True

        self.settings = self._from_dict(_migrate_legacy(data))
        log.info(f"Moved settings from {self.legacy_file} to {self.config_file}.")
        """
        self.save_settings()
        return True

    def _read_json(self, fp: Path) -> Optional[dict]:
        """Read a JSON object from a file. Returns None if missing, empty or invalid."""
        try:
            # "utf-8-sig" is UTF-8 that also accepts a leading BOM (some editors add one)
            data = json.loads(fp.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        except Exception as e:
            log.error(f"Could not read '{fp}': {e}")
            return None

        if not isinstance(data, dict):
            log.error(f"'{fp}' does not contain a JSON object.")
            return None

        return data

    def _move_aside(self, fp: Path) -> Optional[Path]:
        """Rename a bad file to '<name>.corrupt-<time>'. Returns the new path, or None on failure."""
        target = fp.with_name(f"{fp.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            os.replace(fp, target)
        except OSError as e:
            log.error(f"Could not move unreadable settings file aside: {e}")
            return None
        log.info(f"Kept unreadable settings file as: {target}")
        return target

    def _from_dict(self, data: dict) -> AppSettings:
        """Build AppSettings from a dict, one field at a time. A bad value only resets that field."""
        settings = _dataclass_from_dict(AppSettings, data)

        for name, item_cls in _COLLECTIONS.values():
            items = data.get(name, {})
            if not isinstance(items, dict):
                log.warning(f"Ignoring invalid '{name}' value in settings: {items!r}")
                items = {}

            collection = getattr(settings, name)
            for key, item_data in items.items():
                key = key.strip() if isinstance(key, str) else ""
                if not key or not isinstance(item_data, dict):
                    log.warning(f"Skipping invalid '{name}' entry '{key}': {item_data!r}")
                    continue
                collection[key] = self._attach(_dataclass_from_dict(item_cls, item_data))

        return self._attach(settings)

    # ---------- Saving ----------

    def _on_change(self, save_now: bool):
        """
        Called on every field change (with the lock held).

        save_now=True:  plain field. Save now.
        save_now=False: memory() field. Only remember that something changed.
        """
        self._dirty = True
        if save_now:
            self.save_settings()

    def save_if_dirty(self) -> bool:
        """Write the settings only if something changed since the last save. Thread-safe."""
        with self.lock:
            if not self._dirty:
                return True
            return self.save_settings()

    def save_settings(self) -> bool:
        """Write the current settings to disk. Thread-safe."""
        with self.lock:
            if self._batch_depth:
                # Write once when the batch ends
                self._save_pending = True
                return True

            if not self.can_save:
                log.warning("Saving is disabled this session (settings file was unreadable).")
                return False

            text = json.dumps(self._to_dict(), indent=2, ensure_ascii=False)
            if not self._write_text_atomic(self.config_file, text):
                return False

            self._dirty = False
            log.debug(f"Saved settings to {self.config_file}")
            return True

    def _to_dict(self) -> dict:
        """Turn settings into a plain dict for JSON. Call while holding the lock."""
        data = _dataclass_to_dict(self.settings)
        for name in _COLLECTION_FIELDS:
            data[name] = {key: _dataclass_to_dict(item) for key, item in getattr(self.settings, name).items()}
        return data

    def _write_text_atomic(self, fp: Path, text: str) -> bool:
        """
        Write text to a file, never leaving it half-written.

        Write to a temp file in the same folder, flush to disk, then swap it into place,
        which is atomic on Windows, Linux and macOS with `os.replace()`.
        """
        fp.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(dir=fp.parent, prefix=fp.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())

            # On Windows the target can be briefly locked (antivirus, indexer). Retry a few times.
            for attempt in range(3):
                try:
                    os.replace(temp_path, fp)
                    return True
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.1)
        except Exception as e:
            log.error(f"Could not write '{fp}': {e}")
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return False

    # ---------- Batches and snapshots ----------

    @contextmanager
    def batch(self) -> Generator[AppSettings]:
        """
        Effect many changes with a single write at the end:

            with manager.batch() as s:
                s.schedule_type = "weekly"
                s.schedule_time = "18:00:00"

        If anything inside raises, every change made in the batch is undone and nothing is written.
        Batches can be nested but only the outermost one writes or rolls back.
        Other threads wait while a batch is open.
        """
        with self.lock:
            outermost = self._batch_depth == 0
            before = self.snapshot() if outermost else None
            dirty_before = self._dirty
            self._batch_depth += 1

            try:
                yield self.settings
            except BaseException:
                self._batch_depth -= 1
                if outermost:
                    self._save_pending = False
                    self.settings = self._from_dict(before)
                    self._dirty = dirty_before
                    log.warning("Settings batch failed. Its changes were undone.")
                raise

            self._batch_depth -= 1
            if outermost and self._save_pending:
                self._save_pending = False
                self.save_settings()

    def snapshot(self) -> dict:
        """Copy of the current settings. Passed to `restore()` to undo every change made since."""
        with self.lock:
            return copy.deepcopy(self._to_dict())

    def restore(self, snapshot: dict) -> None:
        """
        Put back settings from `snapshot()` and save. No effect if nothing changed.

        Settings objects fetched earlier (ex.: from `repo()`) are replaced. Must be fetched again after.
        """
        with self.lock:
            if self._to_dict() == snapshot:
                log.debug("Settings already match the snapshot. Nothing to restore.")
                return
            self.settings = self._from_dict(copy.deepcopy(snapshot))
            self._dirty = True
            self.save_settings()
            log.info("Restored settings from snapshot.")

    # ---------- Entries (repositories and accounts) ----------

    def entry(self, kind: EntryKind, key: str) -> BackupTargetSettings:
        """Settings of a repository (key = URL) or account (key = owner), added and saved if new."""
        key = key.strip()
        _, item_cls = _COLLECTIONS[kind]
        if not key:
            # Never store an entry without a key. Hand back a detached object so callers don't crash.
            log.warning(f"Requested {item_cls.__name__} with an empty key; not saving it.")
            return item_cls()

        with self.lock:
            collection = self._collection(kind)
            if key not in collection:
                collection[key] = self._attach(item_cls())
                self._on_change(save_now=True)
            return collection[key]

    def find(self, kind: EntryKind, key: str) -> Optional[BackupTargetSettings]:
        """Settings of an entry, or None if it isn't stored. Never adds anything."""
        return self._collection(kind).get(key.strip())

    def has(self, kind: EntryKind, key: str) -> bool:
        return self.find(kind, key) is not None

    def remove(self, kind: EntryKind, key: str) -> bool:
        with self.lock:
            if self._collection(kind).pop(key.strip(), None) is None:
                return False
            self._on_change(save_now=True)
            return True

    def _collection(self, kind: EntryKind) -> dict:
        field_name, _ = _COLLECTIONS[kind]
        return getattr(self.settings, field_name)

    # ---------- Typed shortcuts ----------

    def repo(self, url: str) -> RepoSettings:
        return self.entry(EntryKind.REPO, url)

    def has_repo(self, url: str) -> bool:
        return self.has(EntryKind.REPO, url)

    def remove_repo(self, url: str) -> bool:
        return self.remove(EntryKind.REPO, url)

    def rename_repo(self, old_url: str, new_url: str) -> RepoSettings:
        """Move a repository's settings to a new URL, keeping its order in the list."""
        old_url, new_url = old_url.strip(), new_url.strip()

        with self.lock:
            if old_url not in self.settings.repos or old_url == new_url:
                return self.repo(new_url)

            self.settings.repos = {
                (new_url if url == old_url else url): repo for url, repo in self.settings.repos.items()
            }
            return self.settings.repos[new_url]

    def account(self, owner: str) -> AccountSettings:
        return self.entry(EntryKind.ACCOUNT, owner)

    def has_account(self, owner: str) -> bool:
        return self.has(EntryKind.ACCOUNT, owner)

    def remove_account(self, owner: str) -> bool:
        return self.remove(EntryKind.ACCOUNT, owner)

    def _attach(self, obj):
        """Link a settings object to this manager so changes to it get saved."""
        obj._manager = self
        return obj


# ---------- Dataclass <-> dict helpers ----------

# AppSettings fields holding `{key: settings object}`, and the class of their items
_COLLECTIONS = {
    EntryKind.REPO: ("repos", RepoSettings),
    EntryKind.ACCOUNT: ("accounts", AccountSettings),
}
_COLLECTION_FIELDS = {name for name, _ in _COLLECTIONS.values()}


def _dataclass_from_dict(cls, data: dict):
    """
    Create `cls` from `data`, checking each field's type against its default value.
    Missing or wrongly typed values keep the default. Unknown keys are kept in `_unknown`.
    Locked fields always keep their default value(s) and are ignored but still written.
    """
    obj = cls()
    known = set()

    for f in fields(cls):
        if f.name.startswith("_"):
            continue
        known.add(f.name)

        if f.name in _COLLECTION_FIELDS or f.name not in data:
            continue  # Collections are handled by the caller

        if cls._is_locked_field(f.name):
            continue

        value = data[f.name]
        default = f.default if f.default is not MISSING else f.default_factory()

        if type(value) is not type(default):
            log.warning(f"Ignoring setting '{f.name}' with unexpected value {value!r}. Using default.")
            continue

        setattr(obj, f.name, value)

    obj._unknown = {k: v for k, v in data.items() if k not in known}
    return obj


def _dataclass_to_dict(obj) -> dict:
    """Public fields of a settings dataclass, plus any unknown keys we read from the file."""
    data = dict(obj._unknown)
    for f in fields(obj):
        if not f.name.startswith("_") and f.name not in _COLLECTION_FIELDS:
            value = getattr(obj, f.name)
            data[f.name] = list(value) if isinstance(value, list) else value
    return data


def _migrate_legacy(old: dict) -> dict:
    """Convert the pre-0.1.0 settings layout to the current field names."""
    renames = {
        "save_to": "backup_root",
        "schedule_type": "schedule_type",
        "schedule_svc_week_day": "schedule_week_day",
        "schedule_svc_month": "schedule_month",
        "schedule_svc_month_day": "schedule_month_day",
        "schedule_svc_time": "schedule_time",
        "last_run": "last_run",
    }
    data = {new: old[key] for key, new in renames.items() if key in old}

    window = old.get("window_size")
    if isinstance(window, list) and len(window) == 2:
        data["window_width"], data["window_height"] = window

    data["repos"] = {
        url: {key: value for key, value in info.items() if key in ("do_pull", "last_pulled", "locations")}
        for url, info in old.get("repos", {}).items()
        if isinstance(info, dict)
    }
    return data


# ---------- Module access ----------


def init(config_dir: Path = CONFIG_FOLDER) -> SettingsManager:
    """Create the settings manager and load the file. Call once at startup."""
    global _current

    if _current is None:
        _current = SettingsManager(config_dir)
        _current.load()

    return _current


def get() -> SettingsManager:
    if _current is None:
        raise RuntimeError("Settings are not initialised. Call settings.init() first.")
    return _current

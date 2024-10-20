import os
from pathlib import Path
import platform
import subprocess
import shutil
from log import create_logger
from conf_globals import G_LOG_LEVEL

log = create_logger("OS FS Utils", G_LOG_LEVEL)

WINDOWS = "windows"
LINUX = "linux"
UNIX = "unix"
DARWIN = "darwin"
MAC = "mac"


def win_get_appdata() -> Path:
    if os_windows():
        return Path(os.getenv("appdata"))
    else:
        return unix_get_share_folder()


def win_get_localappdata() -> Path:
    if os_windows():
        return Path(os.getenv("localappdata"))
    else:
        return unix_get_share_folder()


def win_get_documents_folder() -> Path:
    if os_windows():
        return get_home_folder() / "Documents"
    else:
        return unix_get_share_folder()


def unix_get_share_folder() -> Path:
    if not os_windows():
        return unix_get_local_folder() / "share"
    else:
        return win_get_localappdata()


def unix_get_local_folder() -> Path:
    if not os_windows():
        return get_home_folder() / ".local"
    else:
        return win_get_localappdata()


def unix_get_config_folder() -> Path:
    if not os_windows():
        return get_home_folder() / ".config"
    else:
        return win_get_localappdata()


def get_home_folder() -> Path:
    return Path(os.path.expanduser('~'))


def get_env_tempdir() -> Path:
    if os_windows():
        _tempdir = win_get_localappdata() / "Temp"
    else:
        _tempdir = unix_get_share_folder() / "temp"

    # Ensure path exists
    ensure_paths(_tempdir)

    return _tempdir


def get_os_env_config_folder() -> Path:
    if os_windows():
        log.info("Target System Windows")
        _config_folder = win_get_localappdata()
    elif os_linux():
        log.info("Target System Linux/Unix")
        _config_folder = unix_get_share_folder()
    elif os_darwin():
        log.info("Target System MacOS")
        # Write to user-writable locations, like ~/.local/share
        _config_folder = unix_get_share_folder()
    else:
        log.info("Target System Other")
        log.info(system())
        _config_folder = Path.cwd()

    ensure_paths(_config_folder)
    log.info(f"Config folder: {_config_folder}")

    return _config_folder


def ensure_paths(to_path: Path):
    if isinstance(to_path, Path):
        if not to_path.exists():
            if to_path.suffix:
                # It's a file
                os.makedirs(to_path.parent, exist_ok=True)
                with open(to_path, 'w') as f:
                    if to_path.suffix == ".json":
                        f.write('{}')
                    else:
                        f.write('')
            else:
                # It's a directory
                os.makedirs(to_path, exist_ok=True)
    elif isinstance(to_path, str):
        if not os.path.exists(to_path):
            if str(to_path).rpartition('.')[-1]:
                # We have a file
                os.makedirs(to_path.rpartition('.')[0])
                with open(to_path, 'w') as f:
                    if to_path.endswith(".json") == ".json":
                        f.write('{}')
                    else:
                        f.write('')
            else:
                os.makedirs(to_path)

    return Path(to_path)


def get_system_drive() -> Path:
    _drive = os.getenv("SystemDrive")
    if os_windows():
        _drive += "/"
    else:
        _drive = get_home_folder()
    return Path(_drive)


def get_temp_dir() -> Path:
    if os_windows():
        tmp_dir = Path(os.path.expandvars("%TEMP%"))
    elif os_linux() or os_darwin():
        tmp_dir = Path("/tmp")
    else:
        tmp_dir = Path(os.path.expanduser('~'))

    return tmp_dir


def os_linux() -> bool:
    return system() in [LINUX, UNIX]


def os_darwin() -> bool:
    return system() in [DARWIN, MAC]


def os_windows() -> bool:
    return system() in [WINDOWS]


def system() -> str:
    return platform.system().lower()


def _get_clipboard_client() -> str:
    # In MacOS it's pbcopy
    # In Linux, it can be either xclip, xsel or both

    clipboard_client = ''

    if os_linux():
        # Try with xclip
        log.info("Checking clipboard client xclip")
        _clip = "xclip"

        output = subprocess.run([_clip], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        result = output.stdout.decode()

        if "command not found" in result.lower():
            log.warning(f"{_clip} is not an option")
        else:
            clipboard_client = _clip
            log.info(f"{_clip} passed!")

        # Try with xsel
        if not clipboard_client:
            _clip = "xsel"

            log.info(f"Checking clipboard client {_clip}")
            output = subprocess.run([_clip], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            result = output.stdout.decode()

            log.info(result)

            if "command not found" in result.lower():
                log.warning(f"{_clip} is not an option. Out of options...")
            else:
                clipboard_client = _clip
                log.info(f"{_clip} passed!")
    elif os_darwin():
        _clip = "pbcopy"
        output = subprocess.run([_clip], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        result = output.stdout.decode()

        if "command not found" in result.lower():
            log.warning(f"{_clip} is not an option. Out of options...")
        else:
            clipboard_client = _clip

        log.info(result)
    elif os_windows():
        _clip = "clip"
        clipboard_client = _clip
    else:
        log.warning("Uh oh...")

    return clipboard_client


def send_to_clipboard(content: str) -> None:
    clipboard_client = _get_clipboard_client()

    if not clipboard_client:
        return

    temp_folder: Path = get_temp_dir() / ".temp_clipboard"
    temp_file: Path = temp_folder / ".temp_clipboard.txt"

    # Ensure path is created
    os.makedirs(temp_folder, exist_ok=True)

    with open(temp_file, 'w', encoding="utf-8") as tf:
        tf.write(str(content))

    if not os_windows():
        command = [clipboard_client, "-sel", "clip <", str(temp_file)]
    else:
        command = f"{clipboard_client} < {str(temp_file)}"

    if not command:
        # Delete the temp file and folder
        log.info(f"Deleting {temp_folder}")
        shutil.rmtree(temp_folder, ignore_errors=True)
        return

    try:
        subprocess.run(command)
    except Exception as e:
        log.error(e)

    # Delete the temp file and folder
    log.info(f"Deleting {temp_folder}")
    shutil.rmtree(temp_folder, ignore_errors=True)

    log.info(f"\nContents copied to clipboard!")


def diff_files_in_dir(in_dir: Path, against: list) -> list[Path]:
    _diff = []

    for fs_iter in in_dir.iterdir():
        print(f"{fs_iter} in _checked_out: {fs_iter in against}")

        if fs_iter not in against:
            _diff.append(Path(fs_iter))

    log.info(f"Diff of {against}")
    for diff in _diff:
        log.info(f"Diff {str(diff)}")

    return _diff

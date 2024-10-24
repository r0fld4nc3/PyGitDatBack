import subprocess
import shutil
from typing import Tuple
from pathlib import Path

from conf_globals import G_LOG_LEVEL
from log import create_logger
from utils import get_env_tempdir

logger = create_logger(__name__, G_LOG_LEVEL)

_THIS_FILE_PATH = Path(__file__).parent.resolve()

REQUIREMENTS = _THIS_FILE_PATH.parent / "requirements.txt"

SYSTEMD_SYSTEM_PATH = Path("/etc/systemd/system")

VENV_PATH = get_env_tempdir() / "PyGitDatBack.venv"
VENV_BIN_PATH = VENV_PATH / "bin"/ "python3"

SERVICE_FILE_TO_COPY = _THIS_FILE_PATH / "pygitdatback-noui.service"
SERVICE_FILE_IN_PLACE = SYSTEMD_SYSTEM_PATH / "pygitdatback-noui.service"

TIMER_FILE_TO_COPY = _THIS_FILE_PATH / "pygitdatback-noui.timer"
TIMER_FILE_IN_PLACE = SYSTEMD_SYSTEM_PATH / "pygitdatback-noui.timer"

REGISTER_SHELL_FILE = _THIS_FILE_PATH / "register.sh"
UNREGISTER_SHELL_FILE = _THIS_FILE_PATH / "unregister.sh"

def register_service() -> Tuple[bool, str]:
    success = True
    status = ""
    
    # Copy files to temp
    temp_service_file = get_env_tempdir() / SERVICE_FILE_TO_COPY.name

    success = shutil.copyfile(SERVICE_FILE_TO_COPY, temp_service_file)

    if not success:
        status = f"Unable to copy {str(SERVICE_FILE_TO_COPY)} to {str(temp_service_file)}"
        return success, status
    
    _replace_service_file_vars(temp_service_file)

    if success:
        cmd_to_copy = f"chmod +x {str(REGISTER_SHELL_FILE)} && {str(REGISTER_SHELL_FILE)} {str(VENV_PATH)} {str(REQUIREMENTS)} {str(temp_service_file)} {str(SERVICE_FILE_IN_PLACE)} {str(TIMER_FILE_TO_COPY)} {str(TIMER_FILE_IN_PLACE)}"
        status = cmd_to_copy
        logger.info(status)

    return success, status

def unregister_service() -> Tuple[bool, str]:
    success = True
    status = ""
    
    cmd_to_copy = f"chmod +x {str(UNREGISTER_SHELL_FILE)} && {str(UNREGISTER_SHELL_FILE)} {str(SERVICE_FILE_IN_PLACE)} {str(TIMER_FILE_IN_PLACE)}"
    status = cmd_to_copy
    logger.info(status)

    return success, status

def _read_file(file_path: Path) -> list[str]:
    contents = []
    if file_path.exists():
        # Read
        with open(file_path, 'r') as fp:
            contents = fp.readlines()

    return contents

def _write_contents(file_path: Path, contents: list[str]) -> bool:
    try:
        if contents:
            with open(file_path, 'w') as f:
                f.writelines(contents)
            logger.info(f"Wrote lines to {str(file_path)}")
    except Exception as e:
        logger.error(f"Error writing file {str(file_path)}: {e}")
        return False
    
    return True

def _replace_service_file_vars(service_file_path: Path):
    python_path = "{{PYTHON_PATH}}"

    service_path_to_entry_point = "{{PATH_TO_ENTRY_POINT}}" 
    entry_point_path = Path(__file__).parent.parent / "main.py --no-ui"

    service_path_to_project = "{{PATH_TO_PROJECT}}"
    path_to_project = Path(__file__).parent.parent.parent

    if service_file_path.exists():
        # Read
        contents = _read_file(service_file_path)
        if contents:
            for i, line in enumerate(contents):
                if python_path in line:
                    line = line.replace(python_path, str(VENV_BIN_PATH))
                    contents[i] = line
                
                if service_path_to_entry_point in line:
                    line = line.replace(service_path_to_entry_point, str(entry_point_path))
                    contents[i] = line
                
                if service_path_to_project in line:
                    line = line.replace(service_path_to_project, str(path_to_project))
                    contents[i] = line

        # Write - duh
        _write_contents(service_file_path, contents)

def _copy_service_files() -> tuple[bool, str]:
    success = True
    status = ""

    try:
        _try_except([["sudo", "cp", str(SERVICE_FILE_TO_COPY), str(SERVICE_FILE_IN_PLACE)]])
        # shutil.copy2(SERVICE_FILE_TO_COPY, SERVICE_FILE_IN_PLACE)
        logger.info(f"Copied {str(SERVICE_FILE_TO_COPY)} to {str(SERVICE_FILE_IN_PLACE)}")

        _try_except([["sudo", "cp", str(TIMER_FILE_TO_COPY), str(TIMER_FILE_IN_PLACE)]])
        # shutil.copy2(TIMER_FILE_TO_COPY, TIMER_FILE_IN_PLACE)
        logger.info(f"Copied {str(TIMER_FILE_TO_COPY)} to {str(TIMER_FILE_IN_PLACE)}")

        status = f"Copied service files to {str(SYSTEMD_SYSTEM_PATH)}"
    except Exception as e:
        status = f"Error copying service file(s): {e}"
        success = False
    
    if not success:
        logger.error(f"[{success}, {status}]")
    else:
        logger.debug(f"[{success}, {status}]")

    return success, status

def _try_except(cmds: list[list], run_in_term=False) -> Tuple[bool, str]:
    success = True
    status = ""

    # Monkey path PosixPaths
    for cmd in cmds:
        logger.debug(f"{cmd=}")
        for i, cmd_contents in enumerate(cmd):
            if isinstance(cmd_contents, Path):
                cmd[i] = str(cmd_contents)
                logger.info(f"Replaced {cmd_contents} at {i} to str.")

    logger.debug(cmds)

    try:
        if not run_in_term:
            for cmd in cmds:
                logger.debug(' '.join(cmd))
                subprocess.run(cmd, check=True)
        else:
            for cmd in cmds:
                full_command = ' '.join(cmd)
                subprocess.run(["gnome-terminal", "--", "bash", "-c", full_command])
    except Exception as e:
        success = False
        status = e
    
    if not success:
        logger.error(f"[{success}, {status}]")
    else:
        logger.debug(f"[{success}, {status}]")

    return success, status

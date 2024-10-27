import subprocess
import shutil
from typing import Tuple
from pathlib import Path

from conf_globals import G_LOG_LEVEL, HOST, APP_NAME
from log import create_logger
from utils import get_os_env_config_folder

logger = create_logger(__name__, G_LOG_LEVEL)

_THIS_FILE_PATH = Path(__file__).parent.resolve()

# /home/user/.local/share/r0fld4nc3/PyGitDatBack
WORK_DIR = get_os_env_config_folder() / HOST / APP_NAME
VENV_PATH = WORK_DIR / "PyGitDatBack.venv"
VENV_BIN_PATH = VENV_PATH / "bin"/ "python3"

SERVICE_FILE_TO_COPY = _THIS_FILE_PATH / "services" / "pygitdatback-noui.service"

TIMER_FILE_TO_COPY = _THIS_FILE_PATH / "services" / "pygitdatback-noui.timer"

REGISTER_SHELL_FILE = _THIS_FILE_PATH / "shell_scripts" / "register.sh"
UNREGISTER_SHELL_FILE = _THIS_FILE_PATH / "shell_scripts" / "unregister.sh"

def register_service() -> Tuple[bool, str]:
    success = True
    status = ""
    
    # Copy files to temp
    temp_service_file = WORK_DIR / SERVICE_FILE_TO_COPY.name

    success = shutil.copyfile(SERVICE_FILE_TO_COPY, temp_service_file)

    if not success:
        status = f"Unable to copy {str(SERVICE_FILE_TO_COPY)} to {str(temp_service_file)}"
        return success, status
    
    _replace_service_file_vars(temp_service_file)

    if success:
        cmd_to_copy = f"chmod +x {str(REGISTER_SHELL_FILE)} && {str(REGISTER_SHELL_FILE)} {str(temp_service_file)} {str(TIMER_FILE_TO_COPY)}"
        status = cmd_to_copy
        logger.info(status)

    return success, status

def unregister_service() -> Tuple[bool, str]:
    success = True
    status = ""
    
    cmd_to_copy = f"chmod +x {str(UNREGISTER_SHELL_FILE)} && {str(UNREGISTER_SHELL_FILE)} {str(SERVICE_FILE_TO_COPY.name)} {str(TIMER_FILE_TO_COPY.name)}"
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

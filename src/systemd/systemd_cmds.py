import shutil
from typing import Tuple
from pathlib import Path
from enum import Enum

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

"""
# Daily at specific time
OnCalendar=*-*-* 14:30:00        # Every day at 14:30
OnCalendar=daily 14:30:00        # Same as above

# Weekly on specific days
OnCalendar=Mon,Fri *-*-* 18:00:00  # Every Monday and Friday at 18:00
OnCalendar=Sat,Sun 14:30:00        # Weekends at 14:30

# Monthly
OnCalendar=*-*-1 00:00:00        # First day of every month at midnight
OnCalendar=*-*-15 15:00:00       # 15th of every month at 15:00

# Specific months
OnCalendar=*-1,4,7,10-1 12:00:00 # First day of Jan, Apr, Jul, Oct at 12:00

# Multiple times per day
OnCalendar=*-*-* 9,12,15:00:00   # Every day at 9:00, 12:00, and 15:00

# Time intervals
OnCalendar=*-*-* *:00/2:00       # Every 2 hours
OnCalendar=*-*-* *:00/30:00      # Every 30 minutes

# Yearly
OnCalendar=*-12-31 23:59:00      # Every New Year's Eve at 23:59

# Time ranges
OnCalendar=Mon..Fri *-*-* 9:00   # Weekdays at 9:00
OnCalendar=*-*-* 9:00..17:00     # Every hour from 9:00 to 17:00
"""

class ScheduleTypes(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MONTH_SPEC = "month"
    EVERY = "every"
    YEARLY = "yearly"


def format_schedule(schedule_type: str, week_day: str="Fri", month: str="1", month_day: str="1", time: str="18:00:00"):
    schedule_type = schedule_type.lower()
    
    logger.info(f"Type to schedule is {schedule_type}")
    logger.info(f"{week_day=}")
    logger.info(f"{month=}")
    logger.info(f"{month_day=}")
    logger.info(f"{time=}")

    if schedule_type == ScheduleTypes.DAILY.value:
        return f"*-*-* {time}"
    
    if schedule_type == ScheduleTypes.WEEKLY.value:
        return f"{week_day} *-*-* {time}"

    if schedule_type == ScheduleTypes.MONTHLY.value:
        return f"*-*-{month_day} {time}"
    
    if schedule_type == ScheduleTypes.MONTH_SPEC.value:
        return f"*-{month}-{month_day} {time}"
    
    if schedule_type == ScheduleTypes.YEARLY.value:
        return f"*-{month}-{month_day} {time}"
    
    # Return a default
    return f"{week_day} *-*-* {time}"

def register_service(schedule_type=ScheduleTypes.WEEKLY.value, week_day: str="Fri", month: str="1,3,6,8,12", month_day: str="6", time: str="18:00:00") -> Tuple[bool, str]:
    success = True
    status = ""
    
    # Copy files to temp
    temp_service_file = WORK_DIR / SERVICE_FILE_TO_COPY.name
    temp_timer_file = WORK_DIR / TIMER_FILE_TO_COPY.name

    success = shutil.copyfile(SERVICE_FILE_TO_COPY, temp_service_file)
    if not success:
        status = f"Unable to copy {str(SERVICE_FILE_TO_COPY)} to {str(temp_service_file)}"
        return success, status

    success = shutil.copyfile(TIMER_FILE_TO_COPY, temp_timer_file)
    if not success:
        status = f"Unable to copy {str(TIMER_FILE_TO_COPY)} to {str(temp_timer_file)}"
        return success, status
    
    schedule = format_schedule(schedule_type, week_day, month, month_day, time)
    _replace_service_file_vars(temp_service_file)
    _replace_timer_file_vars(temp_timer_file, schedule)

    if success:
        cmd_to_copy = f"chmod +x {str(REGISTER_SHELL_FILE)} && {str(REGISTER_SHELL_FILE)} {str(temp_service_file)} {str(temp_timer_file)}"
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

def _replace_timer_file_vars(timer_file_path: Path, schedule: str):
    schedule_var = "{{SCHEDULE}}"

    if timer_file_path.exists():
        # Read
        contents = _read_file(timer_file_path)
        if contents:
            for i, line in enumerate(contents):
                if schedule_var in line:
                    line = line.replace(schedule_var, schedule)
                    contents[i] = line

        # Write - duh
        _write_contents(timer_file_path, contents)

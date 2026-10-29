import logging
from enum import StrEnum
from pathlib import Path

from defines import APP_NAME, HOST
from utils import get_os_env_config_folder

logger = logging.getLogger(__name__)

_THIS_FILE_PATH = Path(__file__).parent.resolve()

# /home/user/.local/share/r0fld4nc3/PyGitDatBack
WORK_DIR = get_os_env_config_folder() / HOST / APP_NAME
VENV_PATH = WORK_DIR / "PyGitDatBack.venv"
VENV_BIN_PATH = VENV_PATH / "bin" / "python3"

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


class ScheduleType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MONTH_SPEC = "month"
    EVERY = "every"
    YEARLY = "yearly"


# systemd OnCalendar expression for each schedule type.
# Anything not listed runs weekly.
_SCHEDULE_TEMPLATES = {
    ScheduleType.DAILY: "*-*-* {time}",
    ScheduleType.WEEKLY: "{week_day} *-*-* {time}",
    ScheduleType.MONTHLY: "*-*-{month_day} {time}",
    ScheduleType.MONTH_SPEC: "*-{month}-{month_day} {time}",
    ScheduleType.YEARLY: "*-{month}-{month_day} {time}",
}


def format_schedule(
    schedule_type: str, week_day: str = "Fri", month: str = "1", month_day: str = "1", time: str = "18:00:00"
) -> str:
    """The OnCalendar expression for the timer file."""
    schedule_type = schedule_type.lower()
    logger.info(f"Type to schedule is {schedule_type}: {week_day=} {month=} {month_day=} {time=}")

    template = _SCHEDULE_TEMPLATES.get(schedule_type, _SCHEDULE_TEMPLATES[ScheduleType.WEEKLY])
    return template.format(week_day=week_day, month=month, month_day=month_day, time=time)


def register_service(
    schedule_type=ScheduleType.WEEKLY,
    week_day: str = "Fri",
    month: str = "1,3,6,8,12",
    month_day: str = "1",
    time: str = "18:00:00",
) -> tuple[bool, str]:
    """
    Fill in the service and timer files, and return the command that installs them.
    Returns (False, reason) if the files couldn't be prepared.
    """
    service_file = WORK_DIR / SERVICE_FILE_TO_COPY.name
    timer_file = WORK_DIR / TIMER_FILE_TO_COPY.name

    try:
        _fill_template(
            SERVICE_FILE_TO_COPY,
            service_file,
            {
                "{{PYTHON_PATH}}": str(VENV_BIN_PATH),
                "{{PATH_TO_ENTRY_POINT}}": str(Path(__file__).parent.parent / "main.py --no-ui"),
                "{{PATH_TO_PROJECT}}": str(Path(__file__).parent.parent.parent),
            },
        )
        _fill_template(
            TIMER_FILE_TO_COPY,
            timer_file,
            {"{{SCHEDULE}}": format_schedule(schedule_type, week_day, month, month_day, time)},
        )
    except OSError as e:
        status = f"Unable to prepare the service files in {WORK_DIR}: {e}"
        logger.error(status)
        return False, status

    command = f"chmod +x {REGISTER_SHELL_FILE} && {REGISTER_SHELL_FILE} {service_file} {timer_file}"
    logger.info(command)
    return True, command


def unregister_service() -> tuple[bool, str]:
    """Command to stop and remove installed service and timer."""
    command = (
        f"chmod +x {UNREGISTER_SHELL_FILE} && {UNREGISTER_SHELL_FILE} "
        f"{SERVICE_FILE_TO_COPY.name} {TIMER_FILE_TO_COPY.name}"
    )
    logger.info(command)
    return True, command


def _fill_template(template: Path, destination: Path, replacements: dict[str, str]) -> None:
    """Copy `template` to `destination`, replacing each placeholder with its value."""
    text = template.read_text()
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)
    logger.info(f"Wrote {destination}")

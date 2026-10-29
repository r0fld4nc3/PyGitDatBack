from datetime import datetime
from enum import StrEnum


class TimestampFormat(StrEnum):
    """The timestamp formats stored in settings. Changing one changes what is written to the file."""

    LAST_RUN = "%d-%m-%Y %H:%M:%S"  # AppSettings.last_run
    PULLED = "%Y-%m-%d %H:%M:%S"  # last_pulled of repositories and accounts, also shown in the table


def timestamp(fmt: TimestampFormat) -> str:
    """The current local time in `fmt`."""
    return datetime.now().strftime(fmt)

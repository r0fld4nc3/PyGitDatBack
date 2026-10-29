from enum import StrEnum

APP_VERSION: tuple = (0, 1, 0)
APP_VERSION_STR = ".".join(str(part) for part in APP_VERSION)
HOST: str = "r0fld4nc3"
APP_NAME: str = "PyGitDatBack"
DRY_RUN = False


class EntryKind(StrEnum):
    """What a backup entry is. Shared by GitHub URL parsing, settings and the main table."""

    REPO = "repo"  # A single repository
    ACCOUNT = "account"  # Every repository of a GitHub user or organisation

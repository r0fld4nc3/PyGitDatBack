from log import create_logger, reset_log_file
from conf_globals import G_LOG_LEVEL

from ui import GitDatBackUI

logger = create_logger("src.main", G_LOG_LEVEL)

def launch_ui() -> bool:
    reset_log_file()
    app = GitDatBackUI()
    app.show()

if __name__ == "__main__":
    launch_ui()
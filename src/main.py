import argparse

from log import create_logger, reset_log_file
from conf_globals import G_LOG_LEVEL
from ui import GitDatBackUI

logger = create_logger(__name__, G_LOG_LEVEL)

def main():
    parser = argparse.ArgumentParser(description="Main entry point for the application.")
    parser.add_argument("--no-ui", action="store_true", help="Run the pull routine automatically without UI and close.")

    args = parser.parse_args()

    if args.no_ui:
        launch_no_ui()
    else:
        launch_ui()

def launch_ui() -> bool:
    reset_log_file()
    logger.info("Launching GUI application")
    app = GitDatBackUI()
    app.show()

def launch_no_ui() -> bool:
    reset_log_file()
    logger.info("Launching no GUI")
    GitDatBackUI.pull_repos_no_ui()
    logger.info("Finished. Exiting.")


if __name__ == "__main__":
    main()

# Stuff that might be required for system tray, following some tests, but unable to get it running.
# system requirements linux: libayatana-appindicator-devel, libayatana-indicator3-devel, libayatana-appindicator3-devel, typelib-1_0-AyatanaAppIndicator-0_1
# python requirements: gi, pygobject, python311-gobject-devel, python312-gobject-devel

import argparse
import logging

import settings
from log import LOG_FILE, configure_logging, reset_log_file
from ui import GitDatBackUI

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Main entry point for the application.")
    parser.add_argument("--no-ui", action="store_true", help="Run the pull routine automatically without UI and close.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()

    # Configure the root logger/logging at startup.
    reset_log_file(LOG_FILE)
    configure_logging(logging.DEBUG if args.debug else logging.INFO, LOG_FILE)
    logger.info(f"Log file: {LOG_FILE}")

    # Load settings once. Everything else uses settings.get()
    config = settings.init()
    if config.load_problem:
        logger.warning(config.load_problem)

    if args.no_ui:
        launch_no_ui()
    else:
        launch_ui()


def launch_ui() -> bool:
    logger.info("Launching GUI application")
    app = GitDatBackUI()
    app.show()


def launch_no_ui() -> bool:
    logger.info("Launching no GUI")
    GitDatBackUI.pull_repos_no_ui()
    logger.info("Finished. Exiting.")


if __name__ == "__main__":
    main()

# Stuff that might be required for system tray, following some tests, but unable to get it running.
# system requirements linux: libayatana-appindicator-devel, libayatana-indicator3-devel, libayatana-appindicator3-devel, typelib-1_0-AyatanaAppIndicator-0_1
# python requirements: gi, pygobject, python311-gobject-devel, python312-gobject-devel

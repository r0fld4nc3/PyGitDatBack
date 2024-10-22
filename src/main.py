import sys
import argparse
import platform
from threading import Event
import gi
gi.require_version("AyatanaAppIndicator3", "0.1")
from pystray import Icon, MenuItem, Menu
from PIL import Image, ImageDraw

from log import create_logger, reset_log_file
from conf_globals import G_LOG_LEVEL
from ui import GitDatBackUI

logger = create_logger("src.main", G_LOG_LEVEL)

stop_event = Event()

def stop_background_job():
    logger.info("Stopping background programme.")
    stop_event.set()
    sys.exit()

def create_tray_image():
    image = Image.new("RGBA", (64, 64), (255, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.ellipse((0, 0, 64, 64), fill="red")
    return image

def create_tray_icon():
    icon_image = create_tray_image()
    
    menu = Menu(MenuItem("Quit", lambda icon, item: stop_background_job()))

    tray_icon = Icon("MyApp", icon_image, menu=menu)
    tray_icon.run_detached()

def start_background_task():
    while not stop_event.is_set():
        logger.info("Running background job...")
        stop_event.wait(5)

def main():
    parser = argparse.ArgumentParser(description="Main entry point for the application.")
    parser.add_argument("--no-ui", action="store_true", help="Launch the GUI-less programme to system tray.")
    parser.add_argument('-s', '--stop', action="store_true", help="Stop the background job")

    args = parser.parse_args()

    if args.stop:
        logger.info("Stopping application")
        sys.exit(0)

    if args.no_ui:
        logger.info("Launching to system tray")
        create_tray_icon()
    else:
        logger.info("Launching GUI application")
        launch_ui()

def launch_ui() -> bool:
    reset_log_file()
    app = GitDatBackUI()
    app.show()

if __name__ == "__main__":
    main()

# system requirements linux: libayatana-appindicator-devel, libayatana-indicator3-devel, libayatana-appindicator3-devel, typelib-1_0-AyatanaAppIndicator-0_1
# python requirements: gi, pygobject, python311-gobject-devel, python312-gobject-devel

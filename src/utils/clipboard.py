import logging
import os
import shutil
import subprocess

from .path_helpers import os_darwin, os_linux, os_windows, system

log = logging.getLogger(__name__)


def _get_clipboard_command() -> list[str] | None:
    """The command that copies its standard input to the clipboard on this OS, or `None` if none is installed."""
    if os_darwin():
        candidates = [["pbcopy"]]
    elif os_windows():
        candidates = [["clip"]]
    elif os_linux():
        candidates = [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        if os.environ.get("WAYLAND_DISPLAY"):
            # Wayland sessions: wl-copy first, the X11 tools only work through XWayland
            candidates.insert(0, ["wl-copy"])
    else:
        candidates = []

    for command in candidates:
        if shutil.which(command[0]):
            return command

    return None


def send_to_clipboard(content: str) -> bool:
    """Copy text to the system clipboard. Returns `True` on success."""
    command = _get_clipboard_command()

    if not command:
        log.warning(f"No clipboard tool found for {system()}. On Linux install xclip, xsel or wl-clipboard.")
        return False

    # clip.exe only reads non-ASCII text correctly as UTF-16 with a byte order mark
    data = str(content).encode("utf-16" if os_windows() else "utf-8")

    try:
        # The text goes in through stdin. Output is discarded rather than captured: xclip, xsel and
        # wl-copy keep running in the background to own the clipboard, and waiting on their output
        # would block until something else is copied.
        subprocess.run(command, input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5)
    except (subprocess.SubprocessError, OSError) as e:
        log.error(f"Unable to copy to clipboard with {command[0]}: {e}")
        return False

    log.info("Contents copied to clipboard")
    return True

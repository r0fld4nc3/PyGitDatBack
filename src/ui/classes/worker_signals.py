from PySide6.QtCore import QObject, Signal

class WorkerSignals(QObject):
    finished = Signal(str)      # repo url
    error = Signal(str, str)    # repo url, error message
    status = Signal(str, str)   # repo url, status text

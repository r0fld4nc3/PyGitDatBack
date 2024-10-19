import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QLabel, QListWidget, QListWidgetItem
)
from PySide6.QtCore import QDateTime

from log import create_logger
from conf_globals import G_LOG_LEVEL
from libgit import Repository


logger = create_logger("src.ui.ui_main", G_LOG_LEVEL)


class UrlEntry(QWidget):
    def __init__(self, url, remove_callback):
        super().__init__()

        self.layout = QHBoxLayout()

        self.checkbox = QCheckBox()

        self.url_label = QLabel(url)
        
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.timestamp_label = QLabel(timestamp)

        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.handle_remove)

        self.layout.addWidget(self.checkbox)
        self.layout.addWidget(self.url_label)
        self.layout.addWidget(self.timestamp_label)
        self.layout.addWidget(self.remove_button)

        self.setLayout(self.layout)

        # Store the callback to remove the entry
        self.remove_callback = remove_callback

    def handle_remove(self):
        self.remove_callback(self)


class GitDatBackUI(QWidget):
    def __init__(self):
        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()

        super().__init__()

        # Main layout
        self.main_layout = QVBoxLayout()

        # Widgets
        self.input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL")
        self.submit_button = QPushButton("Submit")
        self.submit_button.clicked.connect(self.add_entry)
        self.entry_list = QListWidget()
        self.pull_button = QPushButton("Pull Repos")

        self.input_layout.addWidget(self.url_input)
        self.input_layout.addWidget(self.submit_button)

        self.main_layout.addLayout(self.input_layout)
        self.main_layout.addWidget(self.entry_list)
        self.main_layout.addWidget(self.pull_button)

        self.setLayout(self.main_layout)
        self.setWindowTitle("Git Dat Back")

    def add_entry(self):
        url = self.url_input.text()

        if not url:
            return
        
        entry = UrlEntry(url, self.remove_entry)

        list_item = QListWidgetItem(self.entry_list)

        # Set the size of the item according to the widget
        list_item.setSizeHint(entry.sizeHint())

        # Add the custom widget to the QListWidget
        self.entry_list.setItemWidget(list_item, entry)

        # Store the reference to the list item inside the widget (for removal)
        entry.list_item = list_item

        self.url_input.clear()

    def remove_entry(self, entry_widget):
        list_item = entry_widget.list_item
        self.entry_list.takeItem(self.entry_list.row(list_item))

    def pull_repos(self):
        logger.warning("Pull Repos lacks implementation.")

    def show(self):
        super().show()

        sys.exit(self.app.exec())

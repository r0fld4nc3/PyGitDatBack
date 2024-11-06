from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QCheckBox, QLabel, QDialog, QTableWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QSize

from conf_globals import G_LOG_LEVEL
from log import create_logger

from . import AlignedWidget

logger = create_logger(__name__, G_LOG_LEVEL)


class TableBranchEntry(QWidget):
    def __init__(self, branch_name: str):
        super().__init__()

        self.pull_checkbox = QCheckBox()
        self.pull_checkbox_widget = AlignedWidget(self.pull_checkbox)
        self.pull_checkbox.setChecked(True) # Default pull to true
        
        self.branch_name_label = QLabel(branch_name.strip())
        self.branch_name_widget = AlignedWidget(self.branch_name_label, alignment=Qt.AlignLeft, margins=(5, 0, 0, 0))

        self.branches_label = QLabel()
        self.branches_label_widget = AlignedWidget(self.branches_label, alignment=Qt.AlignLeft, margins=(5, 0, 0, 0))

        layout = QHBoxLayout()
        layout.addWidget(self.pull_checkbox_widget)
        layout.addWidget(self.branch_name_label)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.setLayout(layout)

    def get_pull(self) -> bool:
        return self.pull_checkbox.isChecked()

    def set_pull(self, state: bool):
        self.pull_checkbox.setChecked(state)

    def get_name(self) -> str:
        return self.branch_name_label.text()

    def set_name(self, new_name: str):
        former_url = self.branch_name_label.text()
        self.branch_name_label.setText(new_name)
        logger.info(f"Set new URL: {new_name} for former {former_url}")


class TableBranchView(QDialog):
    def __init__(self, parent=None, branches=[]):
        super().__init__(parent)

        self.setWindowTitle("Branches")
        self.setModal(True) # Blocks interaction with parent window
        size_add = len(branches) * 10 if len(branches) >= 15 else 0
        if size_add > 1000:
            size_add = 1000
        logger.debug(f"{size_add=}")
        self.resize(QSize(350, 200 + size_add))

        self.entries: list[TableBranchEntry] = []

        # Main Table
        self.entry_table = QTableWidget(0, 2)
        self.entry_table.setHorizontalHeaderLabels(["Pull", "Branch"])
        self.entry_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # self.entry_table.cellDoubleClicked.connect(self.handle_cell_doubleclick)
        self.entry_table.horizontalHeader().setStretchLastSection(True)
        self.entry_table.setColumnWidth(0, 40)
        self.entry_table.setColumnWidth(1, 100)
        # Selection behaviour
        self.entry_table.setSelectionBehavior(QTableWidget.SelectRows) # Select full rows

        main_layout = QVBoxLayout()

        # Add to main layout
        main_layout.addWidget(self.entry_table)

        self.setLayout(main_layout)

        for branch in branches:
            self.add_to_table(branch)

    def add_to_table(self, branch_name):
        entry = TableBranchEntry(branch_name)

        row_pos = self.entry_table.rowCount()
        self.entry_table.insertRow(row_pos)

        self.entry_table.setCellWidget(row_pos, 0, entry.pull_checkbox_widget)
        self.entry_table.setCellWidget(row_pos, 1, entry.branch_name_label)

        # Handle pull checkbox
        entry.set_pull(False)

        self.entries.append(entry)

        logger.info(f"Added entry: {branch_name}")

        return entry

    def get_selected_values(self):
        return
    
    def accept(self):
        super().accept()

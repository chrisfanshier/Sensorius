"""
LogWidget - Reusable log output text area.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QGroupBox, QPushButton, QApplication


class LogWidget(QWidget):
    """A collapsible log output text area."""

    def __init__(self, title: str = "Log", max_height: int = 200, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.group = QGroupBox(title)
        group_layout = QVBoxLayout()

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumHeight(max_height)
        group_layout.addWidget(self.text_edit)

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.text_edit.clear)
        group_layout.addWidget(clear_btn)

        self.group.setLayout(group_layout)
        layout.addWidget(self.group)

    def log(self, message: str):
        """Append a message to the log."""
        self.text_edit.append(message)
        self.text_edit.verticalScrollBar().setValue(
            self.text_edit.verticalScrollBar().maximum()
        )
        QApplication.processEvents()

    def clear(self):
        self.text_edit.clear()

"""
SelectionControls - Reusable selection toggle + info display widget.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QGroupBox,
)
from PySide6.QtCore import Signal


class SelectionControls(QWidget):
    """
    Reusable selection mode toggle and info display.
    
    Signals:
        selection_mode_changed(bool): Emitted when selection mode is toggled.
        clear_requested: Emitted when clear button is clicked.
    """

    selection_mode_changed = Signal(bool)
    clear_requested = Signal()

    def __init__(self, title: str = "Selection", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox(title)
        group_layout = QVBoxLayout()

        # Toggle button
        self.toggle_btn = QPushButton("Enable Selection Mode")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._on_toggled)
        self.toggle_btn.setStyleSheet(
            "QPushButton:checked { background-color: #4CAF50; color: white; font-weight: bold; }"
        )
        group_layout.addWidget(self.toggle_btn)

        # Help text
        help_label = QLabel(
            "Enable Selection Mode, then double-click\non plot to start/end selection"
        )
        help_label.setStyleSheet("QLabel { color: blue; font-style: italic; }")
        help_label.setWordWrap(True)
        group_layout.addWidget(help_label)

        # Selection info
        self.info_label = QLabel("No selection")
        self.info_label.setWordWrap(True)
        group_layout.addWidget(self.info_label)

        # Clear button
        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(self.clear_requested.emit)
        group_layout.addWidget(clear_btn)

        group.setLayout(group_layout)
        layout.addWidget(group)

    def update_selection_info(self, start_idx: int, end_idx: int, extra: str = ''):
        """Update the selection info display."""
        n_points = end_idx - start_idx + 1
        text = f"Selected:\nRows {start_idx} to {end_idx}\n({n_points} points)"
        if extra:
            text += f"\n{extra}"
        self.info_label.setText(text)

    def clear_info(self):
        self.info_label.setText("No selection")

    @property
    def is_enabled(self) -> bool:
        return self.toggle_btn.isChecked()

    def _on_toggled(self):
        enabled = self.toggle_btn.isChecked()
        self.toggle_btn.setText(
            "Disable Selection Mode" if enabled else "Enable Selection Mode"
        )
        self.selection_mode_changed.emit(enabled)

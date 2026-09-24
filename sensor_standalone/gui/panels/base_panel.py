"""
Base class for all mode panels.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from PySide6.QtCore import Signal


class BaseModePanel(QWidget):
    """
    Base class for mode-specific control panels.
    
    Each panel sits inside a QScrollArea and provides:
    - on_mode_activated(): called when the mode becomes active
    - on_mode_deactivated(): called when leaving the mode
    - log_message signal for sending messages to the log
    """

    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Wrap in scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMinimumWidth(380)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setSpacing(8)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(self._scroll)

    def _finish_layout(self):
        """Call at end of subclass __init__ to finalize the scroll area."""
        self._layout.addStretch()
        self._scroll.setWidget(self._container)

    def on_mode_activated(self):
        """Called when this mode becomes active. Override in subclasses."""
        pass

    def on_mode_deactivated(self):
        """Called when leaving this mode. Override in subclasses."""
        pass

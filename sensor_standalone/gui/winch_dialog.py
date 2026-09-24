"""Winch file import dialog.

Qt port of the Streamlit winch ingestion flow (``add_data_file.py`` /
``add_winch_data.py``): pick a ship format preset, adjust delimiter / header
lines / column names / datetime code, preview the raw rows, then *test-parse*
the full file.  Saving is only enabled after a successful test parse, and the
test uses the exact same parser (:func:`parse_winch_dat`) that the viewer
uses at load time, so what you preview is what you get.
"""
import ast

import pandas as pd
from pyqtgraph.Qt import QtWidgets, QtCore

from ..formats import WINCH_FORMATS
from ..persistence import file_parsers as fp

_DELIMITER_OPTIONS = [
    ("Comma (,)", ","),
    ("Tab (\\t)", "\t"),
    ("Pipe (|)", "|"),
    ("Space ( )", " "),
    ("Semicolon (;)", ";"),
    ("Whitespace (\\s+)", r"\s+"),
]

_PREVIEW_ROWS = 20


def _fill_table(table: QtWidgets.QTableWidget, df: pd.DataFrame):
    table.clear()
    table.setRowCount(min(len(df), _PREVIEW_ROWS))
    table.setColumnCount(len(df.columns))
    table.setHorizontalHeaderLabels([str(c) for c in df.columns])
    for i in range(table.rowCount()):
        for j, col in enumerate(df.columns):
            table.setItem(i, j, QtWidgets.QTableWidgetItem(str(df.iloc[i][col])))
    table.resizeColumnsToContents()


class WinchImportDialog(QtWidgets.QDialog):
    """Configure parsing settings for one winch file.

    After ``exec()`` returns Accepted, read ``self.settings`` (dict ready for
    the database), ``self.start_time`` / ``self.end_time`` and ``self.notes``.
    """

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.settings = None
        self.start_time = None
        self.end_time = None
        self.notes = ""
        self._parsed_df = None
        self._raw_column_count = None

        self.setWindowTitle(f"Import Winch File — {file_path}")
        self.resize(950, 750)
        self._build_ui()
        self._on_format_changed(self.format_combo.currentText())

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Format / delimiter / header controls
        form_row = QtWidgets.QHBoxLayout()
        form_row.addWidget(QtWidgets.QLabel("Ship format:"))
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(list(WINCH_FORMATS.keys()))
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        form_row.addWidget(self.format_combo)

        form_row.addSpacing(15)
        form_row.addWidget(QtWidgets.QLabel("Header lines:"))
        self.header_spin = QtWidgets.QSpinBox()
        self.header_spin.setRange(0, 1000)
        self.header_spin.valueChanged.connect(self._refresh_raw_preview)
        form_row.addWidget(self.header_spin)

        form_row.addSpacing(15)
        form_row.addWidget(QtWidgets.QLabel("Delimiter:"))
        self.delimiter_combo = QtWidgets.QComboBox()
        self.delimiter_combo.addItems([label for label, _ in _DELIMITER_OPTIONS])
        self.delimiter_combo.currentIndexChanged.connect(self._refresh_raw_preview)
        form_row.addWidget(self.delimiter_combo)

        form_row.addWidget(QtWidgets.QLabel("Custom:"))
        self.custom_delim_edit = QtWidgets.QLineEdit()
        self.custom_delim_edit.setMaximumWidth(60)
        self.custom_delim_edit.setPlaceholderText("(opt.)")
        self.custom_delim_edit.textChanged.connect(self._refresh_raw_preview)
        form_row.addWidget(self.custom_delim_edit)
        form_row.addStretch()
        layout.addLayout(form_row)

        # Raw preview
        raw_label = QtWidgets.QLabel(f"Raw preview (first {_PREVIEW_ROWS} rows):")
        raw_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(raw_label)
        self.raw_table = QtWidgets.QTableWidget()
        self.raw_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.raw_table, stretch=2)

        # Column names + datetime code
        cfg_row = QtWidgets.QHBoxLayout()

        col_box = QtWidgets.QVBoxLayout()
        col_box.addWidget(QtWidgets.QLabel("Column names (Python list):"))
        self.columns_edit = QtWidgets.QPlainTextEdit()
        self.columns_edit.setMaximumHeight(70)
        col_box.addWidget(self.columns_edit)
        cfg_row.addLayout(col_box)

        dt_box = QtWidgets.QVBoxLayout()
        dt_box.addWidget(QtWidgets.QLabel(
            "Datetime code (expression using df and pd, e.g. "
            "pd.to_datetime(df[['year','month','day','hour','minute','second']])):"
        ))
        self.datetime_edit = QtWidgets.QPlainTextEdit()
        self.datetime_edit.setMaximumHeight(70)
        dt_box.addWidget(self.datetime_edit)
        cfg_row.addLayout(dt_box)

        layout.addLayout(cfg_row)

        # Any change to columns / datetime code invalidates a previous test.
        self.columns_edit.textChanged.connect(self._invalidate_test)
        self.datetime_edit.textChanged.connect(self._invalidate_test)

        # Test parse
        test_row = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("Test Parse")
        self.test_btn.setStyleSheet("font-weight: bold; padding: 5px 15px;")
        self.test_btn.clicked.connect(self._test_parse)
        test_row.addWidget(self.test_btn)
        self.result_label = QtWidgets.QLabel("Not tested yet — a successful test parse is required before saving.")
        self.result_label.setStyleSheet("color: gray;")
        test_row.addWidget(self.result_label)
        test_row.addStretch()
        layout.addLayout(test_row)

        parsed_label = QtWidgets.QLabel("Parsed preview:")
        parsed_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(parsed_label)
        self.parsed_table = QtWidgets.QTableWidget()
        self.parsed_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.parsed_table, stretch=2)

        # Notes
        notes_row = QtWidgets.QHBoxLayout()
        notes_row.addWidget(QtWidgets.QLabel("Notes:"))
        self.notes_edit = QtWidgets.QLineEdit()
        self.notes_edit.setPlaceholderText("Optional notes about this winch file")
        notes_row.addWidget(self.notes_edit)
        layout.addLayout(notes_row)

        # Buttons
        self.btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        self.btn_box.button(QtWidgets.QDialogButtonBox.Save).setEnabled(False)
        self.btn_box.accepted.connect(self._on_save)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)

    # ── behaviour ─────────────────────────────────────────────────────

    def _current_delimiter(self) -> str:
        custom = self.custom_delim_edit.text()
        if custom:
            return custom
        return _DELIMITER_OPTIONS[self.delimiter_combo.currentIndex()][1]

    def _invalidate_test(self):
        """Any settings change invalidates a previous successful test."""
        self._parsed_df = None
        self.start_time = None
        self.end_time = None
        self.btn_box.button(QtWidgets.QDialogButtonBox.Save).setEnabled(False)
        self.result_label.setText("Settings changed — run Test Parse again before saving.")
        self.result_label.setStyleSheet("color: gray;")

    def _on_format_changed(self, format_name: str):
        preset = WINCH_FORMATS.get(format_name, WINCH_FORMATS["Custom Format"])

        self.header_spin.blockSignals(True)
        self.header_spin.setValue(preset.get("header_lines", 0))
        self.header_spin.blockSignals(False)

        preset_delim = preset.get("delimiter", ",")
        # Presets store "\\s+" (escaped); the option table stores r"\s+".
        normalized = preset_delim.replace("\\\\", "\\")
        idx = 0
        for i, (_, value) in enumerate(_DELIMITER_OPTIONS):
            if value == normalized or value == preset_delim:
                idx = i
                break
        self.delimiter_combo.blockSignals(True)
        self.delimiter_combo.setCurrentIndex(idx)
        self.delimiter_combo.blockSignals(False)
        self.custom_delim_edit.blockSignals(True)
        self.custom_delim_edit.clear()
        self.custom_delim_edit.blockSignals(False)

        self.columns_edit.setPlainText(str(preset.get("columns", [])))
        self.datetime_edit.setPlainText(preset.get("datetime_code", ""))

        self._refresh_raw_preview()

    def _refresh_raw_preview(self, *args):
        self._invalidate_test()
        delimiter = self._current_delimiter()
        try:
            df_preview = pd.read_csv(
                self.file_path,
                sep=delimiter,
                skiprows=self.header_spin.value(),
                nrows=_PREVIEW_ROWS,
                header=None,
                on_bad_lines="skip",
                encoding="latin1",
                engine="python",
            )
            _fill_table(self.raw_table, df_preview)
            self._raw_column_count = len(df_preview.columns)
        except Exception as exc:  # noqa: BLE001
            self.raw_table.clear()
            self.raw_table.setRowCount(0)
            self.raw_table.setColumnCount(1)
            self.raw_table.setHorizontalHeaderLabels(["Error"])
            self.raw_table.setRowCount(1)
            self.raw_table.setItem(0, 0, QtWidgets.QTableWidgetItem(str(exc)))
            self._raw_column_count = None

    def _read_columns(self):
        text = self.columns_edit.toPlainText().strip()
        if not text:
            return []
        try:
            columns = ast.literal_eval(text)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(f"Column names are not a valid Python list: {exc}")
        if not isinstance(columns, (list, tuple)) or not all(isinstance(c, str) for c in columns):
            raise ValueError("Column names must be a list of strings.")
        return list(columns)

    def _build_settings(self) -> dict:
        columns = self._read_columns()
        if not columns:
            raise ValueError("Please specify column names.")
        datetime_code = self.datetime_edit.toPlainText().strip()
        if not datetime_code:
            raise ValueError("Please specify the datetime creation code.")

        settings = {
            "delimiter": self._current_delimiter(),
            "header_lines": self.header_spin.value(),
            "columns": columns,
            "datetime_code": datetime_code,
        }
        preset = WINCH_FORMATS.get(self.format_combo.currentText(), {})
        if "numeric_columns" in preset:
            settings["numeric_columns"] = preset["numeric_columns"]
        return settings

    def _test_parse(self):
        try:
            settings = self._build_settings()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Settings", str(exc))
            return

        if self._raw_column_count is not None and len(settings["columns"]) != self._raw_column_count:
            QtWidgets.QMessageBox.warning(
                self, "Column Mismatch",
                f"The file preview has {self._raw_column_count} columns but "
                f"{len(settings['columns'])} column names were given.\n\n"
                "Adjust the column names (or delimiter / header lines) and try again."
            )
            return

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            df = fp.parse_winch_dat(self.file_path, settings)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if df is None or "datetime" not in df.columns or df["datetime"].dropna().empty:
            self._invalidate_test()
            self.result_label.setText("❌ Parse failed — check delimiter, columns and datetime code.")
            self.result_label.setStyleSheet("color: red;")
            return

        self._parsed_df = df
        self.start_time = df["datetime"].min()
        self.end_time = df["datetime"].max()

        _fill_table(self.parsed_table, df.head(_PREVIEW_ROWS))
        self.result_label.setText(
            f"✓ {len(df):,} records | {self.start_time} → {self.end_time}"
        )
        self.result_label.setStyleSheet("color: green; font-weight: bold;")
        self.btn_box.button(QtWidgets.QDialogButtonBox.Save).setEnabled(True)

    def _on_save(self):
        if self._parsed_df is None:
            QtWidgets.QMessageBox.warning(
                self, "Test Required", "Run a successful Test Parse before saving."
            )
            return
        try:
            settings = self._build_settings()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Settings", str(exc))
            return

        settings["total_records"] = len(self._parsed_df)
        settings["duration_hours"] = (
            (self.end_time - self.start_time).total_seconds() / 3600
        )
        self.settings = settings
        self.notes = self.notes_edit.text().strip()
        self.accept()

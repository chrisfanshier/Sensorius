"""Main window: project management + Data Manager / Analysis tabs."""
import os
import sys
import traceback

from pyqtgraph.Qt import QtWidgets, QtCore

from .. import APP_NAME
from ..persistence.project import ProjectStore, DB_FILENAME
from .data_manager import DataManagerPage
from .analysis_window import AnalysisWindow

_MAX_RECENT = 8


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1600, 1000)

        self.store = None
        self.settings = QtCore.QSettings(APP_NAME, APP_NAME)

        self.tabs = QtWidgets.QTabWidget()
        self.data_manager = DataManagerPage()
        self.analysis = AnalysisWindow()
        self.tabs.addTab(self.data_manager, "📂 Data Manager")
        self.tabs.addTab(self.analysis, "📈 Analysis")
        self.setCentralWidget(self.tabs)

        self.data_manager.dataChanged.connect(
            lambda: self.analysis.refresh_cruises(keep_selection=True)
        )

        self._create_menu()

        last = self.settings.value("last_project", "")
        if last and os.path.isdir(last):
            self._open_store(last)
        else:
            self.statusBar().showMessage(
                "No project open — use File ▸ New Project… or Open Project…"
            )

    def _create_menu(self):
        menu = self.menuBar().addMenu("File")

        menu.addAction("New Project…", self.new_project)
        menu.addAction("Open Project…", self.open_project)

        self.recent_menu = menu.addMenu("Recent Projects")
        self._rebuild_recent_menu()

        menu.addSeparator()
        menu.addAction("Exit", self.close)

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        recent = self._recent_projects()
        self.recent_menu.setEnabled(bool(recent))
        for path in recent:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: self._open_store(p))

    def _recent_projects(self) -> list:
        recent = self.settings.value("recent_projects", [])
        if isinstance(recent, str):
            recent = [recent] if recent else []
        return [p for p in recent if os.path.isdir(p)]

    def _remember_project(self, path: str):
        recent = self._recent_projects()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self.settings.setValue("recent_projects", recent[:_MAX_RECENT])
        self.settings.setValue("last_project", path)
        self._rebuild_recent_menu()

    def new_project(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select (or create) a folder for the new project"
        )
        if not path:
            return
        contents = [f for f in os.listdir(path) if not f.startswith(".")]
        if contents and DB_FILENAME not in contents:
            reply = QtWidgets.QMessageBox.question(
                self, "Folder Not Empty",
                "The folder is not empty and does not look like an existing project.\n"
                "Create a project in it anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._open_store(path)

    def open_project(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Open Project Folder")
        if not path:
            return
        if not os.path.isfile(os.path.join(path, DB_FILENAME)):
            reply = QtWidgets.QMessageBox.question(
                self, "Create Project?",
                f"No {DB_FILENAME} found. Create a new project here?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._open_store(path)

    def _open_store(self, path: str):
        if self.store:
            self.store.close()
        self.store = ProjectStore(path)
        self.data_manager.set_store(self.store)
        self.analysis.set_store(self.store)
        self._remember_project(path)
        self.statusBar().showMessage(f"Project: {path}")
        self.setWindowTitle(f"{APP_NAME} — {os.path.basename(path)}")


def install_excepthook():
  def handler(exc_type, exc_value, exc_tb):
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log_path = os.path.join(os.path.expanduser("~"), "sensorius_error.log")
    try:
      with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    except OSError:
      log_path = "(could not write log)"
    try:
      app = QtWidgets.QApplication.instance()
      if app:
        QtWidgets.QMessageBox.critical(
          None, f"{APP_NAME} Error",
          f"An unexpected error occurred.\n\nDetails saved to:\n{log_path}\n\n{text[:2000]}",
        )
    except Exception:
      pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)
  sys.excepthook = handler

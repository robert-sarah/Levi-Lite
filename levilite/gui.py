from __future__ import annotations

import os
import sys
import traceback

from levilite.db import Database

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except Exception as e:  # pragma: no cover
    QtCore = None  # type: ignore[assignment]
    QtGui = None  # type: ignore[assignment]
    QtWidgets = None  # type: ignore[assignment]
    _PYQT_IMPORT_ERROR = e
else:
    _PYQT_IMPORT_ERROR = None


class MainWindow(QtWidgets.QMainWindow):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Levi Lite")
        self.resize(1300, 780)

        self._db_path: str = os.path.abspath("levilite.db")
        self._db: Database | None = None

        self._build_actions()
        self._build_menus_and_toolbar()
        self.statusBar().showMessage(f"Database: (not open) • Default: {self._db_path}")

        self._build_query_history_dock()

        # Main layout: left schema tree, right editor/results/logs
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)

        # Left: schema browser
        self.schema_tree = QtWidgets.QTreeWidget()
        self.schema_tree.setHeaderLabels(["Schemas"])
        self.schema_tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.schema_tree.customContextMenuRequested.connect(self._schema_context_menu)
        self.schema_tree.itemDoubleClicked.connect(self._schema_item_activated)
        main_splitter.addWidget(self.schema_tree)

        # Right side container
        right = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        main_splitter.addWidget(right)

        # Top right: editor + buttons
        editor_box = QtWidgets.QWidget()
        editor_layout = QtWidgets.QVBoxLayout(editor_box)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        right.addWidget(editor_box)

        self.sql_edit = QtWidgets.QPlainTextEdit()
        self.sql_edit.setPlaceholderText(
            "Write SQL here…\n\nExamples:\n"
            "CREATE TABLE users (id INT, name TEXT);\n"
            "INSERT INTO users (id, name) VALUES (1, \"Alice\");\n"
            "SELECT * FROM users;\n"
            "UPDATE users SET name = \"Bob\" WHERE id = 1;\n"
            "DELETE FROM users WHERE id = 1;\n"
            "DROP TABLE IF EXISTS users;\n"
        )
        font = QtGui.QFont("Consolas")
        font.setPointSize(11)
        self.sql_edit.setFont(font)
        self.sql_edit.textChanged.connect(self._update_state)
        editor_layout.addWidget(self.sql_edit, 1)

        btn_row = QtWidgets.QHBoxLayout()
        editor_layout.addLayout(btn_row)
        self.execute_btn = QtWidgets.QPushButton("Run (Ctrl+Enter)")
        self.execute_btn.clicked.connect(self._execute_sql)
        btn_row.addWidget(self.execute_btn)
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.clicked.connect(self.sql_edit.clear)
        btn_row.addWidget(self.clear_btn)
        self.clear_log_btn = QtWidgets.QPushButton("Clear Console")
        self.clear_log_btn.clicked.connect(self._clear_console)
        btn_row.addWidget(self.clear_log_btn)
        btn_row.addStretch(1)

        # Middle right: results (Excel-like grid)
        results_box = QtWidgets.QWidget()
        results_layout = QtWidgets.QVBoxLayout(results_box)
        results_layout.setContentsMargins(8, 8, 8, 8)
        right.addWidget(results_box)

        results_layout.addWidget(QtWidgets.QLabel("Results"), 0)
        self.results_tabs = QtWidgets.QTabWidget()
        results_layout.addWidget(self.results_tabs, 1)

        self._result_tables: list[QtWidgets.QTableWidget] = []

        # Bottom right: logs
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Logs…")
        right.addWidget(self.log)

        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 4)
        right.setStretchFactor(0, 2)
        right.setStretchFactor(1, 3)
        right.setStretchFactor(2, 1)

        # Shortcuts
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self, activated=self._execute_sql)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Enter"), self, activated=self._execute_sql)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+O"), self, activated=self._action_open_db.trigger)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+W"), self, activated=self._action_close_db.trigger)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+L"), self, activated=self._clear_console)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+S"), self, activated=self._action_save_sql.trigger)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Shift+O"), self, activated=self._action_open_sql.trigger)

        self._update_state()

    def _append_log(self, msg: str) -> None:
        self.log.appendPlainText(msg)

    def _update_state(self) -> None:
        is_open = self._db is not None
        has_sql = bool(self.sql_edit.toPlainText().strip())
        # Run should be clickable as long as user typed SQL.
        self.execute_btn.setEnabled(has_sql)
        self._action_close_db.setEnabled(is_open)
        self._action_open_db.setEnabled(not is_open)
        self._action_run.setEnabled(has_sql)
        self._action_refresh.setEnabled(is_open)

    def _build_actions(self) -> None:
        self._action_open_db = QtWidgets.QAction("Open Database…", self)
        self._action_open_db.triggered.connect(self._open_db_dialog)

        self._action_close_db = QtWidgets.QAction("Close Database", self)
        self._action_close_db.triggered.connect(self._close_db)

        self._action_open_sql = QtWidgets.QAction("Open SQL Script…", self)
        self._action_open_sql.triggered.connect(self._open_sql_dialog)

        self._action_save_sql = QtWidgets.QAction("Save SQL Script…", self)
        self._action_save_sql.triggered.connect(self._save_sql_dialog)

        self._action_exit = QtWidgets.QAction("Exit", self)
        self._action_exit.triggered.connect(self.close)

        self._action_run = QtWidgets.QAction("Run", self)
        self._action_run.triggered.connect(self._execute_sql)

        self._action_refresh = QtWidgets.QAction("Refresh Schemas", self)
        self._action_refresh.triggered.connect(self._refresh_schema_tree)

        self._action_copy = QtWidgets.QAction("Copy", self)
        self._action_copy.triggered.connect(self._copy_selection_to_clipboard)

        self._action_clear_console = QtWidgets.QAction("Clear Console", self)
        self._action_clear_console.triggered.connect(self._clear_console)

        self._action_export_csv = QtWidgets.QAction("Export Current Result to CSV…", self)
        self._action_export_csv.triggered.connect(self._export_current_result_csv)

    def _build_menus_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self._action_open_db)
        file_menu.addAction(self._action_close_db)
        file_menu.addSeparator()
        file_menu.addAction(self._action_open_sql)
        file_menu.addAction(self._action_save_sql)
        file_menu.addSeparator()
        file_menu.addAction(self._action_export_csv)
        file_menu.addSeparator()
        file_menu.addAction(self._action_exit)

        query_menu = self.menuBar().addMenu("Query")
        query_menu.addAction(self._action_run)
        query_menu.addAction(self._action_refresh)

        edit_menu = self.menuBar().addMenu("Edit")
        edit_menu.addAction(self._action_copy)
        edit_menu.addAction(self._action_clear_console)

        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.addAction(self._action_open_db)
        tb.addAction(self._action_close_db)
        tb.addSeparator()
        tb.addAction(self._action_run)
        tb.addAction(self._action_refresh)
        tb.addSeparator()
        tb.addAction(self._action_clear_console)

    def _open_db_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Open database file",
            self._db_path,
            "Levi Lite DB (*.db);;All files (*.*)",
        )
        if not path:
            return
        self._open_db(path)

    def _open_db(self, path: str) -> None:
        if self._db is not None:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._db = Database.open(path)
            self._db_path = path
            self._append_log(f"Opened: {path}")
            self.statusBar().showMessage(f"Database: {path}")
            self._refresh_schema_tree()
        except Exception:
            self._append_log("Open failed:\n" + traceback.format_exc())
            self._db = None
            self.statusBar().showMessage("Database: (not open)")
        self._update_state()

    def _close_db(self) -> None:
        if self._db is None:
            return
        try:
            self._db.close()
            self._append_log("Closed.")
        except Exception:
            self._append_log("Close failed:\n" + traceback.format_exc())
        finally:
            self._db = None
            self.schema_tree.clear()
            self._clear_results_tabs()
            self.statusBar().showMessage("Database: (not open)")
        self._update_state()

    def _execute_sql(self) -> None:
        if self._db is None:
            # Auto-open default database file (same behavior as "workbench" reconnect)
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
                self._db = Database.open(self._db_path)
                self.statusBar().showMessage(f"Database: {self._db_path}")
                self._append_log(f"Opened: {self._db_path}")
                self._refresh_schema_tree()
            except Exception:
                self._append_log("Open failed:\n" + traceback.format_exc())
                self._db = None
                self._update_state()
                return
        sql = self.sql_edit.toPlainText().strip()
        if not sql:
            return
        if not sql.endswith(";"):
            sql += ";"
        try:
            self._clear_results_tabs()
            results = self._db.execute_script(sql)
            if not results:
                self._append_log("OK.")
                self._refresh_schema_tree()
                self._push_history(sql)
                return
            for i, (cols, rows) in enumerate(results, start=1):
                self._add_result_tab(title=f"Result {i}", cols=cols, rows=rows)
                self._append_log(f"OK ({len(rows)} row(s)) for result set {i}.")
            self._refresh_schema_tree()
            self._push_history(sql)
        except Exception:
            self._append_log("Execution failed:\n" + traceback.format_exc())
            self._push_history(sql)

    def _clear_results_tabs(self) -> None:
        self._result_tables = []
        self.results_tabs.clear()

    def _add_result_tab(self, title: str, cols: list[str], rows: list[tuple[object, ...]]) -> None:
        table = QtWidgets.QTableWidget(0, 0)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectItems)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(True)  # row numbers like Excel
        table.horizontalHeader().setStretchLastSection(True)
        table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._results_context_menu)

        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(len(rows))
        for r_i, r in enumerate(rows):
            for c_i, v in enumerate(r):
                item = QtWidgets.QTableWidgetItem("" if v is None else str(v))
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                table.setItem(r_i, c_i, item)
        table.resizeColumnsToContents()

        self._result_tables.append(table)
        self.results_tabs.addTab(table, title)

    def _refresh_schema_tree(self) -> None:
        self.schema_tree.clear()
        if self._db is None:
            return
        try:
            dbs = self._db.show_databases()
            current = self._db.current_database()
            tables = self._db.list_tables()
        except Exception:
            self._append_log("Failed to refresh schema tree:\n" + traceback.format_exc())
            return

        for dbname in dbs:
            db_item = QtWidgets.QTreeWidgetItem([dbname])
            db_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("db", dbname))
            db_item.setExpanded(dbname == current)
            self.schema_tree.addTopLevelItem(db_item)
            if dbname == current:
                for t in tables:
                    item = QtWidgets.QTreeWidgetItem([t])
                    item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("table", t))
                    db_item.addChild(item)

    def _schema_context_menu(self, pos) -> None:
        item = self.schema_tree.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        menu.addAction(self._action_refresh)
        if item is not None:
            data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and len(data) == 2 and data[0] == "db":
                dbname = data[1]
                a_use = menu.addAction(f"USE {dbname}")
                act = menu.exec_(self.schema_tree.viewport().mapToGlobal(pos))
                if act == a_use:
                    self.sql_edit.setPlainText(f"USE {dbname};\nSHOW TABLES;")
                    self.sql_edit.setFocus()
                return
            if isinstance(data, tuple) and len(data) == 2 and data[0] == "table":
                table = data[1]
                a_select = menu.addAction(f"SELECT * FROM {table}")
                a_schema = menu.addAction(f"Show schema for {table}")
                act = menu.exec_(self.schema_tree.viewport().mapToGlobal(pos))
                if act == a_select:
                    self.sql_edit.setPlainText(f"SELECT * FROM {table};")
                    self.sql_edit.setFocus()
                elif act == a_schema:
                    if self._db is None:
                        return
                    self._append_log(self._db.schema(table) or "(unknown table)")
                return
        menu.exec_(self.schema_tree.viewport().mapToGlobal(pos))

    def _schema_item_activated(self, item, _column: int) -> None:
        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2 and data[0] == "db":
            dbname = data[1]
            self.sql_edit.setPlainText(f"USE {dbname};\nSHOW TABLES;")
            self.sql_edit.setFocus()
            return
        if isinstance(data, tuple) and len(data) == 2 and data[0] == "table":
            table = data[1]
            self.sql_edit.setPlainText(f"SELECT * FROM {table};")
            self.sql_edit.setFocus()

    def _results_context_menu(self, pos) -> None:
        menu = QtWidgets.QMenu(self)
        menu.addAction(self._action_copy)
        menu.addAction(self._action_export_csv)
        sender = self.sender()
        if isinstance(sender, QtWidgets.QTableWidget):
            menu.exec_(sender.viewport().mapToGlobal(pos))
        else:
            menu.exec_(self.results_tabs.mapToGlobal(pos))

    def _copy_selection_to_clipboard(self) -> None:
        table = None
        w = self.results_tabs.currentWidget()
        if isinstance(w, QtWidgets.QTableWidget):
            table = w
        if table is None:
            return
        sel = table.selectedRanges()
        if not sel:
            return
        r = sel[0]
        lines: list[str] = []
        for row in range(r.topRow(), r.bottomRow() + 1):
            vals: list[str] = []
            for col in range(r.leftColumn(), r.rightColumn() + 1):
                it = table.item(row, col)
                vals.append("" if it is None else it.text())
            lines.append("\t".join(vals))  # tab-separated, Excel-friendly
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def _clear_console(self) -> None:
        self.log.clear()

    # --- Query history (dock) ---
    def _build_query_history_dock(self) -> None:
        self._history: list[str] = []
        dock = QtWidgets.QDockWidget("History", self)
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.history_list = QtWidgets.QListWidget()
        self.history_list.itemDoubleClicked.connect(self._history_item_activated)
        dock.setWidget(self.history_list)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _push_history(self, sql: str) -> None:
        s = sql.strip()
        if not s:
            return
        # Keep last 200 entries
        self._history.append(s)
        if len(self._history) > 200:
            self._history = self._history[-200:]
        display = s.replace("\n", " ").strip()
        if len(display) > 120:
            display = display[:120] + "…"
        self.history_list.insertItem(0, display)
        self.history_list.setCurrentRow(0)

    def _history_item_activated(self, item) -> None:
        row = self.history_list.row(item)
        idx = len(self._history) - 1 - row
        if idx < 0 or idx >= len(self._history):
            return
        self.sql_edit.setPlainText(self._history[idx])
        self.sql_edit.setFocus()

    # --- File I/O for SQL scripts ---
    def _open_sql_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open SQL script", os.getcwd(), "SQL files (*.sql);;All files (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.sql_edit.setPlainText(f.read())
            self._append_log(f"Loaded SQL: {path}")
        except Exception:
            self._append_log("Failed to load SQL:\n" + traceback.format_exc())

    def _save_sql_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save SQL script", os.getcwd(), "SQL files (*.sql);;All files (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.sql_edit.toPlainText())
            self._append_log(f"Saved SQL: {path}")
        except Exception:
            self._append_log("Failed to save SQL:\n" + traceback.format_exc())

    # --- Export current result tab to CSV ---
    def _export_current_result_csv(self) -> None:
        w = self.results_tabs.currentWidget()
        if not isinstance(w, QtWidgets.QTableWidget):
            self._append_log("No result table to export.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export result to CSV", os.getcwd(), "CSV files (*.csv);;All files (*.*)"
        )
        if not path:
            return
        try:
            import csv

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                headers = [w.horizontalHeaderItem(i).text() for i in range(w.columnCount())]
                writer.writerow(headers)
                for r in range(w.rowCount()):
                    row = []
                    for c in range(w.columnCount()):
                        it = w.item(r, c)
                        row.append("" if it is None else it.text())
                    writer.writerow(row)
            self._append_log(f"Exported CSV: {path}")
        except Exception:
            self._append_log("CSV export failed:\n" + traceback.format_exc())


def main(argv: list[str] | None = None) -> int:
    _ = argv
    if _PYQT_IMPORT_ERROR is not None:
        print(
            "PyQt5 is not installed (or failed to import). Install it first:\n"
            "  pip install PyQt5\n\n"
            f"Import error: {_PYQT_IMPORT_ERROR}",
            file=sys.stderr,
        )
        return 1

    app = QtWidgets.QApplication(sys.argv)  # type: ignore[call-arg]
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())



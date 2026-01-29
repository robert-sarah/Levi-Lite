from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from levilite.catalog import Catalog
from levilite.execution.executor import Executor
from levilite.sql.parser import parse_sql
from levilite.sql.ast import Statement
from levilite.storage.dbfile import DBFile
from levilite.storage.wal import Wal


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]


class Database:
    """
    High-level Database facade.

    - Owns the DB file + WAL
    - Owns catalog metadata
    - Parses SQL and executes it
    """

    def __init__(self, *, base_dir: str, name: str, db: DBFile, wal: Wal, catalog: Catalog) -> None:
        self._base_dir = base_dir
        self._databases_dir = os.path.join(self._base_dir, "levilite_databases")
        os.makedirs(self._databases_dir, exist_ok=True)

        self._name = name
        self._db = db
        self._wal = wal
        self._catalog = catalog
        self._tx: dict[str, bytes] | None = None
        self._tx_wal: list[tuple[str, bytes]] | None = None
        self._executor = Executor(db=self, wal=self._wal, catalog=self._catalog)

    @classmethod
    def open(cls, path: str) -> "Database":
        base_dir = os.path.dirname(os.path.abspath(path)) or os.getcwd()
        # Name from file stem (best effort)
        fname = os.path.basename(path)
        name = os.path.splitext(fname)[0] if fname else "main"

        db = DBFile.open(path)
        wal = Wal.open(path + ".wal")
        catalog = Catalog.load(db)
        wal.recover_into(db)
        return cls(base_dir=base_dir, name=name, db=db, wal=wal, catalog=catalog)

    def close(self) -> None:
        if self._tx is not None:
            # Best-effort: rollback open tx on close
            self.rollback()
        self._catalog.flush(self._db)
        self._wal.close()
        self._db.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def list_tables(self) -> list[str]:
        return sorted(self._catalog.tables.keys())

    def current_database(self) -> str:
        return self._name

    @staticmethod
    def _validate_db_name(name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise ValueError("invalid database name (use letters/numbers/_ only)")
        return name

    def _db_path_for(self, name: str) -> str:
        name = self._validate_db_name(name)
        return os.path.join(self._databases_dir, f"{name}.db")

    def show_databases(self) -> list[str]:
        if not os.path.isdir(self._databases_dir):
            return []
        out: list[str] = []
        for fn in os.listdir(self._databases_dir):
            if fn.lower().endswith(".db"):
                out.append(os.path.splitext(fn)[0])
        return sorted(out)

    def create_database(self, name: str, *, if_not_exists: bool = False) -> bool:
        name = self._validate_db_name(name)
        path = self._db_path_for(name)
        if os.path.exists(path):
            if if_not_exists:
                return False
            raise ValueError(f"database exists: {name}")
        # Create empty DB container
        db = DBFile.open(path)
        db.close()
        # Create empty WAL file
        open(path + ".wal", "ab").close()
        return True

    def use_database(self, name: str) -> None:
        if self._tx is not None:
            raise ValueError("cannot USE database inside a transaction")
        name = self._validate_db_name(name)
        path = self._db_path_for(name)
        if not os.path.exists(path):
            raise ValueError(f"unknown database: {name}")

        # Flush catalog for current DB and close files
        self._catalog.flush(self._db)
        self._wal.close()
        self._db.close()

        db = DBFile.open(path)
        wal = Wal.open(path + ".wal")
        catalog = Catalog.load(db)
        wal.recover_into(db)

        self._name = name
        self._db = db
        self._wal = wal
        self._catalog = catalog
        self._executor = Executor(db=self, wal=self._wal, catalog=self._catalog)

    def schema(self, table: str) -> Optional[str]:
        td = self._catalog.tables.get(table)
        if not td:
            return None
        cols = ", ".join(f"{c.name} {c.type}" for c in td.columns)
        return f"CREATE TABLE {td.name} ({cols});"

    # --- KV access (transaction-aware) ---
    def kv_get(self, key: str) -> Optional[bytes]:
        if self._tx is not None and key in self._tx:
            return self._tx[key]
        return self._db.kv_get(key)

    def kv_put(self, key: str, value: bytes) -> None:
        if self._tx is not None:
            assert self._tx_wal is not None
            self._tx[key] = value
            self._tx_wal.append((key, value))
            return
        self._wal.append_put(key, value)
        self._db.kv_put(key, value)

    # --- Transactions ---
    def begin(self) -> None:
        if self._tx is not None:
            raise ValueError("transaction already open")
        self._tx = {}
        self._tx_wal = []

    def commit(self) -> None:
        if self._tx is None:
            raise ValueError("no open transaction")
        assert self._tx_wal is not None
        for k, v in self._tx_wal:
            self._wal.append_put(k, v)
            self._db.kv_put(k, v)
        self._tx = None
        self._tx_wal = None

    def rollback(self) -> None:
        if self._tx is None:
            raise ValueError("no open transaction")
        self._tx = None
        self._tx_wal = None

    # --- Script runner ---
    @staticmethod
    def split_sql_script(script: str) -> list[str]:
        """
        Split a script into statements by ';', respecting simple single/double quotes.
        """
        out: list[str] = []
        buf: list[str] = []
        in_s = False
        in_d = False
        esc = False
        for ch in script:
            if esc:
                buf.append(ch)
                esc = False
                continue
            if ch == "\\":
                # allow escaping inside strings
                if in_s or in_d:
                    esc = True
                buf.append(ch)
                continue
            if ch == "'" and not in_d:
                in_s = not in_s
                buf.append(ch)
                continue
            if ch == '"' and not in_s:
                in_d = not in_d
                buf.append(ch)
                continue
            if ch == ";" and not in_s and not in_d:
                stmt = "".join(buf).strip()
                if stmt:
                    out.append(stmt + ";")
                buf = []
                continue
            buf.append(ch)
        tail = "".join(buf).strip()
        if tail:
            out.append(tail if tail.endswith(";") else tail + ";")
        return out

    def execute_script(self, script: str) -> list[tuple[list[str], list[tuple[Any, ...]]]]:
        results: list[tuple[list[str], list[tuple[Any, ...]]]] = []
        for sql in self.split_sql_script(script):
            stmt: Statement = parse_sql(sql)
            out = self._executor.execute(stmt)
            if out is None:
                continue
            results.append((out.columns, out.rows))
        return results



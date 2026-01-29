from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from levilite.storage.dbfile import DBFile


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: str  # INT | TEXT | REAL | BOOL
    primary_key: bool = False
    unique: bool = False
    auto_increment: bool = False
    auto_increment: bool = False
    default: Optional[str] = None  # Default value as string


@dataclass
class TableDef:
    name: str
    columns: List[ColumnDef]
    indexes: List[dict]  # [{name, column, unique}]


class Catalog:
    """
    Persisted metadata: tables and column definitions.

    MVP: stored as a small JSON blob under a reserved key in DBFile.
    """

    _CATALOG_KEY = "__levilite_catalog__"

    def __init__(self) -> None:
        self.tables: Dict[str, TableDef] = {}

    def rename_table(self, old: str, new: str) -> None:
        if old not in self.tables:
            raise ValueError(f"unknown table: {old}")
        if new in self.tables:
            raise ValueError(f"table exists: {new}")
        self.tables[new] = self.tables.pop(old)
        self.tables[new].name = new

    def drop_index(self, table: str, name: str) -> None:
        td = self.tables.get(table)
        if not td:
            raise ValueError(f"unknown table: {table}")
        idxs = [i for i in td.indexes if i.get("name") != name]
        if len(idxs) == len(td.indexes):
            raise ValueError(f"index not found: {name}")
        td.indexes = idxs

    @classmethod
    def load(cls, db: DBFile) -> "Catalog":
        c = cls()
        raw = db.kv_get(cls._CATALOG_KEY)
        if not raw:
            return c
        obj = json.loads(raw.decode("utf-8"))
        for tname, tdef in obj.get("tables", {}).items():
            cols = [
                ColumnDef(
                    name=x["name"],
                    type=x["type"],
                    primary_key=bool(x.get("primary_key", False)),
                    unique=bool(x.get("unique", False)),
                )
                for x in tdef["columns"]
            ]
            idxs = list(tdef.get("indexes", []))
            c.tables[tname] = TableDef(name=tname, columns=cols, indexes=idxs)
        return c

    def flush(self, db: DBFile) -> None:
        obj = {
            "tables": {
                tname: {
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.type,
                            "primary_key": c.primary_key,
                            "unique": c.unique,
                        }
                        for c in t.columns
                    ],
                    "indexes": list(getattr(t, "indexes", [])),
                }
                for tname, t in self.tables.items()
            }
        }
        db.kv_put(self._CATALOG_KEY, json.dumps(obj).encode("utf-8"))

    def create_table(self, name: str, columns: list[ColumnDef], if_not_exists: bool = False) -> None:
        if name in self.tables:
            if if_not_exists:
                return
            raise ValueError(f"table exists: {name}")
        _allowed = {"INT", "TEXT", "REAL", "BOOL"}
        for c in columns:
            t = c.type.upper()
            if t not in _allowed:
                raise ValueError(f"unsupported type: {t}")
        # Only one PRIMARY KEY for MVP
        if sum(1 for c in columns if c.primary_key) > 1:
            raise ValueError("only one PRIMARY KEY supported (MVP)")
        indexes: list[dict] = []
        for c in columns:
            if c.primary_key:
                indexes.append({"name": f"pk_{name}_{c.name}", "column": c.name, "unique": True})
            elif c.unique:
                indexes.append({"name": f"uq_{name}_{c.name}", "column": c.name, "unique": True})
        self.tables[name] = TableDef(name=name, columns=columns, indexes=indexes)

    def get_table(self, name: str) -> Optional[TableDef]:
        return self.tables.get(name)

    def drop_table(self, name: str, *, if_exists: bool = False) -> bool:
        if name not in self.tables:
            if if_exists:
                return False
            raise ValueError(f"unknown table: {name}")
        del self.tables[name]
        return True

    def add_column(self, table: str, col: ColumnDef) -> None:
        td = self.tables.get(table)
        if not td:
            raise ValueError(f"unknown table: {table}")
        if col.name in {c.name for c in td.columns}:
            raise ValueError(f"column exists: {col.name}")
        td.columns.append(col)
        if col.primary_key:
            raise ValueError("ALTER TABLE cannot add PRIMARY KEY in MVP")
        if col.unique:
            td.indexes.append({"name": f"uq_{table}_{col.name}", "column": col.name, "unique": True})

    def create_index(self, table: str, name: str, column: str, *, unique: bool = False) -> None:
        td = self.tables.get(table)
        if not td:
            raise ValueError(f"unknown table: {table}")
        if column not in {c.name for c in td.columns}:
            raise ValueError(f"unknown column: {column}")
        if any(i.get("name") == name for i in td.indexes):
            raise ValueError(f"index exists: {name}")
        td.indexes.append({"name": name, "column": column, "unique": bool(unique)})



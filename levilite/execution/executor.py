from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from levilite.catalog import Catalog, ColumnDef
from levilite.sql.ast import (
    Begin,
    Commit,
    CreateDatabase,
    CreateIndex,
    CreateTable,
    Delete,
    DescribeTable,
    DropTable,
    Insert,
    Join,
    Rollback,
    ShowDatabases,
    ShowTables,
    Select,
    Statement,
    Update,
    UseDatabase,
    AlterTableAddColumn,
    Aggregate,
    WhereExpr,
)
from levilite.storage.wal import Wal


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]


def _table_key(table: str) -> str:
    return f"table:{table}:rows"

def _table_meta_key(table: str) -> str:
    return f"table:{table}:meta"

def _index_key(table: str, column: str) -> str:
    return f"index:{table}:{column}"


class Executor:
    """
    Executes the AST against a simple heap store.

    Per table:
    - A JSON list of row objects (simple, not optimized).
    """

    def __init__(self, db, wal: Wal, catalog: Catalog) -> None:
        self._db = db
        self._wal = wal
        self._catalog = catalog

    def execute(self, stmt: Statement) -> Optional[QueryResult]:
        def load_rows(table: str) -> list[dict]:
            raw = self._db.kv_get(_table_key(table)) or b"[]"
            rows = json.loads(raw.decode("utf-8"))
            if not isinstance(rows, list):
                raise ValueError("corrupt table storage")
            # Ensure rowid exists
            changed = False
            meta_raw = self._db.kv_get(_table_meta_key(table))
            meta = json.loads(meta_raw.decode("utf-8")) if meta_raw else {"next_rowid": 1}
            next_rowid = int(meta.get("next_rowid", 1))
            for r in rows:
                if "_rowid" not in r:
                    r["_rowid"] = next_rowid
                    next_rowid += 1
                    changed = True
            if changed:
                meta["next_rowid"] = next_rowid
                self._db.kv_put(_table_meta_key(table), json.dumps(meta).encode("utf-8"))
                self._db.kv_put(_table_key(table), json.dumps(rows).encode("utf-8"))
            return rows

        def save_rows(table: str, rows: list[dict]) -> None:
            self._db.kv_put(_table_key(table), json.dumps(rows).encode("utf-8"))

        def next_rowid(table: str) -> int:
            meta_raw = self._db.kv_get(_table_meta_key(table))
            meta = json.loads(meta_raw.decode("utf-8")) if meta_raw else {"next_rowid": 1}
            rid = int(meta.get("next_rowid", 1))
            meta["next_rowid"] = rid + 1
            self._db.kv_put(_table_meta_key(table), json.dumps(meta).encode("utf-8"))
            return rid

        def rebuild_index(table: str, col: str) -> dict[str, list[int]]:
            rows = load_rows(table)
            idx: dict[str, list[int]] = {}
            for r in rows:
                v = r.get(col)
                key = json.dumps(v, ensure_ascii=False)
                idx.setdefault(key, []).append(int(r["_rowid"]))
            self._db.kv_put(_index_key(table, col), json.dumps(idx).encode("utf-8"))
            return idx

        def get_index(table: str, col: str) -> dict[str, list[int]] | None:
            raw = self._db.kv_get(_index_key(table, col))
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))

        def ensure_unique(table: str, col: str, value: Any, *, exclude_rowid: int | None = None) -> None:
            idx = get_index(table, col)
            if idx is None:
                idx = rebuild_index(table, col)
            key = json.dumps(value, ensure_ascii=False)
            hits = idx.get(key, [])
            if exclude_rowid is not None:
                hits = [x for x in hits if x != exclude_rowid]
            if hits:
                raise ValueError(f"duplicate value for UNIQUE index on {table}.{col}: {value!r}")

        def eval_where(row: dict, where: WhereExpr | None) -> bool:
            if where is None:
                return True
            op = where.op.upper()
            if op in {"AND", "OR"}:
                l = eval_where(row, where.left)
                r = eval_where(row, where.right)
                return l and r if op == "AND" else l or r
            left = where.left
            if isinstance(left, WhereExpr):
                lv = eval_where(row, left)
            else:
                # Support qualified column: table.col
                col = left.split(".", 1)[1] if isinstance(left, str) and "." in left else left
                lv = row.get(col)
            rv = where.right
            if isinstance(rv, WhereExpr):
                rv = eval_where(row, rv)
            op = where.op.upper()
            if op == "=":
                return lv == rv
            if op == "!=":
                return lv != rv
            if op == "<":
                return lv is not None and rv is not None and lv < rv
            if op == "<=":
                return lv is not None and rv is not None and lv <= rv
            if op == ">":
                return lv is not None and rv is not None and lv > rv
            if op == ">=":
                return lv is not None and rv is not None and lv >= rv
            if op == "LIKE":
                if lv is None:
                    return False
                pat = str(rv)
                regex = "^" + re.escape(pat).replace(r"\%", ".*").replace(r"\_", ".") + "$"
                return re.match(regex, str(lv)) is not None
            if op == "IN":
                if lv is None:
                    return False
                return lv in rv
            if op == "NOT_IN":
                if lv is None:
                    return True
                return lv not in rv
            if op == "BETWEEN":
                if lv is None:
                    return False
                val1, val2 = rv
                return val1 <= lv <= val2
            raise ValueError("unsupported WHERE op")

        def validate_column(td, col: str) -> None:
            colname = col.split(".", 1)[1] if "." in col else col
            if colname not in {c.name for c in td.columns}:
                raise ValueError(f"unknown column: {col}")

        def coerce_value(col_type: str, val: Any) -> Any:
            if val is None:
                return None
            t = col_type.upper()
            if t == "TEXT":
                return str(val)
            if t == "INT":
                if isinstance(val, bool):
                    return int(val)
                if isinstance(val, (int,)):
                    return int(val)
                if isinstance(val, str) and val.strip().lstrip("-").isdigit():
                    return int(val.strip())
                raise ValueError(f"cannot coerce value to INT: {val!r}")
            if t == "REAL":
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    return float(val)
                raise ValueError(f"cannot coerce value to REAL: {val!r}")
            if t == "BOOL":
                if isinstance(val, bool):
                    return val
                if isinstance(val, (int,)):
                    return bool(val)
                if isinstance(val, str):
                    s = val.strip().lower()
                    if s in {"true", "1", "yes", "y"}:
                        return True
                    if s in {"false", "0", "no", "n"}:
                        return False
                raise ValueError(f"cannot coerce value to BOOL: {val!r}")
            raise ValueError(f"unsupported type: {t}")

        def match_where(r: dict, where_eq) -> bool:
            if not where_eq:
                return True
            k, v = where_eq
            return r.get(k) == v

        if isinstance(stmt, CreateTable):
            cols = [ColumnDef(name=n, type=t, primary_key=pk, unique=uq, auto_increment=ai) for n, t, pk, uq, ai in stmt.columns]
            self._catalog.create_table(stmt.name, cols, getattr(stmt, "if_not_exists", False))
            # init heap only if table was just created
            td = self._catalog.get_table(stmt.name)
            if td and self._db.kv_get(_table_key(stmt.name)) is None:
                self._db.kv_put(_table_key(stmt.name), b"[]")
                self._db.kv_put(_table_meta_key(stmt.name), json.dumps({"next_rowid": 1}).encode("utf-8"))
                # create persistent indexes (unique constraints)
                for idx in td.indexes:
                    rebuild_index(stmt.name, idx["column"])
            return None

        if isinstance(stmt, CreateDatabase):
            created = self._db.create_database(stmt.name, if_not_exists=stmt.if_not_exists)
            return QueryResult(columns=["database", "created"], rows=[(stmt.name, created)])

        if isinstance(stmt, UseDatabase):
            self._db.use_database(stmt.name)
            return QueryResult(columns=["database"], rows=[(self._db.current_database(),)])

        if isinstance(stmt, ShowDatabases):
            dbs = self._db.show_databases()
            return QueryResult(columns=["Database"], rows=[(x,) for x in dbs])

        if isinstance(stmt, ShowTables):
            tables = self._db.list_tables()
            return QueryResult(columns=[f"Tables_in_{self._db.current_database()}"], rows=[(t,) for t in tables])

        if hasattr(stmt, "__class__") and stmt.__class__.__name__ == "ShowColumns":
            td = self._catalog.get_table(stmt.table)
            if not td:
                raise ValueError(f"unknown table: {stmt.table}")
            return QueryResult(
                columns=["Field", "Type", "Null", "Key"],
                rows=[
                    (c.name, c.type, "NO" if c.primary_key else "YES", "PRI" if c.primary_key else "")
                    for c in td.columns
                ],
            )

        if isinstance(stmt, DescribeTable):
            td = self._catalog.get_table(stmt.name)
            if not td:
                raise ValueError(f"unknown table: {stmt.name}")
            return QueryResult(
                columns=["Field", "Type", "Key", "Unique"],
                rows=[
                    (c.name, c.type, "PRI" if c.primary_key else "", "YES" if c.unique else "")
                    for c in td.columns
                ],
            )

        if isinstance(stmt, AlterTableAddColumn):
            self._catalog.add_column(stmt.table, ColumnDef(name=stmt.column[0], type=stmt.column[1]))
            rows = load_rows(stmt.table)
            col = stmt.column[0]
            for r in rows:
                if col not in r:
                    r[col] = None
            save_rows(stmt.table, rows)
            return QueryResult(columns=["altered"], rows=[(True,)])

        if isinstance(stmt, CreateIndex):
            self._catalog.create_index(stmt.table, stmt.name, stmt.column, unique=stmt.unique)
            rebuild_index(stmt.table, stmt.column)
            return QueryResult(columns=["index", "created"], rows=[(stmt.name, True)])

        if isinstance(stmt, Begin):
            self._db.begin()
            return QueryResult(columns=["transaction"], rows=[("BEGIN",)])

        if isinstance(stmt, Commit):
            self._db.commit()
            return QueryResult(columns=["transaction"], rows=[("COMMIT",)])

        if isinstance(stmt, Rollback):
            self._db.rollback()
            return QueryResult(columns=["transaction"], rows=[("ROLLBACK",)])

        if isinstance(stmt, DropTable):
            dropped = self._catalog.drop_table(stmt.name, if_exists=stmt.if_exists)
            # Remove row heap key if present (best-effort)
            if dropped:
                self._db.kv_put(_table_key(stmt.name), b"[]")
                self._db.kv_put(_table_meta_key(stmt.name), json.dumps({"next_rowid": 1}).encode("utf-8"))
            return QueryResult(columns=["dropped"], rows=[(bool(dropped),)])

        if isinstance(stmt, Insert):
            td = self._catalog.get_table(stmt.table)
            if not td:
                raise ValueError(f"unknown table: {stmt.table}")
            if len(stmt.columns) != len(stmt.values):
                raise ValueError("columns/values length mismatch")

            rows = load_rows(stmt.table)
            for c in stmt.columns:
                validate_column(td, c)
            col_types = {c.name: c.type for c in td.columns}
            row_obj = {c: coerce_value(col_types[c], v) for c, v in zip(stmt.columns, stmt.values)}
            
            # Handle AUTO_INCREMENT: if column has auto_increment and value is None or missing, use next_rowid
            auto_id = None
            for col_def in td.columns:
                if getattr(col_def, "auto_increment", False) and col_def.name not in row_obj:
                    auto_id = next_rowid(stmt.table)
                    row_obj[col_def.name] = auto_id
            
            # apply constraints via indexes
            for idx in getattr(td, "indexes", []):
                if idx.get("unique"):
                    col = idx["column"]
                    if col in row_obj:
                        ensure_unique(stmt.table, col, row_obj.get(col))
            # Use the auto_id if set, otherwise get new rowid
            row_obj["_rowid"] = auto_id if auto_id is not None else next_rowid(stmt.table)
            rows.append(row_obj)
            save_rows(stmt.table, rows)
            # update indexes (best-effort rebuild for MVP)
            for idx in getattr(td, "indexes", []):
                rebuild_index(stmt.table, idx["column"])
            return QueryResult(columns=["rows_affected"], rows=[(1,)])

        if isinstance(stmt, Select):
            td = self._catalog.get_table(stmt.table)
            if not td:
                raise ValueError(f"unknown table: {stmt.table}")
            left_rows = load_rows(stmt.table)

            out_cols = stmt.columns
            if out_cols == ["*"]:
                out_cols = [c.name for c in td.columns]

            # JOIN (one inner join, equality, MVP)
            working: list[dict] = []
            if stmt.join is None:
                # Optimisation WHERE avec index (MVP: = sur colonne indexée, pas AND/OR)
                index_used = False
                if stmt.where and stmt.where.op == "=" and isinstance(stmt.where.left, str):
                    col = stmt.where.left
                    idxs = getattr(td, "indexes", [])
                    idx = next((i for i in idxs if i.get("column") == col), None)
                    if idx:
                        idx_data = get_index(stmt.table, col)
                        key = json.dumps(stmt.where.right, ensure_ascii=False)
                        rowids = idx_data.get(key, []) if idx_data else []
                        for r in left_rows:
                            if r.get("_rowid") in rowids and eval_where(r, stmt.where):
                                working.append(r)
                        index_used = True
                if not index_used:
                    for r in left_rows:
                        if eval_where(r, stmt.where):
                            working.append(r)
            else:
                j: Join = stmt.join
                right_td = self._catalog.get_table(j.right_table)
                if not right_td:
                    raise ValueError(f"unknown table: {j.right_table}")
                right_rows = load_rows(j.right_table)
                lcol = j.left_col.split(".", 1)[1] if "." in j.left_col else j.left_col
                rcol = j.right_col.split(".", 1)[1] if "." in j.right_col else j.right_col
                # build hash on right
                h: dict[Any, list[dict]] = {}
                for rr in right_rows:
                    h.setdefault(rr.get(rcol), []).append(rr)
                for lr in left_rows:
                    for rr in h.get(lr.get(lcol), []):
                        merged = {}
                        # qualify keys to avoid collisions
                        for k, v in lr.items():
                            merged[f"{stmt.table}.{k}"] = v
                        for k, v in rr.items():
                            merged[f"{j.right_table}.{k}"] = v
                        if eval_where(merged, stmt.where):
                            working.append(merged)

                if out_cols == ["*"]:
                    out_cols = [f"{stmt.table}.{c.name}" for c in td.columns] + [
                        f"{j.right_table}.{c.name}" for c in right_td.columns
                    ]

            # Validate selected columns
            if out_cols != ["*"]:
                if stmt.join is None:
                    for c in out_cols:
                        # Skip validation for aggregate functions
                        if not re.match(r"(COUNT|MIN|MAX|AVG|SUM)\s*\(", c, re.IGNORECASE):
                            validate_column(td, c)
                else:
                    # qualified required for JOIN projection if ambiguous
                    pass

            # GROUP BY + COUNT, COUNT_DISTINCT, MIN, MAX, AVG, SUM, multi-colonnes
            if stmt.group_by or stmt.aggregates:
                group_keys = stmt.group_by
                if group_keys:
                    # GROUP BY path
                    buckets: dict[Any, list[dict]] = {}
                    for r in working:
                        if isinstance(group_keys, list):
                            k = tuple(r.get(gk) for gk in group_keys)
                        else:
                            k = r.get(group_keys)
                        buckets.setdefault(k, []).append(r)
                    out_rows: list[tuple[Any, ...]] = []
                    for k, items in buckets.items():
                        row_out: list[Any] = []
                        for col in out_cols:
                            m = re.fullmatch(r"COUNT\((\*|[A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                            md = re.fullmatch(r"COUNT\(DISTINCT ([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                            mmin = re.fullmatch(r"MIN\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                            mmax = re.fullmatch(r"MAX\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                            mavg = re.fullmatch(r"AVG\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                            msum = re.fullmatch(r"SUM\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                            if m:
                                arg = m.group(1)
                                if arg == "*":
                                    row_out.append(len(items))
                                else:
                                    row_out.append(sum(1 for it in items if it.get(arg) is not None))
                            elif md:
                                arg = md.group(1)
                                row_out.append(len(set(it.get(arg) for it in items if it.get(arg) is not None)))
                            elif mmin:
                                arg = mmin.group(1)
                                vals = [it.get(arg) for it in items if it.get(arg) is not None]
                                row_out.append(min(vals) if vals else None)
                            elif mmax:
                                arg = mmax.group(1)
                                vals = [it.get(arg) for it in items if it.get(arg) is not None]
                                row_out.append(max(vals) if vals else None)
                            elif mavg:
                                arg = mavg.group(1)
                                vals = [it.get(arg) for it in items if it.get(arg) is not None]
                                row_out.append(sum(vals) / len(vals) if vals else None)
                            elif msum:
                                arg = msum.group(1)
                                vals = [it.get(arg) for it in items if it.get(arg) is not None]
                                row_out.append(sum(vals) if vals else None)
                            elif isinstance(group_keys, list) and col in group_keys:
                                idx = group_keys.index(col)
                                row_out.append(k[idx])
                            elif col == group_keys:
                                row_out.append(k)
                            else:
                                row_out.append(None)
                        out_rows.append(tuple(row_out))
                    
                    # Apply HAVING clause
                    if stmt.having:
                        filtered_rows: list[tuple[Any, ...]] = []
                        for row_tuple, (k, items) in zip(out_rows, buckets.items()):
                            row_dict = dict(zip(out_cols, row_tuple))
                            if eval_where(row_dict, stmt.having):
                                filtered_rows.append(row_tuple)
                        out_rows = filtered_rows
                else:
                    # No GROUP BY, but has aggregates - compute global aggregates
                    out_rows: list[tuple[Any, ...]] = []
                    row_out: list[Any] = []
                    for col in out_cols:
                        m = re.fullmatch(r"COUNT\((\*|[A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                        md = re.fullmatch(r"COUNT\(DISTINCT ([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                        mmin = re.fullmatch(r"MIN\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                        mmax = re.fullmatch(r"MAX\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                        mavg = re.fullmatch(r"AVG\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                        msum = re.fullmatch(r"SUM\(([A-Za-z0-9_\.]+)\)", col, flags=re.IGNORECASE)
                        if m:
                            arg = m.group(1)
                            if arg == "*":
                                row_out.append(len(working))
                            else:
                                row_out.append(sum(1 for it in working if it.get(arg) is not None))
                        elif md:
                            arg = md.group(1)
                            row_out.append(len(set(it.get(arg) for it in working if it.get(arg) is not None)))
                        elif mmin:
                            arg = mmin.group(1)
                            vals = [it.get(arg) for it in working if it.get(arg) is not None]
                            row_out.append(min(vals) if vals else None)
                        elif mmax:
                            arg = mmax.group(1)
                            vals = [it.get(arg) for it in working if it.get(arg) is not None]
                            row_out.append(max(vals) if vals else None)
                        elif mavg:
                            arg = mavg.group(1)
                            vals = [it.get(arg) for it in working if it.get(arg) is not None]
                            row_out.append(sum(vals) / len(vals) if vals else None)
                        elif msum:
                            arg = msum.group(1)
                            vals = [it.get(arg) for it in working if it.get(arg) is not None]
                            row_out.append(sum(vals) if vals else None)
                        else:
                            row_out.append(None)
                    out_rows = [tuple(row_out)]
            else:
                out_rows = [tuple(r.get(c) for c in out_cols) for r in working]
                
                # Apply DISTINCT
                if stmt.distinct:
                    out_rows = list(dict.fromkeys(out_rows))

            if stmt.order_by:
                col, asc = stmt.order_by
                idx = out_cols.index(col) if col in out_cols else None
                if idx is None:
                    out_rows.sort(key=lambda tup: tup)  # fallback (stable)
                else:
                    out_rows.sort(key=lambda tup: tup[idx])
                if not asc:
                    out_rows.reverse()

            if stmt.limit is not None:
                out_rows = out_rows[: stmt.limit]
            if stmt.offset is not None:
                out_rows = out_rows[stmt.offset :]
            return QueryResult(columns=out_cols, rows=out_rows)

        if isinstance(stmt, Update):
            td = self._catalog.get_table(stmt.table)
            if not td:
                raise ValueError(f"unknown table: {stmt.table}")
            rows = load_rows(stmt.table)
            col_types = {c.name: c.type for c in td.columns}

            for c, _ in stmt.set_pairs:
                validate_column(td, c)

            affected = 0
            for r in rows:
                if not eval_where(r, stmt.where):
                    continue
                # pre-check uniques with exclude rowid
                for idx in getattr(td, "indexes", []):
                    if idx.get("unique"):
                        col = idx["column"]
                        for c, v in stmt.set_pairs:
                            if c == col:
                                ensure_unique(stmt.table, col, coerce_value(col_types[col], v), exclude_rowid=int(r["_rowid"]))
                for c, v in stmt.set_pairs:
                    r[c] = coerce_value(col_types[c], v)
                affected += 1

            save_rows(stmt.table, rows)
            # enforce / refresh indexes after update
            for idx in getattr(td, "indexes", []):
                rebuild_index(stmt.table, idx["column"])
            return QueryResult(columns=["rows_affected"], rows=[(affected,)])

        if isinstance(stmt, Delete):
            td = self._catalog.get_table(stmt.table)
            if not td:
                raise ValueError(f"unknown table: {stmt.table}")
            rows = load_rows(stmt.table)
            kept = [r for r in rows if not eval_where(r, stmt.where)]
            affected = len(rows) - len(kept)
            save_rows(stmt.table, kept)
            for idx in getattr(td, "indexes", []):
                rebuild_index(stmt.table, idx["column"])
            return QueryResult(columns=["rows_affected"], rows=[(affected,)])

        if hasattr(stmt, "__class__") and stmt.__class__.__name__ == "AlterTableRename":
            self._catalog.rename_table(stmt.table, stmt.new_name)
            return QueryResult(columns=["renamed"], rows=[(True,)])

        if hasattr(stmt, "__class__") and stmt.__class__.__name__ == "DropIndex":
            self._catalog.drop_index(stmt.table, stmt.name)
            return QueryResult(columns=["dropped"], rows=[(True,)])

        if hasattr(stmt, "__class__") and stmt.__class__.__name__ == "TruncateTable":
            self._catalog.get_table(stmt.name)  # Verify table exists
            self._db.kv_put(_table_key(stmt.name), b"[]")
            self._db.kv_put(_table_meta_key(stmt.name), json.dumps({"next_rowid": 1}).encode("utf-8"))
            return QueryResult(columns=["truncated"], rows=[(True,)])

        raise ValueError("unhandled statement")



from __future__ import annotations

import re
from typing import Any

from levilite.sql.ast import (
    Begin,
    Commit,
    CreateDatabase,
    CreateIndex,
    CreateTable,
    Delete,
    DescribeTable,
    DropTable,
    DropIndex,
    Insert,
    Rollback,
    ShowDatabases,
    ShowTables,
    ShowColumns,
    Select,
    Statement,
    Update,
    UseDatabase,
    AlterTableAddColumn,
    AlterTableRename,
    TruncateTable,
    Aggregate,
    Join,
    WhereExpr,
)


_WS = re.compile(r"\s+")


def _tok(s: str) -> list[str]:
    # Tokenizer MVP (pas SQL complet).
    s = s.strip()
    if s.endswith(";"):
        s = s[:-1]
    # garder , ( ) = comme tokens
    s = re.sub(r"([(),=])", r" \1 ", s)
    s = _WS.sub(" ", s)
    return s.strip().split(" ") if s else []


def _parse_value(tok: str) -> Any:
    if tok.startswith('"') and tok.endswith('"'):
        return tok[1:-1]
    if tok.startswith("'") and tok.endswith("'"):
        return tok[1:-1]
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    if re.fullmatch(r"-?\d+\.\d+", tok):
        return float(tok)
    return tok


def parse_sql(sql: str) -> Statement:

    # Ignore les lignes vides et les commentaires SQL (-- ...)
    sql_clean = []
    for line in sql.splitlines():
        l = line.strip()
        if not l or l.startswith('--'):
            continue
        sql_clean.append(line)
    sql = '\n'.join(sql_clean)

    toks = _tok(sql)
    if not toks:
        raise ValueError("empty statement")
    head = toks[0].upper()

    if head == "CREATE":
        # CREATE TABLE ... / CREATE DATABASE ...
        if len(toks) < 3:
            raise ValueError("invalid CREATE statement")
        kind = toks[1].upper()
        if kind == "TABLE":
            # CREATE TABLE [IF NOT EXISTS] name (col TYPE, ...)
            i = 2
            if_not_exists = False
            if (
                i + 3 < len(toks)
                and toks[i].upper() == "IF"
                and toks[i + 1].upper() == "NOT"
                and toks[i + 2].upper() == "EXISTS"
            ):
                if_not_exists = True
                i += 3
            name = toks[i]
            if toks[i + 1] != "(" or toks[-1] != ")":
                raise ValueError("expected column list in ( )")
            inner = toks[i + 2 : -1]
            cols: list[tuple[str, str, bool, bool, bool]] = []
            j = 0
            while j < len(inner):
                col = inner[j]
                ctype = inner[j + 1].upper()
                primary_key = False
                unique = False
                auto_increment = False
                k = j + 2
                # inline constraints: PRIMARY KEY / UNIQUE / AUTO_INCREMENT
                while k < len(inner) and inner[k] not in {","}:
                    tok = inner[k].upper()
                    if tok == "PRIMARY" and k + 1 < len(inner) and inner[k + 1].upper() == "KEY":
                        primary_key = True
                        k += 2
                        continue
                    if tok == "UNIQUE":
                        unique = True
                        k += 1
                        continue
                    if tok == "AUTO_INCREMENT":
                        auto_increment = True
                        k += 1
                        continue
                    break
                cols.append((col, ctype, primary_key, unique, auto_increment))
                j = k
                if j < len(inner):
                    if inner[j] != ",":
                        raise ValueError("expected ',' between columns")
                    j += 1
            return CreateTable(name=name, columns=cols, if_not_exists=if_not_exists)

        if kind == "DATABASE":
            # CREATE DATABASE [IF NOT EXISTS] name
            i = 2
            if_not_exists = False
            if (
                i + 3 < len(toks)
                and toks[i].upper() == "IF"
                and toks[i + 1].upper() == "NOT"
                and toks[i + 2].upper() == "EXISTS"
            ):
                if_not_exists = True
                i += 3
            name = toks[i]
            return CreateDatabase(name=name, if_not_exists=if_not_exists)

        if kind == "INDEX" or (kind == "UNIQUE" and len(toks) > 2 and toks[2].upper() == "INDEX"):
            # CREATE [UNIQUE] INDEX name ON table (col)
            unique = kind == "UNIQUE"
            i = 2 if not unique else 3
            name = toks[i]
            if toks[i + 1].upper() != "ON":
                raise ValueError("expected ON")
            table = toks[i + 2]
            if toks[i + 3] != "(" or toks[i + 5] != ")":
                raise ValueError("expected (col)")
            col = toks[i + 4]
            return CreateIndex(name=name, table=table, column=col, unique=unique)

        raise ValueError("unsupported CREATE statement")

    if head == "INSERT":
        # INSERT INTO t (a,b) VALUES (1,"x")
        if toks[1].upper() != "INTO":
            raise ValueError("expected INSERT INTO")
        table = toks[2]
        i = 3
        if toks[i] != "(":
            raise ValueError("expected column list '('")
        i += 1
        columns: list[str] = []
        while toks[i] != ")":
            if toks[i] != ",":
                columns.append(toks[i])
            i += 1
        i += 1
        if toks[i].upper() != "VALUES":
            raise ValueError("expected VALUES")
        i += 1
        if toks[i] != "(":
            raise ValueError("expected values '('")
        i += 1
        values: list[Any] = []
        while toks[i] != ")":
            if toks[i] != ",":
                values.append(_parse_value(toks[i]))
            i += 1
        return Insert(table=table, columns=columns, values=values)

    if head == "SELECT":
        # SELECT [DISTINCT] cols FROM t [JOIN ...] [WHERE ...] [GROUP BY ...] [HAVING ...] [ORDER BY ...] [LIMIT ...] [OFFSET ...]
        i = 1
        distinct = False
        if toks[i].upper() == "DISTINCT":
            distinct = True
            i += 1
        cols: list[str] = []
        while toks[i].upper() != "FROM":
            if toks[i] == ",":
                i += 1
                continue
            # Reconstruct aggregate function calls (e.g., COUNT ( col ) → COUNT(col))
            if toks[i].upper() in {"COUNT", "MIN", "MAX", "AVG", "SUM"} and i + 2 < len(toks) and toks[i + 1] == "(":
                func_name = toks[i].upper()
                j = i + 2
                # Collect tokens inside parentheses
                inner = []
                depth = 1
                while j < len(toks) and depth > 0:
                    if toks[j] == "(":
                        depth += 1
                    elif toks[j] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    inner.append(toks[j])
                    j += 1
                if depth != 0:
                    raise ValueError(f"mismatched parentheses in {func_name}")
                # Reconstruct as single token: COUNT(col) or COUNT(DISTINCT col)
                inner_str = " ".join(inner)
                cols.append(f"{func_name}({inner_str})")
                i = j + 1
            else:
                cols.append(toks[i])
                i += 1
        i += 1
        table = toks[i]
        i += 1
        join = None
        # Support for multiple JOINs (MVP: only one, but can be extended)
        if i < len(toks) and toks[i].upper() == "JOIN":
            right_table = toks[i + 1]
            if toks[i + 2].upper() != "ON":
                raise ValueError("expected ON")
            left_col = toks[i + 3]
            if toks[i + 4] != "=":
                raise ValueError("expected '=' in JOIN ON")
            right_col = toks[i + 5]
            join = Join(right_table=right_table, left_col=left_col, right_col=right_col)
            i += 6

        def parse_where_expr(start: int) -> tuple[WhereExpr, int]:
            # Recursive descent for AND/OR
            left = toks[start]
            if left == "(":
                # Parenthesized
                expr, next_i = parse_where_expr(start + 1)
                if toks[next_i] != ")":
                    raise ValueError("expected )")
                left = expr
                start = next_i + 1
            else:
                op = toks[start + 1].upper()
                
                # Handle IN operator
                if op == "IN":
                    if toks[start + 2] != "(":
                        raise ValueError("expected ( after IN")
                    values = []
                    j = start + 3
                    while j < len(toks) and toks[j] != ")":
                        if toks[j] != ",":
                            values.append(_parse_value(toks[j]))
                        j += 1
                    if j >= len(toks):
                        raise ValueError("expected ) in IN clause")
                    left = WhereExpr(left=left, op="IN", right=values)
                    start = j + 1
                
                # Handle NOT IN operator
                elif op == "NOT" and start + 2 < len(toks) and toks[start + 2].upper() == "IN":
                    if toks[start + 3] != "(":
                        raise ValueError("expected ( after NOT IN")
                    values = []
                    j = start + 4
                    while j < len(toks) and toks[j] != ")":
                        if toks[j] != ",":
                            values.append(_parse_value(toks[j]))
                        j += 1
                    if j >= len(toks):
                        raise ValueError("expected ) in NOT IN clause")
                    left = WhereExpr(left=left, op="NOT_IN", right=values)
                    start = j + 1
                
                # Handle BETWEEN operator
                elif op == "BETWEEN":
                    val1 = _parse_value(toks[start + 2])
                    if toks[start + 3].upper() != "AND":
                        raise ValueError("expected AND in BETWEEN clause")
                    val2 = _parse_value(toks[start + 4])
                    left = WhereExpr(left=left, op="BETWEEN", right=(val1, val2))
                    start = start + 5
                
                # Handle standard operators
                elif op not in {"=", "!=", "<", "<=", ">", ">=", "LIKE"}:
                    raise ValueError(f"unsupported operator in WHERE: {op}")
                else:
                    right = _parse_value(toks[start + 2])
                    left = WhereExpr(left=left, op=op, right=right)
                    start = start + 3
            # Check for AND/OR
            if start < len(toks) and toks[start].upper() in {"AND", "OR"}:
                op = toks[start].upper()
                right_expr, next_i = parse_where_expr(start + 1)
                return WhereExpr(left=left, op=op, right=right_expr), next_i
            return left, start

        where = None
        if i < len(toks) and toks[i].upper() == "WHERE":
            where, next_i = parse_where_expr(i + 1)
            i = next_i

        group_by = None
        if i < len(toks) and toks[i].upper() == "GROUP":
            if toks[i + 1].upper() != "BY":
                raise ValueError("expected GROUP BY")
            group_cols = []
            j = i + 2
            while j < len(toks) and toks[j] not in {"HAVING", "ORDER", "LIMIT", "OFFSET"}:
                if toks[j] != ",":
                    group_cols.append(toks[j])
                j += 1
            group_by = group_cols
            i = j

        having = None
        if i < len(toks) and toks[i].upper() == "HAVING":
            having, next_i = parse_where_expr(i + 1)
            i = next_i

        aggregates: list[Aggregate] | None = None
        # detect COUNT, MIN, MAX, AVG, SUM in projection
        agg_patterns = {"COUNT", "MIN", "MAX", "AVG", "SUM"}
        if any(any(c.upper().startswith(p) for p in agg_patterns) for c in cols):
            aggregates = []
            new_cols: list[str] = []
            for c in cols:
                cu = c.upper()
                if cu.startswith("COUNT(DISTINCT"):
                    m = re.fullmatch(r"COUNT\(DISTINCT ([A-Za-z0-9_\.]+)\)", c, flags=re.IGNORECASE)
                    if not m:
                        raise ValueError("expected COUNT(DISTINCT col)")
                    aggregates.append(Aggregate(func="COUNT_DISTINCT", arg=m.group(1)))
                    new_cols.append(c)
                elif cu.startswith("COUNT"):
                    m = re.fullmatch(r"COUNT\((\*|[A-Za-z0-9_\.]+)\)", c, flags=re.IGNORECASE)
                    if not m:
                        raise ValueError("expected COUNT(*) or COUNT(col)")
                    aggregates.append(Aggregate(func="COUNT", arg=m.group(1)))
                    new_cols.append(c)
                elif cu.startswith("MIN"):
                    m = re.fullmatch(r"MIN\(([A-Za-z0-9_\.]+)\)", c, flags=re.IGNORECASE)
                    if not m:
                        raise ValueError("expected MIN(col)")
                    aggregates.append(Aggregate(func="MIN", arg=m.group(1)))
                    new_cols.append(c)
                elif cu.startswith("MAX"):
                    m = re.fullmatch(r"MAX\(([A-Za-z0-9_\.]+)\)", c, flags=re.IGNORECASE)
                    if not m:
                        raise ValueError("expected MAX(col)")
                    aggregates.append(Aggregate(func="MAX", arg=m.group(1)))
                    new_cols.append(c)
                elif cu.startswith("AVG"):
                    m = re.fullmatch(r"AVG\s*\(\s*([A-Za-z0-9_\.]+)\s*\)", c, flags=re.IGNORECASE)
                    if not m:
                        raise ValueError("expected AVG(col)")
                    aggregates.append(Aggregate(func="AVG", arg=m.group(1)))
                    new_cols.append(c)
                elif cu.startswith("SUM"):
                    m = re.fullmatch(r"SUM\s*\(\s*([A-Za-z0-9_\.]+)\s*\)", c, flags=re.IGNORECASE)
                    if not m:
                        raise ValueError("expected SUM(col)")
                    aggregates.append(Aggregate(func="SUM", arg=m.group(1)))
                    new_cols.append(c)
                else:
                    new_cols.append(c)
            cols = new_cols

        order_by = None
        if i < len(toks) and toks[i].upper() == "ORDER":
            if toks[i + 1].upper() != "BY":
                raise ValueError("expected ORDER BY")
            col = toks[i + 2]
            asc = True
            i += 3
            if i < len(toks) and toks[i].upper() in {"ASC", "DESC"}:
                asc = toks[i].upper() == "ASC"
                i += 1
            order_by = (col, asc)

        limit = None
        offset = None
        if i < len(toks) and toks[i].upper() == "LIMIT":
            n = _parse_value(toks[i + 1])
            if not isinstance(n, int) or n < 0:
                raise ValueError("LIMIT must be a non-negative integer")
            limit = n
            i += 2
        if i < len(toks) and toks[i].upper() == "OFFSET":
            n = _parse_value(toks[i + 1])
            if not isinstance(n, int) or n < 0:
                raise ValueError("OFFSET must be a non-negative integer")
            offset = n
        return Select(
            table=table,
            columns=cols,
            where=where,
            join=join,
            group_by=group_by,
            having=having,
            aggregates=aggregates,
            order_by=order_by,
            limit=limit,
            offset=offset,
            distinct=distinct,
        )

    if head == "DELETE":
        # DELETE FROM t [WHERE a = 1]
        if toks[1].upper() != "FROM":
            raise ValueError("expected DELETE FROM")
        table = toks[2]
        where = None
        if len(toks) > 3:
            if toks[3].upper() != "WHERE":
                raise ValueError("expected WHERE")
            left = toks[4]
            op = toks[5].upper()
            if op not in {"=", "!=", "<", "<=", ">", ">=", "LIKE"}:
                raise ValueError("unsupported operator in WHERE")
            right = _parse_value(toks[6])
            where = WhereExpr(left=left, op=op, right=right)
        return Delete(table=table, where=where)

    if head == "UPDATE":
        # UPDATE t SET a = 1, b = "x" [WHERE c = 2]
        table = toks[1]
        i = 2
        if toks[i].upper() != "SET":
            raise ValueError("expected SET")
        i += 1
        set_pairs: list[tuple[str, Any]] = []
        while i < len(toks) and toks[i].upper() != "WHERE":
            col = toks[i]
            if toks[i + 1] != "=":
                raise ValueError("expected '=' in SET")
            val = _parse_value(toks[i + 2])
            set_pairs.append((col, val))
            i += 3
            if i < len(toks) and toks[i] == ",":
                i += 1
        where = None
        if i < len(toks) and toks[i].upper() == "WHERE":
            left = toks[i + 1]
            op = toks[i + 2].upper()
            if op not in {"=", "!=", "<", "<=", ">", ">=", "LIKE"}:
                raise ValueError("unsupported operator in WHERE")
            right = _parse_value(toks[i + 3])
            where = WhereExpr(left=left, op=op, right=right)
        return Update(table=table, set_pairs=set_pairs, where=where)

    if head == "ALTER":
        # ALTER TABLE t ADD COLUMN col TYPE
        if len(toks) < 4 or toks[1].upper() != "TABLE":
            raise ValueError("expected ALTER TABLE")
        table = toks[2]
        if toks[3].upper() == "ADD" and toks[4].upper() == "COLUMN":
            col = toks[5]
            ctype = toks[6].upper()
            return AlterTableAddColumn(table=table, column=(col, ctype))
        if toks[3].upper() == "RENAME" and toks[4].upper() == "TO":
            new_name = toks[5]
            return AlterTableRename(table=table, new_name=new_name)
        raise ValueError("expected ADD COLUMN or RENAME TO")
    if head == "DROP":
        # DROP INDEX name ON table
        # DROP TABLE [IF EXISTS] name
        if len(toks) >= 5 and toks[1].upper() == "INDEX":
            name = toks[2]
            if toks[3].upper() != "ON":
                raise ValueError("expected ON")
            table = toks[4]
            return DropIndex(name=name, table=table)
        if len(toks) >= 3 and toks[1].upper() == "TABLE":
            i = 2
            if_exists = False
            if i + 2 < len(toks) and toks[i].upper() == "IF" and toks[i + 1].upper() == "EXISTS":
                if_exists = True
                i += 2
            name = toks[i]
            return DropTable(name=name, if_exists=if_exists)
        raise ValueError("expected DROP INDEX or DROP TABLE")

    if head == "TRUNCATE":
        # TRUNCATE TABLE name
        if len(toks) < 3 or toks[1].upper() != "TABLE":
            raise ValueError("expected TRUNCATE TABLE")
        return TruncateTable(name=toks[2])

    if head == "SHOW":
        # SHOW DATABASES | SHOW TABLES | SHOW COLUMNS FROM table
        if len(toks) >= 2:
            what = toks[1].upper()
            if what == "DATABASES":
                return ShowDatabases()
            if what == "TABLES":
                return ShowTables()
            if what == "COLUMNS" and len(toks) >= 4 and toks[2].upper() == "FROM":
                return ShowColumns(table=toks[3])
        raise ValueError("unsupported SHOW statement")

    if head == "USE":
        # USE dbname
        if len(toks) != 2:
            raise ValueError("expected USE <database>")
        return UseDatabase(name=toks[1])

    if head in {"DESCRIBE", "DESC"}:
        # DESCRIBE table
        if len(toks) != 2:
            raise ValueError("expected DESCRIBE <table>")
        return DescribeTable(name=toks[1])

    if head == "BEGIN":
        return Begin()

    if head == "COMMIT":
        return Commit()

    if head == "ROLLBACK":
        return Rollback()

    raise ValueError(f"unsupported statement: {head}")



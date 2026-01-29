from __future__ import annotations

import argparse
import os
import sys

from levilite.db import Database


PROMPT = "levi-lite> "


def _read_stmt() -> str | None:
    """
    Reads a SQL statement, supporting multi-line input until ';'.
    Returns None on EOF.
    """
    buf: list[str] = []
    while True:
        try:
            line = input(PROMPT if not buf else "....> ")
        except EOFError:
            return None
        buf.append(line)
        joined = "\n".join(buf).strip()
        if joined.endswith(";"):
            return joined


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="levilite", description="Levi Lite — mini DBMS")
    p.add_argument("--db", default="levilite.db", help="Path to database file")
    args = p.parse_args(argv)

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)

    with Database.open(args.db) as db:
        print("Levi Lite shell. Type .help for help. Ctrl-D to exit.")
        while True:
            stmt = _read_stmt()
            if stmt is None:
                print()
                break
            stmt_stripped = stmt.strip()
            if stmt_stripped.startswith("."):
                if stmt_stripped == ".help":
                    print("Commands: .help, .tables, .schema <table>, .quit")
                elif stmt_stripped == ".tables":
                    for t in db.list_tables():
                        print(t)
                elif stmt_stripped.startswith(".schema"):
                    parts = stmt_stripped.split()
                    if len(parts) != 2:
                        print("Usage: .schema <table>")
                    else:
                        print(db.schema(parts[1]) or "(unknown table)")
                elif stmt_stripped == ".quit":
                    break
                else:
                    print("Unknown command. Type .help")
                continue

            try:
                result = db.execute(stmt)
                if result is not None:
                    cols, rows = result
                    print(" | ".join(cols))
                    print("-+-".join("-" * len(c) for c in cols))
                    for r in rows:
                        print(" | ".join(str(x) for x in r))
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)

    return 0



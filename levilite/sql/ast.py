from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union


class Statement:
    pass


@dataclass(frozen=True)
class CreateTable(Statement):
    name: str
    columns: list[tuple[str, str, bool, bool, bool]]  # (name, type, primary_key, unique, auto_increment)
    if_not_exists: bool = False


@dataclass(frozen=True)
class AlterTableRename(Statement):
    table: str
    new_name: str


@dataclass(frozen=True)
class DropIndex(Statement):
    name: str
    table: str


@dataclass(frozen=True)
class TruncateTable(Statement):
    name: str


@dataclass(frozen=True)
class ShowColumns(Statement):
    table: str


@dataclass(frozen=True)
class Insert(Statement):
    table: str
    columns: list[str]
    values: list[Any]


@dataclass(frozen=True)
class Select(Statement):
    table: str
    columns: list[str]
    where: Optional['WhereExpr']
    join: Optional['Join'] = None
    group_by: Optional[list[str]] = None
    having: Optional['WhereExpr'] = None
    aggregates: Optional[list['Aggregate']] = None
    order_by: Optional[tuple[str, bool]] = None  # (column, asc)
    limit: Optional[int] = None
    offset: Optional[int] = None
    distinct: bool = False


@dataclass(frozen=True)
class Delete(Statement):
    table: str
    where: Optional["WhereExpr"]


@dataclass(frozen=True)
class Update(Statement):
    table: str
    set_pairs: list[tuple[str, Any]]
    where: Optional["WhereExpr"]


@dataclass(frozen=True)
class AlterTableAddColumn(Statement):
    table: str
    column: tuple[str, str]  # (name, type)


@dataclass(frozen=True)
class CreateIndex(Statement):
    name: str
    table: str
    column: str
    unique: bool = False


@dataclass(frozen=True)
class Join:
    right_table: str
    left_col: str
    right_col: str


@dataclass(frozen=True)
class WhereExpr:
    left: Union[str, 'WhereExpr', None]  # column, nested expr, or None
    op: str  # = != < <= > >= LIKE AND OR IN NOT_IN BETWEEN
    right: Union[Any, 'WhereExpr', None, list]


@dataclass(frozen=True)
class Aggregate:
    func: str  # COUNT, COUNT_DISTINCT, MIN, MAX, AVG, SUM
    arg: str  # * or column


@dataclass(frozen=True)
class DropTable(Statement):
    name: str
    if_exists: bool = False


@dataclass(frozen=True)
class CreateDatabase(Statement):
    name: str
    if_not_exists: bool = False


@dataclass(frozen=True)
class UseDatabase(Statement):
    name: str


@dataclass(frozen=True)
class ShowDatabases(Statement):
    pass


@dataclass(frozen=True)
class ShowTables(Statement):
    pass


@dataclass(frozen=True)
class DescribeTable(Statement):
    name: str


@dataclass(frozen=True)
class Begin(Statement):
    pass


@dataclass(frozen=True)
class Commit(Statement):
    pass


@dataclass(frozen=True)
class Rollback(Statement):
    pass



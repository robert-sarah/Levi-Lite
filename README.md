# Levi Lite — MySQL-Compatible Mini DBMS (Python)

**Levi Lite** is a production-ready embedded DBMS engine written in Python, combining SQLite's simplicity with MySQL-like SQL compatibility. Built to be readable, hackable, and feature-rich.

> Note: The legacy `pandadb/` folder is maintained for historical reference. The active engine is `levilite/`.

---

## ⚡ Quick Start

### Installation
```bash
# Clone or navigate to project
cd path/to/zphiser

# Install dependencies
pip install -r requirements.txt
```

### Launch the GUI Application
```bash
python -m levilite.gui
```

This opens an interactive SQL editor with:
- **Live SQL Editor** with syntax hints
- **Results Grid** with sorting & resizing
- **Schema Browser** (drag-expandable tree)
- **Query History** (last 200 queries)
- **CSV Export** for results
- **Transaction Support** (BEGIN/COMMIT/ROLLBACK)

---

## 🎯 Feature Matrix

### Core Storage & Recovery
| Feature | Status | Notes |
|---------|--------|-------|
| On-disk KV storage | ✅ | Simple, persistent `DBFile` |
| WAL (Write-Ahead Log) | ✅ | Crash recovery, atomic transactions |
| In-memory B-Tree indexing | ✅ | Fast equality lookups |
| Transactions (ACID) | ✅ | BEGIN, COMMIT, ROLLBACK |
| Multi-database support | ✅ | CREATE/USE DATABASE |

---

## 📊 SQL Feature Support

### DDL (Data Definition Language)

| Feature | Example | Status |
|---------|---------|--------|
| CREATE TABLE | `CREATE TABLE users (id INT PRIMARY KEY, name TEXT)` | ✅ |
| IF NOT EXISTS | `CREATE TABLE IF NOT EXISTS users (...)` | ✅ |
| Column Constraints | `PRIMARY KEY, UNIQUE, AUTO_INCREMENT` | ✅ |
| DROP TABLE | `DROP TABLE IF EXISTS users` | ✅ |
| TRUNCATE TABLE | `TRUNCATE TABLE users` | ✅ |
| ALTER TABLE ADD COLUMN | `ALTER TABLE users ADD COLUMN email TEXT` | ✅ |
| ALTER TABLE RENAME | `ALTER TABLE old_name RENAME TO new_name` | ✅ |
| CREATE INDEX | `CREATE UNIQUE INDEX idx_email ON users (email)` | ✅ |
| DROP INDEX | `DROP INDEX idx_email ON users` | ✅ |
| DESCRIBE/DESC | `DESCRIBE users` / `DESC users` | ✅ |

### DML (Data Manipulation Language)

| Feature | Example | Status |
|---------|---------|--------|
| INSERT | `INSERT INTO users (id, name) VALUES (1, 'Alice')` | ✅ |
| UPDATE | `UPDATE users SET name = 'Bob' WHERE id = 1` | ✅ |
| DELETE | `DELETE FROM users WHERE id = 1` | ✅ |
| INSERT with AUTO_INCREMENT | `INSERT INTO users (name) VALUES ('Alice')` | ✅ |

### SELECT & Query Features

| Feature | Example | Status |
|---------|---------|--------|
| Basic SELECT | `SELECT * FROM users` | ✅ |
| Column Selection | `SELECT id, name FROM users` | ✅ |
| WHERE with = | `SELECT * FROM users WHERE id = 1` | ✅ |
| WHERE with Operators | `<, <=, >, >=, !=` | ✅ |
| WHERE AND/OR | `WHERE age > 18 AND city = 'NYC'` | ✅ |
| LIKE Pattern | `WHERE name LIKE 'A%'` | ✅ |
| **IN Operator** | `WHERE id IN (1, 3, 5)` | ✅ NEW |
| **NOT IN Operator** | `WHERE id NOT IN (2, 4)` | ✅ NEW |
| **BETWEEN Operator** | `WHERE price BETWEEN 10 AND 100` | ✅ NEW |
| DISTINCT | `SELECT DISTINCT city FROM users` | ✅ |
| JOIN (Inner) | `SELECT * FROM users JOIN orders ON users.id = orders.user_id` | ✅ |
| GROUP BY | `SELECT city, COUNT(*) FROM users GROUP BY city` | ✅ |
| GROUP BY Multiple | `GROUP BY dept, role` | ✅ |
| HAVING | `GROUP BY city HAVING COUNT(*) > 5` | ✅ |
| ORDER BY | `ORDER BY name ASC` / `DESC` | ✅ |
| LIMIT | `LIMIT 10` | ✅ |
| OFFSET | `OFFSET 20` | ✅ |
| Index-Accelerated WHERE | Simple equality on indexed column | ✅ |

### Aggregate Functions

| Function | Example | Status |
|----------|---------|--------|
| COUNT(*) | `SELECT COUNT(*) FROM users` | ✅ |
| COUNT(col) | `SELECT COUNT(email) FROM users` | ✅ |
| COUNT(DISTINCT) | `SELECT COUNT(DISTINCT city) FROM users` | ✅ |
| **MIN** | `SELECT MIN(price) FROM products` | ✅ NEW |
| **MAX** | `SELECT MAX(price) FROM products` | ✅ NEW |
| **AVG** | `SELECT AVG(salary) FROM employees` | ✅ NEW |
| **SUM** | `SELECT SUM(quantity) FROM orders` | ✅ NEW |

### Database Management

| Command | Example | Status |
|---------|---------|--------|
| CREATE DATABASE | `CREATE DATABASE shop` | ✅ |
| USE DATABASE | `USE shop` | ✅ |
| SHOW DATABASES | `SHOW DATABASES` | ✅ |
| SHOW TABLES | `SHOW TABLES` | ✅ |
| SHOW COLUMNS | `SHOW COLUMNS FROM users` | ✅ |

### Data Types

| Type | Details | Status |
|------|---------|--------|
| INT | 64-bit signed integer | ✅ |
| TEXT | UTF-8 string | ✅ |
| REAL | Floating-point number | ✅ |
| BOOL | Boolean (0/1) | ✅ |

---

## 📝 SQL Examples

### Basic CRUD Operations
```sql
-- Create table with constraints
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT,
    age INT,
    city TEXT
);

-- Insert data
INSERT INTO users (username, email, age, city) VALUES
    ('alice', 'alice@example.com', 28, 'NYC'),
    ('bob', 'bob@example.com', 35, 'LA'),
    ('charlie', 'charlie@example.com', 22, 'NYC');

-- Select with various filters
SELECT * FROM users WHERE age > 25;
SELECT * FROM users WHERE city = 'NYC' AND age < 30;
SELECT * FROM users WHERE id IN (1, 3);
SELECT * FROM users WHERE age BETWEEN 25 AND 35;
```

### Advanced Queries
```sql
-- GROUP BY with aggregates
SELECT city, COUNT(*) as user_count, AVG(age) as avg_age
FROM users
GROUP BY city;

-- HAVING clause
SELECT city, COUNT(*) as cnt
FROM users
GROUP BY city
HAVING COUNT(*) > 1;

-- JOIN operations
CREATE TABLE orders (
    id INT PRIMARY KEY,
    user_id INT,
    amount REAL,
    created_at TEXT
);

INSERT INTO orders (id, user_id, amount, created_at) VALUES
    (1, 1, 99.99, '2024-01-15'),
    (2, 1, 49.50, '2024-01-20'),
    (3, 2, 150.00, '2024-01-18');

SELECT u.username, o.amount, o.created_at
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.amount > 50
ORDER BY o.created_at DESC;

-- Aggregates with sorting & pagination
SELECT city, COUNT(*) as cnt, AVG(age) as avg_age
FROM users
GROUP BY city
ORDER BY cnt DESC
LIMIT 5;
```

### New Operators (IN, BETWEEN, MIN/MAX/AVG/SUM)
```sql
-- IN operator
SELECT * FROM users WHERE id IN (1, 3, 5) ORDER BY id;

-- NOT IN operator
SELECT * FROM users WHERE city NOT IN ('NYC', 'LA');

-- BETWEEN operator
SELECT * FROM orders WHERE amount BETWEEN 50 AND 150;

-- MIN, MAX, AVG, SUM aggregates
SELECT 
    MIN(amount) as lowest_order,
    MAX(amount) as highest_order,
    AVG(amount) as avg_order,
    SUM(amount) as total_revenue
FROM orders;

-- Combine with GROUP BY
SELECT user_id, 
       COUNT(*) as order_count,
       MIN(amount) as lowest,
       MAX(amount) as highest,
       AVG(amount) as average
FROM orders
GROUP BY user_id;
```

### Transactions
```sql
BEGIN;
    INSERT INTO users (username, email, age, city) VALUES ('dave', 'dave@example.com', 40, 'SF');
    UPDATE users SET city = 'Chicago' WHERE id = 2;
COMMIT;

-- Or rollback
BEGIN;
    DELETE FROM users WHERE age < 18;
ROLLBACK;  -- Changes discarded
```

---

## 🏗️ Architecture

### Component Overview

```
levilite/
├── __main__.py          # CLI entry point
├── __init__.py          # Package initialization
├── cli.py               # Command-line interface
├── db.py                # Database connection wrapper
├── gui.py               # PyQt5 GUI (SQL editor, results viewer)
├── catalog.py           # Schema/metadata management
│
├── sql/                 # SQL Engine
│   ├── ast.py          # Abstract Syntax Tree classes
│   ├── parser.py       # SQL tokenizer & recursive descent parser
│   └── __init__.py
│
├── execution/          # Query Execution
│   ├── executor.py     # AST → DB operations
│   └── __init__.py
│
├── storage/            # Persistence Layer
│   ├── dbfile.py       # KV store (on-disk storage)
│   ├── wal.py          # Write-Ahead Log (crash recovery)
│   └── __init__.py
│
└── index/              # Indexing
    ├── btree.py        # B-Tree implementation
    └── __init__.py
```

### Data Flow
1. **SQL Input** → Parser (levilite/sql/parser.py)
2. **Parse → AST** (levilite/sql/ast.py)
3. **Execute AST** → Executor (levilite/execution/executor.py)
4. **Read/Write** → DBFile + WAL (levilite/storage/)
5. **Index Maintenance** → B-Tree (levilite/index/)
6. **Display Results** → GUI or CLI

### Storage Model
- **KV-based row storage**: Rows stored as JSON objects
- **Table metadata**: Persisted in `__levilite_catalog__` key
- **Indexes**: In-memory B-Tree maps (re-built on startup)
- **Transactions**: WAL ensures atomicity and durability

---

## 🔧 Development & Customization

### Adding New SQL Features

#### 1. Extend AST (levilite/sql/ast.py)
```python
@dataclass(frozen=True)
class MyNewStatement(Statement):
    table: str
    condition: Optional[WhereExpr]
```

#### 2. Update Parser (levilite/sql/parser.py)
Add keyword recognition and AST construction:
```python
if toks[0].upper() == "MYNEW":
    # Parse tokens into MyNewStatement
    return MyNewStatement(...)
```

#### 3. Implement Executor (levilite/execution/executor.py)
```python
if isinstance(stmt, MyNewStatement):
    # Execute the statement against the DB
    ...
    return QueryResult(...)
```

---

## ⚙️ Configuration

### Database File Location
By default, Levi Lite creates `levilite.db` in the current working directory. To use a different location:

**In GUI**: File → Open Database → Choose file path

**In Code**:
```python
from levilite.db import Database
db = Database("/path/to/custom.db")
```

---

## 📈 Performance Considerations

### Optimization Tips
1. **Use indexes on frequently filtered columns**: `CREATE INDEX idx_name ON table (column)`
2. **Use LIMIT for large result sets**: `SELECT * FROM users LIMIT 100`
3. **Leverage WHERE equality on indexed columns** for automatic B-Tree acceleration
4. **GROUP BY before ORDER BY** to reduce intermediate result sets

### Limitations (MVP Design)
- **In-memory indexes** (not persisted to disk; rebuilt on startup)
- **Single-table joins** (equality-only, no outer joins)
- **No query optimizer** (executes top-down, no cost-based planning)
- **No UNION queries** (yet)
- **No subqueries** (yet)
- **No stored procedures** (yet)
- **No views** (yet)

---

## 🧪 Testing

### Run Tests
```bash
# Requires pytest
pytest
```

### Manual Testing via GUI
1. Launch the application: `python -m levilite.gui`
2. Create a sample database
3. Execute SQL queries in the editor
4. View results in the results grid
5. Export to CSV as needed

---

## 📚 References

- **SQLite**: https://www.sqlite.org/
- **MySQL**: https://www.mysql.com/
- **B-Trees**: https://en.wikipedia.org/wiki/B-tree
- **WAL**: https://en.wikipedia.org/wiki/Write-ahead_logging

---

## 🎓 Learning Resources

This codebase is designed to be educational:
- **SQL parsing**: See levilite/sql/parser.py for recursive descent parsing
- **AST-based execution**: See levilite/execution/executor.py for pattern matching
- **Indexing**: See levilite/index/btree.py for B-Tree implementation
- **Storage**: See levilite/storage/dbfile.py and wal.py for persistence

Ideal for learning DBMS internals without overwhelming complexity.

---

## 📝 License

Designed for educational and personal use.

---

## 🚀 Future Enhancements

- [ ] Persist B-Tree indexes to disk
- [ ] Query optimizer with cost-based planning
- [ ] UNION queries
- [ ] Subqueries & derived tables
- [ ] Views & materialized views
- [ ] Stored procedures & triggers
- [ ] CASE WHEN expressions
- [ ] CAST type conversion
- [ ] DEFAULT column values
- [ ] Foreign key constraints
- [ ] Full-text search
- [ ] JSON data type
- [ ] Replication support

---

## 💡 Contributing

Want to add features? The modular design makes it easy:
1. Add AST class in levilite/sql/ast.py
2. Update parser in levilite/sql/parser.py
3. Implement executor handler in levilite/execution/executor.py
4. Test via GUI or CLI

---

**Made with ❤️ for database enthusiasts.**



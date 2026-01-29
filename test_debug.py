from levilite.db import Database
from levilite.sql.parser import parse_sql
import os

if os.path.exists('test_debug.db'):
    os.remove('test_debug.db')

db = Database.open('test_debug.db')

def execute(sql):
    stmt = parse_sql(sql)
    result = db._executor.execute(stmt)
    return result

# Create test table
execute('CREATE TABLE users (id INT PRIMARY KEY AUTO_INCREMENT, name TEXT)')

# Insert 3 rows
execute('INSERT INTO users (name) VALUES ("A")')
execute('INSERT INTO users (name) VALUES ("B")')
execute('INSERT INTO users (name) VALUES ("C")')

# Test basic select
result = execute('SELECT * FROM users')
print(f"All rows: {len(result.rows)}")
for row in result.rows:
    print(f"  {row}")

# Test NOT IN with specific values
result = execute('SELECT * FROM users WHERE id NOT IN (2)')
print(f"\nNOT IN (2): {len(result.rows)} rows")
for row in result.rows:
    print(f"  {row}")

db.close()
os.remove('test_debug.db')
os.remove('test_debug.db.wal')

#!/usr/bin/env python3
"""Integration tests for new SQL features."""

from levilite.db import Database
from levilite.sql.parser import parse_sql
import os

def test_features():
    # Clean up old test database
    if os.path.exists('test_levilite.db'):
        os.remove('test_levilite.db')
    
    db = Database.open('test_levilite.db')
    
    try:
        # Helper to execute a single statement
        def execute(sql):
            stmt = parse_sql(sql)
            result = db._executor.execute(stmt)
            return result
        
        # Create test table with AUTO_INCREMENT
        execute('CREATE TABLE users (id INT PRIMARY KEY AUTO_INCREMENT, name TEXT, age INT, city TEXT)')
        
        # Insert data (AUTO_INCREMENT should generate IDs)
        execute('INSERT INTO users (name, age, city) VALUES ("Alice", 28, "NYC")')
        execute('INSERT INTO users (name, age, city) VALUES ("Bob", 35, "LA")')
        execute('INSERT INTO users (name, age, city) VALUES ("Charlie", 22, "NYC")')
        execute('INSERT INTO users (name, age, city) VALUES ("Dave", 30, "SF")')
        execute('INSERT INTO users (name, age, city) VALUES ("Eve", 25, "LA")')
        
        print("✅ Table creation and INSERT completed")
        
        # Test IN operator
        result = execute('SELECT * FROM users WHERE id IN (1, 3, 5)')
        assert len(result.rows) == 3, f"Expected 3 rows, got {len(result.rows)}"
        print(f"✅ IN operator: {len(result.rows)} rows")
        
        # Test NOT IN operator
        result = execute('SELECT * FROM users WHERE id NOT IN (2, 4)')
        assert len(result.rows) == 3, f"Expected 3 rows, got {len(result.rows)}"
        print(f"✅ NOT IN operator: {len(result.rows)} rows")
        
        # Test BETWEEN
        result = execute('SELECT * FROM users WHERE age BETWEEN 25 AND 35')
        assert len(result.rows) == 4, f"Expected 4 rows, got {len(result.rows)}"
        print(f"✅ BETWEEN operator: {len(result.rows)} rows")
        
        # Test COUNT aggregate
        result = execute('SELECT COUNT(*) FROM users')
        assert result.rows[0][0] == 5, f"Expected 5, got {result.rows[0][0]}"
        print(f"✅ COUNT(*): {result.rows[0][0]}")
        
        # Test MIN/MAX aggregates
        result = execute('SELECT MIN(age), MAX(age) FROM users')
        assert result.rows[0] == (22, 35), f"Expected (22, 35), got {result.rows[0]}"
        print(f"✅ MIN/MAX: {result.rows[0]}")
        
        # Test AVG aggregate
        result = execute('SELECT AVG(age) FROM users')
        avg_age = result.rows[0][0]
        assert 27 < avg_age < 29, f"Expected ~28, got {avg_age}"
        print(f"✅ AVG(age): {avg_age:.2f}")
        
        # Test SUM aggregate
        result = execute('SELECT SUM(age) FROM users')
        total_age = result.rows[0][0]
        assert total_age == 140, f"Expected 140, got {total_age}"
        print(f"✅ SUM(age): {total_age}")
        
        # Test GROUP BY with aggregates
        result = execute('SELECT city, COUNT(*) FROM users GROUP BY city ORDER BY city')
        assert len(result.rows) == 3, f"Expected 3 cities, got {len(result.rows)}"
        print(f"✅ GROUP BY with COUNT: {result.rows}")
        
        # Test GROUP BY with multiple aggregates
        result = execute('SELECT city, MIN(age), MAX(age), AVG(age) FROM users GROUP BY city')
        assert len(result.rows) == 3, f"Expected 3 rows, got {len(result.rows)}"
        print(f"✅ GROUP BY with MIN/MAX/AVG: {result.rows}")
        
        # Test HAVING clause
        result = execute('SELECT city, COUNT(*) FROM users GROUP BY city HAVING COUNT(*) > 1')
        assert len(result.rows) == 2, f"Expected 2 cities, got {len(result.rows)}"
        print(f"✅ HAVING clause: {result.rows}")
        
        # Test WHERE with AND/OR and IN
        result = execute('SELECT * FROM users WHERE city IN ("NYC", "LA") AND age > 25')
        assert len(result.rows) == 3, f"Expected 3 rows, got {len(result.rows)}"
        print(f"✅ WHERE with AND/OR and IN: {len(result.rows)} rows")
        
        print("\n🎉 All tests passed! New features working correctly.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
        if os.path.exists('test_levilite.db'):
            os.remove('test_levilite.db')
        if os.path.exists('test_levilite.db.wal'):
            os.remove('test_levilite.db.wal')

if __name__ == '__main__':
    test_features()

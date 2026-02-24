import sqlite3
import traceback

try:
    with sqlite3.connect('db.sqlite3', timeout=10) as conn:
        cursor = conn.cursor()
        print("Checking tables...")
        # Check if is_completed exists in finance_savingsgoal
        cursor.execute("PRAGMA table_info(finance_savingsgoal);")
        columns = [info[1] for info in cursor.fetchall()]
        print("Columns: ", columns)
        
        if 'is_completed' not in columns:
            print("Adding is_completed column...")
            cursor.execute("ALTER TABLE finance_savingsgoal ADD COLUMN is_completed bool DEFAULT 0 NOT NULL;")
            conn.commit()
            print("Column added successfully.")
        else:
            print("Column is_completed already exists.")
except Exception as e:
    print("MIGRATION ERROR:", traceback.format_exc())

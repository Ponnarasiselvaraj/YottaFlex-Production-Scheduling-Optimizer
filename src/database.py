from pathlib import Path
import sqlite3
import pandas as pd

def export_sqlite(data_dir="data"):
    d=Path(data_dir); db=d/"production.db"
    with sqlite3.connect(db) as conn:
        for f in d.glob("*.csv"):
            pd.read_csv(f).to_sql(f.stem,conn,if_exists="replace",index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_operations_order ON operations(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_schedules_machine ON operation_schedules(machine_id)")
    return db

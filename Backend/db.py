import pyodbc
import pandas as pd
import config


def get_connection():
    return pyodbc.connect(
        f"DRIVER={{{config.DB_DRIVER}}};"
        f"SERVER={config.DB_SERVER};"
        f"DATABASE={config.DB_NAME};"
        f"UID={config.DB_USER};"
        f"PWD={config.DB_PASSWORD};"
    )


def run_query(sql, params=()):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if cur.description is None:
            return pd.DataFrame()

        columns = [c[0] for c in cur.description]
        rows = cur.fetchall()
        return pd.DataFrame.from_records(rows, columns=columns)
    finally:
        conn.close()


def get_table_columns():
    sql = """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """
    df = run_query(sql, (config.TABLE_SCHEMA, config.TABLE_NAME))
    return df["COLUMN_NAME"].tolist() if not df.empty else []
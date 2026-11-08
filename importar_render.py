import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

RENDER_DATABASE_URL = os.getenv("RENDER_DATABASE_URL") or os.getenv("SUPABASE_CONNECTION_STRING")
if not RENDER_DATABASE_URL:
    raise ValueError("Define RENDER_DATABASE_URL o SUPABASE_CONNECTION_STRING")
print(f"Conectando a: {RENDER_DATABASE_URL[:50]}...")


def run_sql_file(conn, filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"[OK] Schema ejecutado desde {filepath}")


def load_json(filepath):
    with open(filepath, "r", encoding="latin-1") as f:
        return json.load(f)


from psycopg2.extras import Json

def cast_values(row: dict) -> list:
    vals = []
    for v in row.values():
        if isinstance(v, dict):
            vals.append(Json(v))
        else:
            vals.append(v)
    return vals

def import_data(conn, table: str, rows: list[dict]):
    if not rows:
        print(f"[SKIP] {table}: sin datos")
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(columns))
    cols_str = ", ".join(columns)
    sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING"

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, cast_values(row))
    conn.commit()
    print(f"[OK] {table}: {len(rows)} filas importadas")


def main():
    conn = psycopg2.connect(RENDER_DATABASE_URL, cursor_factory=RealDictCursor)

    # 1. Schema
    run_sql_file(conn, "migracion_render.sql")

    # 2. Import data
    import_data(conn, "preguntas", load_json("data_preguntas.json"))
    import_data(conn, "empresas", load_json("data_empresas.json"))
    import_data(conn, "evaluaciones", load_json("data_evaluaciones.json"))

    conn.close()
    print("\n[MIGRACION COMPLETADA]")


if __name__ == "__main__":
    main()

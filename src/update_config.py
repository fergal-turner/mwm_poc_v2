"""Sync indicator / dimension config CSVs to Supabase.

Usage (from repo root):
    python -m src.update_config indicators config/indicators_config.csv
    python -m src.update_config dimensions config/dimensions_config.csv
    python -m src.update_config indicators                # uses default CSV path

If the table does not exist it is created, then rows are upserted on `id`.
Creating a table needs a direct Postgres connection, since the Supabase REST
API cannot run DDL. Set SUPABASE_DB_URL in .env (Project Settings > Database >
Connection string). Without it the CREATE TABLE SQL is printed to run manually.
"""
import argparse
import os
import sys

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

TABLES = {
    "indicators": ("indicators", "config/indicators_config.csv"),
    "dimensions": ("dimensions", "config/dimensions_config.csv"),
    "drivers": ("drivers", "synthetic_v2/config/drivers.csv"),
    "driver_indicators": ("driver_indicators", "synthetic_v2/config/driver_indicators.csv"),
}
BOOL_COLS = {"active"}
BATCH_SIZE = 500


def build_create_sql(table, df):
    cols = []
    for c in df.columns:
        if c == "id":
            cols.append('"id" text primary key')
        elif c in BOOL_COLS:
            cols.append(f'"{c}" boolean')
        else:
            cols.append(f'"{c}" text')
    return f'create table public."{table}" (\n  ' + ",\n  ".join(cols) + "\n);"


def table_exists(supabase, table):
    try:
        supabase.table(table).select("id").limit(1).execute()
        return True
    except Exception as e:
        msg = str(e)
        if "PGRST205" in msg or "does not exist" in msg or "schema cache" in msg:
            return False
        raise


def create_table(table, df):
    sql = build_create_sql(table, df)
    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        print(f"Table '{table}' does not exist and SUPABASE_DB_URL is not set.\n"
              f"Run this SQL in the Supabase SQL editor (or set SUPABASE_DB_URL), then re-run:\n\n{sql}")
        sys.exit(1)
    import psycopg2
    with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql)
        cur.execute("notify pgrst, 'reload schema';")
    print(f"Created table '{table}'.")


def add_missing_columns(table, df, existing_cols):
    missing = [c for c in df.columns if c not in existing_cols]
    if not missing:
        return
    db_url = os.getenv("SUPABASE_DB_URL")
    stmts = [f'alter table public."{table}" add column if not exists "{c}" '
             f'{"boolean" if c in BOOL_COLS else "text"};' for c in missing]
    if not db_url:
        print("CSV has columns not in the table. Run this SQL then re-run:\n" + "\n".join(stmts))
        sys.exit(1)
    import psycopg2
    with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
        for s in stmts:
            cur.execute(s)
        cur.execute("notify pgrst, 'reload schema';")
    print(f"Added columns to '{table}': {', '.join(missing)}")


def load_csv(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    if "id" not in df.columns:
        sys.exit(f"{path} must contain an 'id' column.")
    df = df.apply(lambda s: s.str.strip())
    dupes = df[df["id"].duplicated()]["id"].tolist()
    if dupes:
        sys.exit(f"Duplicate ids in CSV: {dupes}")
    if (df["id"] == "").any():
        sys.exit("CSV contains rows with an empty id.")
    return df


def to_records(df):
    records = []
    for row in df.to_dict(orient="records"):
        rec = {}
        for k, v in row.items():
            if v == "":
                rec[k] = None
            elif k in BOOL_COLS:
                rec[k] = v.lower() in ("true", "1", "yes", "t")
            else:
                rec[k] = v
        records.append(rec)
    return records


def sync_config(kind, csv_path=None):
    load_dotenv()
    table, default_path = TABLES[kind]
    df = load_csv(csv_path or default_path)

    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    if table_exists(supabase, table):
        print(f"Table '{table}' exists - upserting.")
        existing = supabase.table(table).select("*").limit(1).execute().data
        if existing:
            add_missing_columns(table, df, existing[0].keys())
    else:
        print(f"Table '{table}' not found - creating.")
        create_table(table, df)

    records = to_records(df)
    for i in range(0, len(records), BATCH_SIZE):
        supabase.table(table).upsert(records[i:i + BATCH_SIZE], on_conflict="id").execute()
    print(f"Upserted {len(records)} rows into '{table}'.")


def main():
    p = argparse.ArgumentParser(description="Sync config CSV to Supabase.")
    p.add_argument("kind", choices=TABLES.keys())
    p.add_argument("csv", nargs="?", help="CSV path (defaults to config/<kind>_config.csv)")
    args = p.parse_args()
    sync_config(args.kind, args.csv)


if __name__ == "__main__":
    main()

Query Execution Plans — Quick README

This short README explains how to use the three helper scripts in this folder to:
  1) create the TPC-H database schema (database_init.py),
  2) convert .tbl reference files to CSV and load them into PostgreSQL (helper/tbl_to_csv.py), and
  3) obtain a query execution plan (QEP) programmatically using preprocessing.py.

Prerequisites
- PostgreSQL running and accessible (defaults assume localhost:5432)
- Database parameter used can be found in database_init.py:

Files
- database_init.py
  Creates the TPC-H database schema (public region, nation, part, supplier, partsupp, customer, orders, lineitem).
  Usage: run on a machine with access to PostgreSQL and appropriate credentials.

- helper/tbl_to_csv.py
  Converts TPC-H .tbl files (reference data) into CSV files and can load those CSVs into PostgreSQL.
  The script embeds defaults for DB connection and data paths — edit the DB params in the file if needed.

- preprocessing.py
  Contains functions to connect to the database and retrieve/extract execution plans and schema metadata.
  Functions of interest:
    - connect_database(db_config: dict)
    - get_postgresql_plan(connection, query: str, schema_name: str = "public") -> dict
    - extract_schema(db_config: dict, schema_name: str) -> dict
    - get_ai_query_execution_plan(sql_query: str, system_prompt: str | None, model: str | None) -> dict

- TPC-H V3.0.1
  The TPC-H database can be found under ./database folder

- csv data
  The converted csv data are under ./database/csv_data folder


Quick usage: 1) Convert .tbl -> CSV
- Place your reference data under the expected reference folder (the script uses a REF_DATA_ROOT relative to the project). By default the helper expects the TPC-H reference folder tree:
  6548BB6C-9DED-4BED-90DC-3218D7D750CC-TPC-H-Tool/TPC-H V3.0.1/ref_data/<scale_folder>/

- Convert all .tbl files in a scale folder to CSV (writes to Query-Execution-Plans/database/csv_data/<scale_folder>/):

  python helper/tbl_to_csv.py 1

  Optional flags:
    --remove-delete     Remove files with "delete" in the name from the source folder during conversion.

- Convert a specific scale folder (e.g., scale 10):

  python helper/tbl_to_csv.py 10

Quick usage: 2) Load CSVs into PostgreSQL (after creating schema)
- Create the database schema first (see next step) or ensure tables exist in the target schema.

- Load CSV files into PostgreSQL (uses DB_PARAMS inside helper/tbl_to_csv.py by default):

  python helper/tbl_to_csv.py load-csv 1

  Optional flags for load-csv:
    --include-updates    Include .tbl.u (update) files when scanning CSVs
    --truncate           Truncate target tables before loading (respects load order)
    --strict             Raise on any CSV load error (default is to skip faulty files)

Notes:
- The loader checks target table column counts and will normalize rows where necessary (some TPC-H variations are handled).
- If your DB credentials/host differ from the defaults, edit DB_PARAMS near the top of helper/tbl_to_csv.py or run the functions programmatically with a custom db_params dict.

Quick usage: 3) Create/prepare the database schema
- The database-init script creates the TPC-H tables in the "public" schema using psycopg2 and the DB_PARAMS defined at the top of database_init.py.

  python database_init.py

- If you need a different database name/credentials, update DB_PARAMS at the top of database_init.py before running.
- The script drops existing TPC-H tables (IF EXISTS) and recreates them. It commits once all tables are created.

Programmatic usage: get a QEP from preprocessing.py
- Example: obtain a PostgreSQL JSON plan for a SELECT query.

  Create a small script (example_get_plan.py):

  from preprocessing import connect_database, get_postgresql_plan

  db_config = {
      "host": "localhost",
      "database": "TPC-H",
      "user": "postgres",
      "password": "postgres",
      "port": 5432,
  }

  conn = connect_database(db_config)

  try:
      sql_query = "SELECT * FROM public.customer LIMIT 10"
      plan = get_postgresql_plan(conn, sql_query, schema_name="public")
      import json
      print(json.dumps(plan, indent=2))
  finally:
      conn.close()

- Requirements/notes:
  - get_postgresql_plan only accepts SELECT queries and returns the JSON plan (the Plan node) from EXPLAIN (FORMAT JSON).
  - connect_database calls psycopg.connect(**db_config) — supply the same keys used in database_init.py (host, database, user, password, port).

AI-assisted QEP (optional)
- preprocessing.py also exposes get_ai_query_execution_plan(sql_query) which uses an external AI (Gemini) via google-genai. To use it:
  - Set GEMINI_API_KEY in the environment or add it to .env one level up (the script will search for .env near the file).
  - Install google-genai (pip install google-genai).
  - Call get_ai_query_execution_plan(sql_query) — the function returns parsed JSON recommended-plan structure.

Example snippet (AI QEP):

  from preprocessing import get_ai_query_execution_plan

  q = "SELECT l_orderkey, sum(l_extendedprice * (1 - l_discount)) as revenue FROM public.lineitem GROUP BY l_orderkey ORDER BY revenue DESC LIMIT 5"
  ai_plan = get_ai_query_execution_plan(q)
  import json
  print(json.dumps(ai_plan, indent=2))

Troubleshooting
- If conversion fails: confirm REF_DATA_ROOT and the scale folder exist and contain .tbl files.
- If CSV load fails: ensure the database schema exists and that DB_PARAMS (host/database/user/password/port) match your Postgres instance.
- If get_postgresql_plan raises an error, confirm the connection configuration and that the query is a valid SELECT.
- If AI plan fails: ensure GEMINI_API_KEY (or AI_API_KEY_GEMINI) is present in environment or .env and google-genai is installed.
- If build tpch.vcproj failed, try build tpch.vcxproj instead (or find generated results in ref_data)
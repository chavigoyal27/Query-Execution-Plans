
import os
import sys
from pathlib import Path
import json

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from preprocessing import *


db_config = {
    "dbname": "sc3020_test",
    "user": "postgres",
    "password": os.environ["SC3020_DB_PASSWORD"],
    "host": "localhost",
    "port": 5432
}

with connect_database(db_config) as connection:

    print("Connected successfully!")

    print("Schemas:", list_schemas(connection))

    plan = get_postgresql_plan(
    connection,
    """
    SELECT s.name, e.course_name
    FROM students s
    JOIN enrollments e
        ON s.student_id = e.student_id
    """,
    schema_name="public"
    )

    print("PostgreSQL QEP:")
    print(json.dumps(plan, indent=4))

    schema = extract_schema(db_config, "public")

    print("\nDATABASE SCHEMA:")
    print(json.dumps(schema, indent=4))


    column_stats = get_column_statistics(
        connection,
        "public"
    )

    print("\nCOLUMN STATISTICS:")
    print(json.dumps(column_stats, indent=4, default=str))

    optimizer_settings = get_optimizer_settings(connection)

    print("\nOPTIMIZER SETTINGS:")
    print(json.dumps(optimizer_settings, indent=4))


    #print("Available databases:", list_databases(connection))
    

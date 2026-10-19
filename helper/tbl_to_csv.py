import csv
import sys
import tempfile
from pathlib import Path

import psycopg2
from psycopg2 import sql

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REF_DATA_ROOT = PROJECT_ROOT / "Query-Execution-Plans" / "database" / "TPC-H V3.0.1" / "ref_data"
CSV_OUTPUT_ROOT = PROJECT_ROOT / "Query-Execution-Plans" / "database" / "csv_data"
DB_PARAMS = {
    "host": "localhost",
    "database": "TPC-H",
    "user": "postgres",
    "password": "postgres",
    "port": "5432",
}
TABLE_LOAD_ORDER = {
    "region": 1,
    "nation": 2,
    "part": 3,
    "supplier": 4,
    "partsupp": 5,
    "customer": 6,
    "orders": 7,
    "lineitem": 8,
}
TPCH_REGION_ROWS = [
    (0, "AFRICA"),
    (1, "AMERICA"),
    (2, "ASIA"),
    (3, "EUROPE"),
    (4, "MIDDLE EAST"),
]
TPCH_NATION_ROWS = [
    (0, "ALGERIA", 0),
    (1, "ARGENTINA", 1),
    (2, "BRAZIL", 1),
    (3, "CANADA", 1),
    (4, "EGYPT", 4),
    (5, "ETHIOPIA", 0),
    (6, "FRANCE", 3),
    (7, "GERMANY", 3),
    (8, "INDIA", 2),
    (9, "INDONESIA", 2),
    (10, "IRAN", 4),
    (11, "IRAQ", 4),
    (12, "JAPAN", 2),
    (13, "JORDAN", 4),
    (14, "KENYA", 0),
    (15, "MOROCCO", 0),
    (16, "MOZAMBIQUE", 0),
    (17, "PERU", 1),
    (18, "CHINA", 2),
    (19, "ROMANIA", 3),
    (20, "SAUDI ARABIA", 4),
    (21, "VIETNAM", 2),
    (22, "RUSSIA", 3),
    (23, "UNITED KINGDOM", 3),
    (24, "UNITED STATES", 1),
]

# Convert all .tbl source files from one ref_data subfolder into CSV files.
def convert_tbl_files_to_csv(scale_folder="1", remove_delete_files=False):

    source_folder = REF_DATA_ROOT / scale_folder
    if not source_folder.exists() or not source_folder.is_dir():
        raise FileNotFoundError(f"Source folder does not exist: {source_folder}")

    output_folder = CSV_OUTPUT_ROOT / scale_folder
    output_folder.mkdir(parents=True, exist_ok=True)

    converted_count = 0
    skipped_delete_count = 0
    removed_delete_count = 0

    for file_path in sorted(source_folder.iterdir()):
        if not file_path.is_file():
            continue

        file_name_lower = file_path.name.lower()

        if "delete" in file_name_lower:
            skipped_delete_count += 1
            if remove_delete_files:
                file_path.unlink()
                removed_delete_count += 1
            continue

        if ".tbl" not in file_name_lower:
            continue

        csv_path = output_folder / f"{file_path.name}.csv"
        with file_path.open("r", encoding="utf-8", newline="") as tbl_file, csv_path.open(
            "w", encoding="utf-8", newline=""
        ) as csv_file:
            writer = csv.writer(csv_file)
            for line in tbl_file:
                raw_line = line.rstrip("\r\n")
                if not raw_line:
                    continue
                if raw_line.endswith("|"):
                    raw_line = raw_line[:-1]

                writer.writerow(raw_line.split("|"))

        converted_count += 1

    print(f"Converted {converted_count} files from '{source_folder}' to '{output_folder}'.")
    print(f"Skipped {skipped_delete_count} delete file(s).")
    if remove_delete_files:
        print(f"Removed {removed_delete_count} delete file(s) from source folder.")

    return output_folder


def _extract_table_name_from_csv(csv_path):
    file_name = csv_path.name.lower()
    if not file_name.endswith(".csv") or ".tbl." not in file_name:
        return None
    return file_name.split(".tbl.", 1)[0]


# Load CSV files into PostgreSQL tables
# Ensure that the database tables exist and are ready for data loading
# Run database_init.py if the database tables have not been created yet
def _normalize_csv_for_table(csv_path, expected_column_count, table_name):
    transformed_rows = 0
    total_rows = 0

    temporary_file = tempfile.NamedTemporaryFile("w+", encoding="utf-8", newline="", delete=False)
    temp_path = Path(temporary_file.name)

    try:
        writer = csv.writer(temporary_file)
        with csv_path.open("r", encoding="utf-8", newline="") as input_file:
            reader = csv.reader(input_file)
            for row_number, row in enumerate(reader, start=1):
                total_rows += 1
                current_row = row

                # Compatibility path for the current database schema:
                # supplier table may not include s_name.
                if table_name == "supplier" and len(current_row) == 7 and expected_column_count == 6:
                    current_row = [current_row[0], *current_row[2:]]
                    transformed_rows += 1

                if len(current_row) != expected_column_count:
                    raise ValueError(
                        f"Column mismatch in {csv_path.name} at row {row_number}: "
                        f"expected {expected_column_count}, got {len(current_row)}"
                    )

                writer.writerow(current_row)
    except Exception:
        temporary_file.close()
        temp_path.unlink(missing_ok=True)
        raise

    temporary_file.flush()
    temporary_file.seek(0)
    return temporary_file, temp_path, total_rows, transformed_rows


def _seed_tpch_reference_tables(cursor, schema):
    for region_key, region_name in TPCH_REGION_ROWS:
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.region (r_regionkey, r_name)
                VALUES (%s, %s)
                ON CONFLICT (r_regionkey) DO NOTHING
                """
            ).format(sql.Identifier(schema)),
            (region_key, region_name),
        )

    for nation_key, nation_name, region_key in TPCH_NATION_ROWS:
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.nation (n_nationkey, n_name, n_regionkey)
                VALUES (%s, %s, %s)
                ON CONFLICT (n_nationkey) DO NOTHING
                """
            ).format(sql.Identifier(schema)),
            (nation_key, nation_name, region_key),
        )


def load_csv_files_to_postgres(
    scale_folder="1",
    include_updates=False,
    truncate_before_load=False,
    schema="public",
    seed_reference_data=True,
    strict_load=False,
    db_params=None,
):

    source_folder = CSV_OUTPUT_ROOT / scale_folder
    if not source_folder.exists() or not source_folder.is_dir():
        raise FileNotFoundError(f"CSV source folder does not exist: {source_folder}")

    csv_files = []
    for file_path in sorted(source_folder.iterdir()):
        if not file_path.is_file() or file_path.suffix.lower() != ".csv":
            continue

        file_name_lower = file_path.name.lower()
        if not include_updates and ".tbl.u" in file_name_lower:
            continue

        table_name = _extract_table_name_from_csv(file_path)
        if table_name is None:
            continue

        csv_files.append((table_name, file_path))

    csv_files.sort(key=lambda item: (TABLE_LOAD_ORDER.get(item[0], 999), item[1].name.lower()))

    if not csv_files:
        raise ValueError(f"No eligible CSV files found in: {source_folder}")

    connection = None
    db_config = db_params or DB_PARAMS
    missing_table_names = set()
    loaded_files_count = 0
    skipped_load_files = []

    try:
        connection = psycopg2.connect(**db_config)

        existing_tables = {}
        with connection.cursor() as cursor:
            for table_name, _ in csv_files:
                if table_name in existing_tables:
                    continue

                qualified_table_name = f"{schema}.{table_name}"
                cursor.execute("SELECT to_regclass(%s)", (qualified_table_name,))
                existing_tables[table_name] = cursor.fetchone()[0] is not None

            cursor.execute("SELECT to_regclass(%s)", (f"{schema}.region",))
            has_region_table = cursor.fetchone()[0] is not None
            cursor.execute("SELECT to_regclass(%s)", (f"{schema}.nation",))
            has_nation_table = cursor.fetchone()[0] is not None

            if seed_reference_data and has_region_table and has_nation_table:
                _seed_tpch_reference_tables(cursor, schema)
                print(f"Seeded {schema}.region/{schema}.nation with TPC-H keys (if missing).")

            if truncate_before_load:
                for table_name in sorted(
                    {table for table, _ in csv_files if existing_tables.get(table)},
                    key=lambda table: TABLE_LOAD_ORDER.get(table, 999),
                    reverse=True,
                ):
                    truncate_sql = sql.SQL("TRUNCATE TABLE {}.{} CASCADE").format(
                        sql.Identifier(schema),
                        sql.Identifier(table_name),
                    )
                    cursor.execute(truncate_sql)
                    print(f"Truncated {schema}.{table_name} before load.")

            for table_name, csv_path in csv_files:
                if not existing_tables.get(table_name):
                    missing_table_names.add(table_name)
                    continue

                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    """,
                    (schema, table_name),
                )
                expected_column_count = cursor.fetchone()[0]
                if expected_column_count == 0:
                    missing_table_names.add(table_name)
                    continue

                copy_sql = sql.SQL("COPY {}.{} FROM STDIN WITH (FORMAT CSV)").format(
                    sql.Identifier(schema),
                    sql.Identifier(table_name),
                )

                normalized_file = None
                normalized_path = None
                try:
                    normalized_file, normalized_path, total_rows, transformed_rows = _normalize_csv_for_table(
                        csv_path=csv_path,
                        expected_column_count=expected_column_count,
                        table_name=table_name,
                    )
                    cursor.execute("SAVEPOINT csv_file_load")
                    try:
                        cursor.copy_expert(copy_sql.as_string(connection), normalized_file)
                        cursor.execute("RELEASE SAVEPOINT csv_file_load")
                    except (Exception, psycopg2.Error) as load_error:
                        cursor.execute("ROLLBACK TO SAVEPOINT csv_file_load")
                        cursor.execute("RELEASE SAVEPOINT csv_file_load")
                        error_summary = str(load_error).strip().splitlines()[0]
                        skipped_load_files.append((csv_path.name, table_name, error_summary))
                        print(
                            f"Skipped {csv_path.name} for {schema}.{table_name}: {error_summary}"
                        )
                        if strict_load:
                            raise
                        continue
                finally:
                    if normalized_file:
                        normalized_file.close()
                    if normalized_path:
                        normalized_path.unlink(missing_ok=True)

                loaded_files_count += 1
                if transformed_rows > 0:
                    print(
                        f"Loaded {csv_path.name} into {schema}.{table_name} "
                        f"({transformed_rows}/{total_rows} row(s) transformed)."
                    )
                else:
                    print(f"Loaded {csv_path.name} into {schema}.{table_name}.")

        connection.commit()

    except (Exception, psycopg2.Error):
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            connection.close()

    if missing_table_names:
        print(
            "Skipped loading files for missing table(s): "
            + ", ".join(sorted(missing_table_names))
            + "."
        )

    if skipped_load_files:
        print(f"Skipped {len(skipped_load_files)} file(s) due to load errors:")
        for file_name, table_name, error_summary in skipped_load_files:
            print(f" - {file_name} -> {schema}.{table_name}: {error_summary}")

    print(f"Loaded {loaded_files_count} CSV file(s) into PostgreSQL from '{source_folder}'.")
    return loaded_files_count


if __name__ == "__main__":
    # Convert: python helper/tbl_to_csv.py [scale_folder] [--remove-delete]
    # Load:    python helper/tbl_to_csv.py load-csv [scale_folder] [--include-updates] [--truncate] [--strict]
    arguments = sys.argv[1:]

    if arguments and arguments[0] == "load-csv":
        selected_scale_folder = "1"
        include_updates = "--include-updates" in arguments
        truncate_before_load = "--truncate" in arguments
        strict_load = "--strict" in arguments

        for argument in arguments[1:]:
            if not argument.startswith("--"):
                selected_scale_folder = argument
                break

        load_csv_files_to_postgres(
            scale_folder=selected_scale_folder,
            include_updates=include_updates,
            truncate_before_load=truncate_before_load,
            strict_load=strict_load,
        )
    else:
        selected_scale_folder = "1"
        remove_delete = "--remove-delete" in arguments

        for argument in arguments:
            if not argument.startswith("--"):
                selected_scale_folder = argument
                break

        convert_tbl_files_to_csv(scale_folder=selected_scale_folder, remove_delete_files=remove_delete)

import psycopg
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

# Connect to the selected PostgreSQL database
def connect_database(db_config: dict):
    return psycopg.connect(**db_config)

# Get the query execution plan from PostgreSQL
def get_postgresql_plan(
    connection,
    query: str,
    schema_name: str = "public"
) -> dict:

    if not query or not query.strip():
        raise ValueError("SQL query cannot be empty.")

    query = query.strip()

    if not query.upper().startswith("SELECT "):
        raise ValueError("Only SELECT queries are supported.")

    #Retrieve QEP
    try:
        with connection.transaction():
            with connection.cursor() as cursor:

                # Use the selected schema
                cursor.execute(
                    "SELECT set_config('search_path', %s, true)",
                    (schema_name,)
                )

                # Get the QEP in JSON format
                cursor.execute(
                    "EXPLAIN (FORMAT JSON) " + query,
                    prepare=False
                )

                result = cursor.fetchone()[0]

        return result[0]["Plan"]

    except psycopg.Error as error:
        raise RuntimeError(
            f"PostgreSQL QEP generation failed: {error}"
        ) from error


# Get all available schemas in the database
def list_schemas(connection) -> list:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN (
                'information_schema', 'pg_catalog'
            )
            AND schema_name NOT LIKE 'pg_toast%'
            AND schema_name NOT LIKE 'pg_temp_%'
            ORDER BY schema_name
        """)

        return [row[0] for row in cursor.fetchall()]

# Get table details from the selected schema
def extract_schema(db_config: dict, schema_name: str) -> dict:

    # Create connection using SQLAlchemy
    url = URL.create(
        drivername="postgresql+psycopg",
        username=db_config["user"],
        password=db_config["password"],
        host=db_config.get("host", "localhost"),
        port=db_config.get("port", 5432),
        database=db_config["dbname"]
    )

    engine = create_engine(url)

    try:
        inspector = inspect(engine)
        
        # Check if schema exists
        if schema_name not in inspector.get_schema_names():
            raise ValueError(
                f"Schema '{schema_name}' does not exist."
            )

        tables = {}

        # Get all tables in the schema
        table_names = inspector.get_table_names(
            schema=schema_name
        )

        for table_name in table_names:

            # Extracting columns and their data types
            columns = [
                {
                    "name": column["name"],
                    "data_type": str(column["type"]),
                    "nullable": column["nullable"]
                }
                for column in inspector.get_columns(
                    table_name,
                    schema=schema_name
                )
            ]

            # Extracting primary-key columns.
            primary_key = inspector.get_pk_constraint(
                table_name,
                schema=schema_name
            ).get("constrained_columns", [])

            # Extracting foreign-key relationships
            foreign_keys = []

            for fk in inspector.get_foreign_keys(
                table_name,
                schema=schema_name
            ):
                foreign_keys.append({
                    "columns": fk["constrained_columns"],
                    "referenced_schema": fk["referred_schema"],
                    "referenced_table": fk["referred_table"],
                    "referenced_columns": fk["referred_columns"]
                })

            # Extracting indexes
            indexes = []

            for index in inspector.get_indexes(
                table_name,
                schema=schema_name
            ):
                options = index.get("dialect_options", {})
                indexes.append({
                    "name": index["name"],
                    "columns": index.get("column_names", []),
                    "expressions": index.get("expressions", []),
                    "unique": index.get("unique", False),
                    "type": options.get("postgresql_using", "btree"),
                    "condition": options.get("postgresql_where")
                })

            # Get estimated table rows and pages
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT c.reltuples, c.relpages
                        FROM pg_catalog.pg_class AS c
                        JOIN pg_catalog.pg_namespace AS n
                            ON n.oid = c.relnamespace
                        WHERE n.nspname = :schema_name
                        AND c.relname = :table_name
                        AND c.relkind IN ('r', 'p')
                    """),
                    {
                        "schema_name": schema_name,
                        "table_name": table_name
                    }
                ).fetchone()

            statistics = {
                "estimated_rows": (
                    float(result[0])
                    if result is not None and result[0] >= 0
                    else None
                ),
                "estimated_pages": (
                    int(result[1])
                    if result is not None and result[1] >= 0
                    else None
                )
            }

            # Store all details for the current table
            tables[table_name] = {
                "columns": columns,
                "primary_key": primary_key,
                "foreign_keys": foreign_keys,
                "indexes": indexes,
                "statistics": statistics
            }

        return {
            "database": db_config["dbname"],
            "schema_name": schema_name,
            "tables": tables
        }

    finally:
        engine.dispose()


# Get available databases from PostgreSQL
def list_databases(connection) -> list:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT datname
            FROM pg_database
            WHERE datistemplate = false
              AND datallowconn = true
              AND has_database_privilege(oid, 'CONNECT')
            ORDER BY datname
        """)

        return [row[0] for row in cursor.fetchall()]


def get_column_statistics(connection, schema_name: str) -> dict:

    #Get column-level statistics from PostgreSQL.
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                tablename,attname,
                null_frac,n_distinct,
                avg_width,most_common_vals::text,
                most_common_freqs,
                histogram_bounds::text
            FROM pg_catalog.pg_stats
            WHERE schemaname = %s
            ORDER BY tablename, attname
        """, (schema_name,))

        rows = cursor.fetchall()

    statistics = {}

    for row in rows:
        (
            table_name,column_name,
            null_fraction,distinct_values,
            average_width,common_values,
            common_frequencies,histogram
        ) = row

        if table_name not in statistics:
            statistics[table_name] = {}

        statistics[table_name][column_name] = {
            "null_fraction": null_fraction,
            "distinct_values": distinct_values,
            "average_width": average_width,
            "most_common_values": common_values,
            "most_common_frequencies": common_frequencies,
            "histogram_bounds": histogram
        }

    return statistics


def get_optimizer_settings(connection) -> dict:
    """
    Get PostgreSQL settings that influence query planning.
    """

    settings_to_get = [
        "seq_page_cost","random_page_cost",
        "cpu_tuple_cost","cpu_index_tuple_cost",
        "cpu_operator_cost","effective_cache_size",
        "work_mem","hash_mem_multiplier","max_parallel_workers_per_gather",
        "parallel_setup_cost","parallel_tuple_cost",
        "enable_seqscan","enable_indexscan",
        "enable_indexonlyscan","enable_bitmapscan",
        "enable_hashjoin","enable_mergejoin",
        "enable_nestloop","enable_memoize",
        "enable_partitionwise_join","join_collapse_limit",
        "from_collapse_limit","geqo"
    ]

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT name, setting, unit
            FROM pg_catalog.pg_settings
            WHERE name = ANY(%s)
            ORDER BY name
        """, (settings_to_get,))

        rows = cursor.fetchall()

    return {
        name: {
            "value": value,
            "unit": unit
        }
        for name, value, unit in rows
    }

# SECTION: AI INTEGRATION

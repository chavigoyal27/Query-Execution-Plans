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


# ==========================
# SECTION: AI INTEGRATION
# ==========================

def get_default_qep_system_prompt() -> str:
    return (
        "You are a PostgreSQL query optimization assistant. "
        "Given a SQL SELECT query, return the best-fit execution approach as JSON only. "
        "Your response must be valid JSON (no markdown, no code fences, no extra prose). "
        "Match the structure of a PostgreSQL EXPLAIN JSON plan, including fields such as 'Node Type', 'Join Type', 'Startup Cost', 'Total Cost', 'Plan Rows', 'Plan Width', and nested 'Plans' arrays when relevant. "
        "If helpful, include top-level keys like 'recommended_plan_summary', 'indexes_to_consider', and 'assumptions', but keep the output as a JSON object only. "
        "Focus on PostgreSQL-compatible operations and practical optimizer behavior."
    )

# Build the user prompt for AI-assisted PostgreSQL query-plan recommendations.
def build_qep_user_prompt(sql_query: str) -> str:

    cleaned_query = (sql_query or "").strip()
    if not cleaned_query:
        raise ValueError("SQL query cannot be empty.")

    if not cleaned_query.upper().startswith("SELECT "):
        raise ValueError("Only SELECT queries are supported for AI planning.")

    example_json = '''{
  "Node Type": "Hash Join",
  "Parallel Aware": false,
  "Async Capable": false,
  "Join Type": "Inner",
  "Startup Cost": 23.25,
  "Total Cost": 39.82,
  "Plan Rows": 500,
  "Plan Width": 23,
  "Disabled": false,
  "Inner Unique": true,
  "Hash Cond": "(o.o_custkey = c.c_custkey)",
  "Plans": [
    {
      "Node Type": "Seq Scan",
      "Parent Relationship": "Outer",
      "Parallel Aware": false,
      "Async Capable": false,
      "Relation Name": "orders",
      "Alias": "o",
      "Startup Cost": 0.0,
      "Total Cost": 15.25,
      "Plan Rows": 500,
      "Plan Width": 8,
      "Disabled": false,
      "Filter": "(o_totalprice > '1000'::numeric)"
    },
    {
      "Node Type": "Hash",
      "Parent Relationship": "Inner",
      "Parallel Aware": false,
      "Async Capable": false,
      "Startup Cost": 17.0,
      "Total Cost": 17.0,
      "Plan Rows": 500,
      "Plan Width": 23,
      "Disabled": false,
      "Plans": [
        {
          "Node Type": "Seq Scan",
          "Parent Relationship": "Outer",
          "Parallel Aware": false,
          "Async Capable": false,
          "Relation Name": "customer",
          "Alias": "c",
          "Startup Cost": 0.0,
          "Total Cost": 17.0,
          "Plan Rows": 500,
          "Plan Width": 23,
          "Disabled": false
        }
      ]
    }
  ]
}'''

    return (
        "Analyze the following SQL query and return the best-fit PostgreSQL execution plan.\n\n"
        "SQL query to plan:\n"
        f"{cleaned_query}\n\n"
        "Requirements:\n"
        "1) Return JSON only.\n"
        "2) Do not include markdown fences, explanation text, or any prose outside the JSON object.\n"
        "3) Follow the PostgreSQL EXPLAIN JSON format shown below, using realistic PostgreSQL node types, cost estimates, row counts, and nested 'Plans' arrays when appropriate.\n"
        "4) Keep the response structurally similar to a PostgreSQL execution plan, with keys such as 'Node Type', 'Join Type', 'Startup Cost', 'Total Cost', 'Plan Rows', 'Plan Width', and 'Plans'.\n"
        "5) If useful, include additional top-level fields such as 'recommended_plan_summary', 'indexes_to_consider', and 'assumptions', but keep them inside the same JSON object.\n\n"
        "The example below demonstrates JSON format only. Plan the SQL query above; "
        "do not copy the example's tables, predicates, indexes, or estimates.\n\n"
        "Format-only example SQL:\n"
        "SELECT c.c_name, o.o_orderkey\n"
        "    FROM public.customer c\n"
        "    JOIN public.orders o ON c.c_custkey = o.o_custkey\n"
        "    WHERE o.o_totalprice > 1000;\n\n"
        "PostgreSQL QEP (JSON):\n"
        f"{example_json}\n"
    )

# Load API key from .env file if not already set in environment variables.
def _load_api_key_from_env_file():
    import os
    from pathlib import Path

    env_candidates = [
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env"
    ]

    for env_path in env_candidates:
        if not env_path.exists():
            continue

        with env_path.open("r", encoding="utf-8") as file_handle:
            for raw_line in file_handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if key and key not in os.environ:
                    os.environ[key] = value


def _extract_json_payload(text_content: str) -> dict:
    import json

    cleaned = text_content.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI response did not contain a valid JSON object.")

    return json.loads(cleaned[start:end + 1])

# Generate a Query Execution Plan (QEP) using the Google Gemini AI model.
def get_ai_query_execution_plan(
    sql_query: str,
    system_prompt: str | None = None,
    model: str | None = None
) -> dict:
    import os
    import json

    _load_api_key_from_env_file()

    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY_GEMINI")
    if not gemini_key:
        raise RuntimeError("Gemini API key not found. Set GEMINI_API_KEY in environment or .env.")

    prompt_system = system_prompt or get_default_qep_system_prompt()
    prompt_user = build_qep_user_prompt(sql_query)
    combined_prompt = f"System:\n{prompt_system}\n\nUser:\n{prompt_user}"

    # Normalize model name for genai client: use the final path segment (e.g. 'gemini-2.5-flash')
    raw_model = model or os.getenv("GEMINI_MODEL", "gemini-1.0")
    selected_model = raw_model.split("/")[-1]

    # Initialize genai client
    try:
        from google import genai
    except Exception as e:
        raise RuntimeError("genai library is required for Gemini calls. Install 'google-genai' or set up the SDK.") from e

    try:
        client = genai.Client(api_key=gemini_key)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize genai client: {e}") from e

    # Call the model
    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=combined_prompt
        )
    except Exception as e:
        raise RuntimeError(f"Gemini genai call failed: {e}") from e

    # Extract textual response
    response_text = None
    # Preferred attribute
    if hasattr(response, "text") and isinstance(response.text, str):
        response_text = response.text
    else:
        # Try to convert to dict and inspect common shapes
        parsed_resp = None
        try:
            if hasattr(response, "to_dict"):
                parsed_resp = response.to_dict()
            else:
                parsed_resp = json.loads(str(response))
        except Exception:
            parsed_resp = None

        if isinstance(parsed_resp, dict):
            # candidates -> content
            if "candidates" in parsed_resp and parsed_resp["candidates"]:
                first = parsed_resp["candidates"][0]
                if isinstance(first.get("content"), list):
                    parts = []
                    for item in first.get("content", []):
                        if isinstance(item, dict) and item.get("text"):
                            parts.append(item.get("text"))
                        elif isinstance(item, str):
                            parts.append(item)
                    response_text = "\n".join([p for p in parts if p])
                elif isinstance(first.get("text"), str):
                    response_text = first.get("text")
            # fallback: output -> content/text
            if not response_text and "output" in parsed_resp:
                out = parsed_resp["output"]
                if isinstance(out, dict) and isinstance(out.get("content"), list):
                    texts = [c.get("text") for c in out.get("content") if isinstance(c, dict) and c.get("text")]
                    response_text = "\n".join([t for t in texts if t])
                elif isinstance(out, str):
                    response_text = out

    if not response_text:
        # Last resort: string representation
        response_text = str(response)

    # Extract JSON payload and validate. Accept both the legacy 'steps' format
    # and the PostgreSQL EXPLAIN JSON/plan-like format requested by the prompt.
    result = _extract_json_payload(response_text)

    if not isinstance(result, dict):
        raise RuntimeError("AI result is not a JSON object.")

    has_steps = isinstance(result.get("steps"), list) and bool(result.get("steps"))
    postgres_plan_keys = (
        "Node Type",
        "NodeType",
        "Plans",
        "Startup Cost",
        "Total Cost",
        "Plan Rows",
        "Plan Width",
        "Join Type",
        "Relation Name",
    )
    has_postgres_plan_shape = any(key in result for key in postgres_plan_keys)

    if not (has_steps or has_postgres_plan_shape):
        raise RuntimeError(
            "AI result must include either a non-empty 'steps' array or a PostgreSQL-style plan object "
            "with keys such as 'Node Type', 'Plans', 'Startup Cost', and 'Total Cost'."
        )

    return result

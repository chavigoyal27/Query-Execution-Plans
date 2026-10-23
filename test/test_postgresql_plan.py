"""Print a real PostgreSQL optimizer plan: python test/test_postgresql_plan.py."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database_init import DB_PARAMS
from preprocessing import connect_database, get_postgresql_plan


def main():
    query = """
    SELECT c.c_name, o.o_orderkey
    FROM public.customer c
    JOIN public.orders o ON c.c_custkey = o.o_custkey
    WHERE o.o_totalprice > 1000;
    """
    config = dict(DB_PARAMS)
    # psycopg 3 uses dbname; the setup script uses psycopg2's database alias.
    config['dbname'] = config.pop('database')
    config['connect_timeout'] = 5
    print('SQL query:')
    print(query.strip())
    with connect_database(config) as connection:
        plan = get_postgresql_plan(connection, query, schema_name='public')
    print('\nPostgreSQL QEP (JSON):')
    print(json.dumps(plan, indent=2))


if __name__ == '__main__':
    main()

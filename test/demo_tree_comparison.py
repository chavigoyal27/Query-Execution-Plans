"""Show comparison output. Use --live for one PostgreSQL and Gemini retrieval."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from comparison import compare_plans

QUERY = '''SELECT c.c_name, o.o_orderkey
FROM public.customer c
JOIN public.orders o ON c.c_custkey = o.o_custkey
WHERE o.o_totalprice > 1000;'''


def show(name, pg, ai, folder):
    result = compare_plans(pg, ai)
    for suffix, value in [('postgres', pg), ('ai', ai), ('result', result)]:
        (folder / f'{name}_{suffix}.json').write_text(
            json.dumps(value, indent=2), encoding='utf-8')
    print('\n' + name)
    print('Mode:', result['mode'])
    rate = result['difference_rate']
    print('Difference rate:', f'{rate:.1%}' if rate is not None else 'unavailable')
    print('Metrics:', result.get('metric'))
    for text in result['explanations']:
        print(' -', text)
    for node in result['node_annotations']:
        print(' ', node['source'], node['node_id'], node['status'],
              'counterpart:', node['counterpart_id'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    folder = ROOT / 'demo_output' / 'tree_comparison'
    folder.mkdir(parents=True, exist_ok=True)
    # Explicit fixtures, not AI-generated answers or executed database plans.
    pg = {'Node Type': 'Hash Join', 'Join Type': 'Inner', 'Plans': [
        {'Node Type': 'Seq Scan', 'Relation Name': 'orders', 'Alias': 'o'},
        {'Node Type': 'Seq Scan', 'Relation Name': 'customer', 'Alias': 'c'},
    ]}
    show('fixture_identical', pg, deepcopy(pg), folder)
    changed = deepcopy(pg)
    changed['Plans'][0]['Node Type'] = 'Index Scan'
    changed['Plans'][0]['Index Name'] = 'example_orders_index'
    show('fixture_changed_scan', pg, changed, folder)
    reordered = deepcopy(pg)
    reordered['Plans'].reverse()
    show('fixture_reordered_inputs', pg, reordered, folder)
    if args.live:
        from database_init import DB_PARAMS
        from preprocessing import connect_database, get_postgresql_plan, get_ai_query_execution_plan
        config = dict(DB_PARAMS)
        if 'database' in config:
            config['dbname'] = config.pop('database')
        config['connect_timeout'] = 5
        print('\nRetrieving PostgreSQL plan...')
        with connect_database(config) as connection:
            postgres = get_postgresql_plan(connection, QUERY)
        print('Retrieving Gemini plan (one API request)...', flush=True)
        ai = get_ai_query_execution_plan(QUERY)
        show('live', postgres, ai, folder)
    print('\nFull input/output JSON:', folder)


if __name__ == '__main__':
    main()

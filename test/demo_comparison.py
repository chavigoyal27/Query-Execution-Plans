"""Read-only local demo using the operation labels from the shared AI response.

No AI call is made. Saves the two inputs and comparison JSON under demo_output/.
Run from the repository root: python test/demo_comparison.py
"""
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comparison import compare_plans
from database_init import DB_PARAMS
from preprocessing import connect_database, get_postgresql_plan


def main():
    # Read the same SQL literal as the existing AI test without invoking Gemini.
    source = ast.parse((ROOT / 'test/test_AI_prompt_gemini.py').read_text(encoding='utf-8'))
    query = next(ast.literal_eval(node.value) for node in ast.walk(source)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'sample_query'
                         for t in node.targets))
    labels = ['Index Scan / Filter', 'Nested Loop or Hash Join', 'Hash Join',
              'HashAggregate', 'Top-N Heapsort / Limit']
    ai = {'steps': [{'step_number': i, 'operation': label}
                    for i, label in enumerate(labels, 1)]}
    config = dict(DB_PARAMS)
    config['dbname'] = config.pop('database')
    config['connect_timeout'] = 5
    with connect_database(config) as connection:
        pg = get_postgresql_plan(connection, query)
    result = compare_plans(pg, ai)
    folder = ROOT / 'demo_output'
    folder.mkdir(exist_ok=True)
    for name, value in [('postgres_plan', pg), ('ai_operations', ai), ('comparison', result)]:
        (folder / (name + '.json')).write_text(json.dumps(value, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    print('Saved inputs and result to', folder)


if __name__ == '__main__':
    main()

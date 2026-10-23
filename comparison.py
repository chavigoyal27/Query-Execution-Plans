"""Schema-independent structural QEP comparison; no database or API calls.

Use compare_plans(postgresql_plan, ai_plan), or run:
    python comparison.py postgres_plan.json ai_plan.json
Tree inputs accept a bare PostgreSQL node, {"Plan": node}, or EXPLAIN's
single-element array. Legacy AI {"steps": [...]} responses receive only
an operation-inventory comparison: prose is never treated as tree structure.
"""

import argparse
from collections import Counter
import json
import re


def _operation(node):
    name = node['Node Type']
    aliases = {
        'HashAggregate': 'Aggregate (Hashed)',
        'GroupAggregate': 'Aggregate (Sorted)',
        'Nested Loop Join': 'Nested Loop',
        'Sequential Scan': 'Seq Scan',
    }
    if name == 'Aggregate' and node.get('Strategy'):
        return 'Aggregate (' + node['Strategy'] + ')'
    return aliases.get(name, name)


def _tree(value):
    if isinstance(value, list):
        if len(value) != 1:
            raise ValueError('Expected one EXPLAIN plan.')
        value = value[0]
    if isinstance(value, dict) and 'Plan' in value:
        value = value['Plan']
    if not isinstance(value, dict) or not isinstance(value.get('Node Type'), str):
        raise ValueError('Expected a PostgreSQL-style plan tree with Node Type.')
    if not value['Node Type'].strip():
        raise ValueError('Node Type cannot be empty.')
    children = value.get('Plans', [])
    if not isinstance(children, list):
        raise ValueError('Plans must be a list.')
    for child in children:
        _tree(child)
    return value


def _nodes(root, path='root'):
    yield path, root
    for index, child in enumerate(root.get('Plans', [])):
        yield from _nodes(child, f'{path}.Plans[{index}]')


def _identity(node):
    # Include relation identity and join type; never rely on schema-specific names.
    return (_operation(node), node.get('Schema'), node.get('Relation Name'),
            node.get('Alias'), node.get('Join Type'))


def _signature(node):
    # Preserve child order: join orientation can matter. Costs are not structural.
    return (_identity(node), tuple(_signature(c) for c in node.get('Plans', [])))


def _counts(counter):
    return [{'operation': name, 'count': count}
            for name, count in sorted(counter.items()) if count]


def compare_plans(postgresql_plan, ai_plan):
    """Return JSON-serializable comparison evidence and explicit limitations.

    Inventory distance = sum(abs(pg_count - ai_count)) / sum(all counts).
    This measures operation counts only, not semantic equivalence or performance.
    For ambiguous legacy steps the distance is unavailable (None).
    """
    pg = _tree(postgresql_plan)
    pg_nodes = list(_nodes(pg))
    pg_counts = Counter(_operation(n) for _, n in pg_nodes)
    limitations = [
        'Operation counts do not establish SQL equivalence or plan quality.',
        'Costs, timings, predicates, index names and estimated rows are not scored.',
    ]
    unresolved = []
    ai_nodes = None
    if isinstance(ai_plan, dict) and 'steps' in ai_plan:
        steps = ai_plan['steps']
        if not isinstance(steps, list) or not steps:
            raise ValueError('AI steps must be a non-empty list.')
        ai_counts = Counter()
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get('operation'), str):
                raise ValueError('Each AI step must have a string operation.')
            label = step['operation'].strip()
            # Do not split prose or guess which alternative the model intended.
            if not label or re.search(r'/|\bor\b', label, re.IGNORECASE):
                unresolved.append({'step_index': index, 'operation': label})
            else:
                ai_counts[_operation({'Node Type': label})] += 1
        mode = 'legacy_steps'
        limitations.append(
            'AI steps lack explicit child links and relation identities; tree structure, '
            'join order and table-specific scan changes cannot be compared reliably.'
        )
    else:
        ai = _tree(ai_plan)
        ai_nodes = list(_nodes(ai))
        ai_counts = Counter(_operation(n) for _, n in ai_nodes)
        mode = 'tree'

    common = pg_counts & ai_counts
    pg_only = pg_counts - ai_counts
    ai_only = ai_counts - pg_counts
    denominator = sum(pg_counts.values()) + sum(ai_counts.values())
    distance = None if unresolved else (
        (sum(pg_only.values()) + sum(ai_only.values())) / denominator
    )
    result = {
        'mode': mode,
        'postgresql_operations': _counts(pg_counts),
        'ai_operations': _counts(ai_counts),
        'shared_operations': _counts(common),
        'postgresql_unmatched_operations': _counts(pg_only),
        'ai_unmatched_operations': _counts(ai_only),
        'unresolved_ai_steps': unresolved,
        'operation_difference_rate': distance,
        'same_ordered_structure': None,
        'node_annotations': [],
        'limitations': limitations,
        'explanations': [],
    }
    if ai_nodes is not None:
        result['same_ordered_structure'] = _signature(pg) == _signature(ai)
        # Match only unique identities; duplicate/self-join nodes without sufficient
        # identity remain ambiguous rather than being paired by traversal position.
        pg_ids = Counter(_identity(n) for _, n in pg_nodes)
        ai_ids = Counter(_identity(n) for _, n in ai_nodes)
        ai_paths = {_identity(n): path for path, n in ai_nodes}
        for path, node in pg_nodes:
            key = _identity(node)
            unique = pg_ids[key] == ai_ids[key] == 1
            result['node_annotations'].append({
                'postgresql_path': path,
                'ai_path': ai_paths[key] if unique else None,
                'operation': _operation(node),
                'status': 'matched_identity' if unique else (
                    'unmatched' if not ai_ids[key] else 'ambiguous_identity'),
            })
        result['explanations'].append(
            'Ordered operator/relation structure is identical.'
            if result['same_ordered_structure'] else
            'Ordered operator/relation structure differs; inspect the two trees. '
            'Matching operation counts alone can conceal these differences.'
        )
    for item in _counts(common):
        result['explanations'].append(
            f"Both plans explicitly contain {item['count']} {item['operation']} operation(s)."
        )
    if unresolved:
        result['explanations'].append(
            'AI output contains compound or alternative operations; unmatched counts '
            'are provisional and the difference rate is unavailable.'
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('postgresql_json')
    parser.add_argument('ai_json')
    args = parser.parse_args()
    with open(args.postgresql_json, encoding='utf-8-sig') as handle:
        pg = json.load(handle)
    with open(args.ai_json, encoding='utf-8-sig') as handle:
        ai = json.load(handle)
    print(json.dumps(compare_plans(pg, ai), indent=2))


if __name__ == '__main__':
    main()

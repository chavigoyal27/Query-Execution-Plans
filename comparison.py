"""Schema-independent structural QEP comparison; no database or API calls.

Use compare_plans(postgresql_plan, ai_plan), or run:
    python comparison.py postgres_plan.json ai_plan.json
Tree inputs accept a bare PostgreSQL node, {"Plan": node}, or EXPLAIN's
single-element array. Returns normalized trees, node correspondences, differences,
explanations, GUI statuses and an affected-node metric. Legacy AI {"steps": [...]}
responses receive only an operation-inventory comparison.
"""

import argparse
from collections import Counter
import json
import re


def _strategy(node):
    """Read an explicit strategy or the strategy implied by an aggregate alias."""
    if node.get('Strategy') is not None:
        return node['Strategy']
    return {'HashAggregate': 'Hashed', 'GroupAggregate': 'Sorted'}.get(node['Node Type'])


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


def _compare_legacy(postgresql_plan, ai_plan):
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


# Deliberately exclude costs/estimates and narrative metadata from structural
# scoring. Preserve them in attributes for GUI tooltips. Expressions are compared
# literally: rewriting SQL expressions without a parser could alter meaning.
COMPARED_FIELDS = (
    'Join Type', 'Strategy', 'Index Name', 'Scan Direction', 'Filter',
    'Index Cond', 'Recheck Cond', 'Hash Cond', 'Merge Cond', 'Join Filter',
    'Group Key', 'Sort Key', 'Presorted Key', 'Output', 'Subplan Name',
    'CTE Name', 'Function Name', 'Parallel Aware', 'Partial Mode',
    'Workers Planned', 'Parent Relationship',
)
NARRATIVE_FIELDS = ('recommended_plan_summary', 'indexes_to_consider', 'assumptions')


def _family(operation):
    if 'Join' in operation or operation == 'Nested Loop':
        return 'join'
    if 'Scan' in operation and operation not in ('Bitmap Index Scan',):
        return 'scan'
    if operation.startswith('Aggregate'):
        return 'aggregate'
    if operation in ('Sort', 'Incremental Sort'):
        return 'sort'
    return operation


def normalize_plan(value, source):
    """Copy a PostgreSQL-shaped tree into nodes with stable source-local IDs.

    Leaves without relation identity retain their operator identity. Self-joins
    retain aliases; unresolved duplicate scopes are never arbitrarily paired.
    """
    root = _tree(value)
    nodes = {}

    def visit(raw, path, parent):
        node_id = f'{source}_{len(nodes)}'
        attributes = {k: v for k, v in raw.items()
                      if k != 'Plans' and k not in NARRATIVE_FIELDS}
        node = {
            'id': node_id, 'path': path, 'operator': _operation(raw),
            'family': _family(_operation(raw)), 'parent_id': parent,
            'attributes': attributes, 'children': [], 'scope': [],
            'status': 'unmatched', 'counterpart_id': None,
            'difference_ids': [],
        }
        nodes[node_id] = node
        node['children'] = [visit(c, f'{path}.Plans[{i}]', node_id)
                            for i, c in enumerate(raw.get('Plans', []))]
        scope = []
        # Bitmap Index Scan inherits no relation identity of its own; its parent
        # provides it through matching context later.
        if raw.get('Relation Name'):
            scope.append((raw.get('Schema'), raw['Relation Name'], raw.get('Alias')))
        elif raw.get('CTE Name'):
            scope.append(('CTE', raw['CTE Name'], raw.get('Alias')))
        else:
            for child in node['children']:
                scope.extend(nodes[child]['scope'])
        node['scope'] = sorted(scope, key=repr)
        return node_id

    root_id = visit(root, 'root', None)
    return {'root_id': root_id, 'nodes': list(nodes.values())}


def compare_plans(postgresql_plan, ai_plan):
    """Compare trees without database/API access; legacy steps remain supported.

    Matching uses unique (operator family, descendant relation/alias multiset)
    anchors and uniquely identifiable children of matched parents, repeated
    until no further pairs can be resolved.
    Operator methods may differ. Ties remain explicitly uncertain.

    difference_rate is the fraction of nodes affected by a recorded difference:
    (2 * changed_pairs + unmatched_nodes) / (pg_nodes + ai_nodes).
    Ambiguous correspondence makes the rate unavailable. It is a heuristic
    affected-node rate, NOT tree edit distance or a measure of execution quality.
    """
    if isinstance(ai_plan, dict) and 'steps' in ai_plan and 'Node Type' not in ai_plan and 'Plan' not in ai_plan:
        result = _compare_legacy(postgresql_plan, ai_plan)
        result['difference_rate'] = None
        return result
    pg_tree = normalize_plan(postgresql_plan, 'pg')
    ai_tree = normalize_plan(ai_plan, 'ai')
    pg = {n['id']: n for n in pg_tree['nodes']}
    ai = {n['id']: n for n in ai_tree['nodes']}
    matches = {}
    reverse = {}

    def key(n):
        return n['family'], tuple(tuple(s) for s in n['scope'])

    def bind(p, a):
        matches[p] = a
        reverse[a] = p

    # Group unmatched nodes independently of traversal order.
    def groups(nodes, excluded, candidates=None):
        grouped = {}
        for node_id in (candidates if candidates is not None else nodes):
            if node_id not in excluded:
                grouped.setdefault(key(nodes[node_id]), []).append(node_id)
        return grouped

    def bind_unique(p_groups, a_groups):
        # Dictionary insertion order follows the supplied tree, so matching is
        # deterministic without sorting potentially large relation scopes.
        for anchor, p_candidates in p_groups.items():
            a_candidates = a_groups.get(anchor, [])
            if len(p_candidates) == len(a_candidates) == 1:
                bind(p_candidates[0], a_candidates[0])

    # A contextual match can make another global pair unique, or disambiguate
    # children of an already visited parent. Revisit both rules to a fixed point.
    # Each successful pass binds at least one new pair, so this loop terminates.
    while True:
        previous_count = len(matches)
        bind_unique(groups(pg, matches), groups(ai, reverse))
        for p, a in list(matches.items()):
            bind_unique(groups(pg, matches, pg[p]['children']),
                        groups(ai, reverse, ai[a]['children']))
        if len(matches) == previous_count:
            break

    remaining_pg = groups(pg, matches)
    remaining_ai = groups(ai, reverse)

    differences = []
    similarities = []

    def record(kind, p, a, details, explanation):
        diff_id = f'diff_{len(differences)}'
        differences.append({'id': diff_id, 'kind': kind,
                            'postgresql_node_id': p, 'ai_node_id': a,
                            'details': details, 'explanation': explanation})
        for nodes, node_id in ((pg, p), (ai, a)):
            if node_id is not None:
                nodes[node_id]['difference_ids'].append(diff_id)

    for p, a in sorted(matches.items(), key=lambda item: pg[item[0]]['path']):
        pn, an = pg[p], ai[a]
        relationship_uncertain = False
        pn['counterpart_id'], an['counterpart_id'] = a, p
        context = ', '.join(s[2] or s[1] for s in pn['scope']) or pn['operator']
        if pn['operator'] != an['operator']:
            record('operator_changed', p, a,
                   {'postgresql': pn['operator'], 'ai': an['operator']},
                   f"For {context}, PostgreSQL uses {pn['operator']}; AI uses {an['operator']}.")
        else:
            similarities.append({'postgresql_node_id': p, 'ai_node_id': a,
                                 'kind': 'same_operator',
                                 'explanation': f"Both use {pn['operator']} for {context}."})
        for field in COMPARED_FIELDS:
            pv, av = pn['attributes'].get(field), an['attributes'].get(field)
            if field == 'Strategy':
                # Preserve raw attributes for display, but compare the canonical
                # strategy also implied by HashAggregate / GroupAggregate.
                pv, av = _strategy(pn['attributes']), _strategy(an['attributes'])
            if pv != av:
                record('attribute_changed', p, a,
                       {'field': field, 'postgresql': pv, 'ai': av,
                        'postgresql_present': field in pn['attributes'],
                        'ai_present': field in an['attributes']},
                       f"For {context}, {field} differs: PostgreSQL {pv!r}; AI {av!r}. "
                       'An omitted field without an implied value means unspecified, '
                       'not necessarily absent at execution.')
        # Compare actual immediate edges, preserving their order. Inserted helper
        # nodes remain visible and affect the structural comparison.
        children_changed = len(pn['children']) != len(an['children'])
        for pc, ac in zip(pn['children'], an['children']):
            if pc in matches:
                children_changed |= matches[pc] != ac
            elif ac in reverse or key(pg[pc]) != key(ai[ac]):
                children_changed = True
            else:
                # Compatible unresolved children do not prove an edge changed.
                relationship_uncertain = True
        if children_changed:
            record('children_changed', p, a,
                   {'postgresql_children': pn['children'], 'ai_children': an['children']},
                   f'For {context}, ordered inputs differ (order, grouping, or extra/missing nodes).')
        pp, ap = pn['parent_id'], an['parent_id']
        parent_changed = (pp is None) != (ap is None)
        if pp is not None and ap is not None:
            if pp in matches:
                parent_changed = matches[pp] != ap
            elif ap in reverse or key(pg[pp]) != key(ai[ap]):
                parent_changed = True
            else:
                relationship_uncertain = True
        if parent_changed:
            record('parent_changed', p, a,
                   {'postgresql_parent': pp, 'ai_parent': ap},
                   f'For {context}, the node has a different position in the plan tree.')
        pn['status'] = an['status'] = (
            'changed' if pn['difference_ids'] else
            'uncertain' if relationship_uncertain else 'unchanged'
        )

    unresolved = []
    for nodes, excluded, other_groups, source in (
        (pg, matches, remaining_ai, 'postgresql'), (ai, reverse, remaining_pg, 'ai')
    ):
        for node_id, node in nodes.items():
            if node_id in excluded:
                continue
            candidates = other_groups.get(key(node), [])
            if candidates:
                node['status'] = 'uncertain'
                unresolved.append({'source': source, 'node_id': node_id,
                                   'candidate_ids': candidates,
                                   'reason': 'Multiple possible correspondences; no arbitrary pairing.'})
            else:
                record('unmatched_node', node_id if source == 'postgresql' else None,
                       node_id if source == 'ai' else None, {'operator': node['operator']},
                       f"{source} contains an unmatched {node['operator']} node at {node['path']}.")

    pg_counts = Counter(n['operator'] for n in pg.values())
    ai_counts = Counter(n['operator'] for n in ai.values())
    total = len(pg) + len(ai)
    changed_pairs = sum(pg[p]['status'] == 'changed' for p in matches)
    unmatched = sum(n['status'] == 'unmatched' for n in [*pg.values(), *ai.values()])
    metadata_root = ai_plan[0] if isinstance(ai_plan, list) else ai_plan
    metadata = {k: metadata_root[k] for k in NARRATIVE_FIELDS if k in metadata_root}
    affected = 2 * changed_pairs + unmatched
    return {
        'mode': 'tree', 'format_version': 2,
        'trees': {'postgresql': pg_tree, 'ai': ai_tree},
        'ai_metadata': metadata,
        'matches': [{'postgresql_node_id': p, 'ai_node_id': a} for p, a in sorted(matches.items())],
        'differences': differences, 'similarities': similarities,
        'unresolved_matches': unresolved,
        'postgresql_operations': _counts(pg_counts), 'ai_operations': _counts(ai_counts),
        'shared_operations': _counts(pg_counts & ai_counts),
        'postgresql_unmatched_operations': _counts(pg_counts - ai_counts),
        'ai_unmatched_operations': _counts(ai_counts - pg_counts),
        'unresolved_ai_steps': [],
        'operation_difference_rate': sum((pg_counts - ai_counts).values()) / total
                                     + sum((ai_counts - pg_counts).values()) / total,
        'difference_rate': None if unresolved else affected / total,
        'metric': {'name': 'affected_node_rate', 'changed_pairs': changed_pairs,
                   'unmatched_nodes': unmatched, 'total_nodes': total,
                   'formula': '(2 * changed_pairs + unmatched_nodes) / total_nodes'},
        'same_ordered_structure': _signature(_tree(postgresql_plan)) == _signature(_tree(ai_plan)),
        'node_annotations': [
            {'source': side, 'node_id': n['id'], 'status': n['status'],
             'counterpart_id': n['counterpart_id'], 'difference_ids': n['difference_ids']}
            for side, nodes in (('postgresql', pg), ('ai', ai)) for n in nodes.values()
        ],
        'explanations': [d['explanation'] for d in differences] or
                        (['Correspondence is uncertain.'] if unresolved else ['No compared differences found.']),
        'limitations': [
            'Matching is heuristic, not minimum tree edit distance or SQL equivalence checking.',
            'Predicates and expression lists are compared literally; equivalent SQL may differ.',
            'Missing compared fields count as differences in reported information.',
            'Aliases and schema qualification must be consistent between plans.',
            'Costs, estimates, runtime measurements and recommendations are preserved but not scored.',
            'Unknown operator types are preserved and matched by their exact operator family.',
            'Different join groupings can leave joins unmatched; scans can still correspond.',
        ],
    }


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

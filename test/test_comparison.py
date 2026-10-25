"""Offline comparison tests: python -m unittest discover -s test -p test_comparison.py."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comparison import compare_plans


def scan(table, alias=None, method='Seq Scan'):
    node = {'Node Type': method, 'Relation Name': table}
    if alias:
        node['Alias'] = alias
    return node


def join(a, b, method='Hash Join'):
    return {'Node Type': method, 'Join Type': 'Inner', 'Plans': [a, b]}


class ComparisonTests(unittest.TestCase):
    def test_identical_tree_metadata_costs_and_wrappers(self):
        pg = join(scan('arbitrary_table', 'x'), scan('other_table', 'y'))
        ai = deepcopy(pg)
        ai.update({'recommended_plan_summary': 'Independent plan', 'Total Cost': 123})
        result = compare_plans([{'Plan': pg}], ai)
        self.assertEqual(result['difference_rate'], 0)
        self.assertEqual(result['ai_metadata']['recommended_plan_summary'], 'Independent plan')
        self.assertEqual(len(result['node_annotations']), 6)
        self.assertTrue(all(n['status'] == 'unchanged' for n in result['node_annotations']))
        json.dumps(result)

    def test_changed_scan_maps_to_same_table(self):
        result = compare_plans(scan('t', 'a'), scan('t', 'a', 'Index Scan'))
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual(result['differences'][0]['kind'], 'operator_changed')
        self.assertEqual(result['difference_rate'], 1)

    def test_join_method_change(self):
        result = compare_plans(join(scan('a'), scan('b')),
                               join(scan('a'), scan('b'), 'Nested Loop'))
        self.assertEqual(len(result['matches']), 3)
        self.assertAlmostEqual(result['difference_rate'], 1 / 3)

    def test_reordered_children_with_identical_counts(self):
        result = compare_plans(join(scan('a'), scan('b')), join(scan('b'), scan('a')))
        self.assertEqual(result['operation_difference_rate'], 0)
        self.assertGreater(result['difference_rate'], 0)
        self.assertFalse(result['same_ordered_structure'])
        self.assertIn('children_changed', [d['kind'] for d in result['differences']])

    def test_changed_join_grouping(self):
        result = compare_plans(join(join(scan('a'), scan('b')), scan('c')),
                               join(scan('a'), join(scan('b'), scan('c'))))
        self.assertGreater(result['difference_rate'], 0)
        self.assertEqual(len(result['matches']), 4)

    def test_self_join_aliases(self):
        result = compare_plans(join(scan('t', 'a'), scan('t', 'b')),
                               join(scan('t', 'b'), scan('t', 'a')))
        self.assertFalse(result['unresolved_matches'])
        self.assertEqual(len(result['matches']), 3)

    def test_unidentified_duplicate_scans_are_uncertain(self):
        node = join(scan('t'), scan('t'))
        result = compare_plans(node, deepcopy(node))
        self.assertIsNone(result['difference_rate'])
        self.assertEqual(len(result['unresolved_matches']), 4)

    def test_identical_parallel_aggregate_plan_from_project_brief(self):
        # Figure 1 has two aggregates over the same input relations. Matching
        # the partial aggregate must make the remaining root pair resolvable.
        node = {
            'Node Type': 'Aggregate', 'Strategy': 'Plain', 'Partial Mode': 'Finalize',
            'Plans': [{
                'Node Type': 'Gather', 'Workers Planned': 2,
                'Plans': [{
                    'Node Type': 'Aggregate', 'Strategy': 'Plain', 'Partial Mode': 'Partial',
                    'Plans': [join(scan('lineitem', 'l'), {
                        'Node Type': 'Hash', 'Plans': [scan('part', 'p')],
                    })],
                }],
            }],
        }
        result = compare_plans(node, deepcopy(node))
        self.assertEqual(len(result['matches']), 7)
        self.assertEqual(result['difference_rate'], 0)
        self.assertEqual(result['unresolved_matches'], [])
        self.assertEqual(result['differences'], [])
        self.assertTrue(all(n['status'] == 'unchanged' for n in result['node_annotations']))

    def test_repeated_operators_resolve_after_parent_matching(self):
        for middle in ('Sort', 'Gather'):
            with self.subTest(middle=middle):
                node = {
                    'Node Type': 'Aggregate', 'Strategy': 'Plain',
                    'Plans': [{
                        'Node Type': middle,
                        'Plans': [{
                            'Node Type': 'Aggregate', 'Strategy': 'Plain',
                            'Plans': [scan('t')],
                        }],
                    }],
                }
                result = compare_plans(node, deepcopy(node))
                self.assertEqual(len(result['matches']), 4)
                self.assertEqual(result['difference_rate'], 0)
                self.assertEqual(result['differences'], [])

    def test_uncertain_parent_does_not_prove_child_moved(self):
        node = {
            'Node Type': 'Sort',
            'Plans': [{'Node Type': 'Sort', 'Plans': [scan('t')]}],
        }
        result = compare_plans(node, deepcopy(node))
        self.assertIsNone(result['difference_rate'])
        self.assertTrue(result['unresolved_matches'])
        self.assertNotIn('parent_changed', [d['kind'] for d in result['differences']])

    def test_uncertain_children_do_not_prove_order_changed(self):
        node = join(scan('t'), scan('t'))
        result = compare_plans(node, deepcopy(node))
        self.assertIsNone(result['difference_rate'])
        self.assertNotIn('children_changed', [d['kind'] for d in result['differences']])

    def test_known_child_reorder_is_reported_despite_other_ambiguity(self):
        pg = {'Node Type': 'Append', 'Plans': [scan('t'), scan('t'), scan('u')]}
        ai = {'Node Type': 'Append', 'Plans': [scan('u'), scan('t'), scan('t')]}
        result = compare_plans(pg, ai)
        self.assertIsNone(result['difference_rate'])
        self.assertIn('children_changed', [d['kind'] for d in result['differences']])

    def test_different_unmatched_parents_still_report_movement(self):
        pg = {'Node Type': 'Sort', 'Plans': [scan('t')]}
        ai = {'Node Type': 'Limit', 'Plans': [scan('t')]}
        result = compare_plans(pg, ai)
        self.assertFalse(result['unresolved_matches'])
        self.assertIn('parent_changed', [d['kind'] for d in result['differences']])

    def test_aggregate_aliases_have_equivalent_strategies(self):
        for alias, strategy in [('HashAggregate', 'Hashed'), ('GroupAggregate', 'Sorted')]:
            canonical = {'Node Type': 'Aggregate', 'Strategy': strategy, 'Plans': [scan('t')]}
            shorthand = {'Node Type': alias, 'Plans': [scan('t')]}
            for pg, ai in [(canonical, shorthand), (shorthand, canonical)]:
                with self.subTest(alias=alias, pg_operator=pg['Node Type']):
                    before = deepcopy((pg, ai))
                    result = compare_plans(pg, ai)
                    self.assertEqual(result['difference_rate'], 0)
                    self.assertEqual(result['differences'], [])
                    self.assertEqual((pg, ai), before)

    def test_different_aggregate_strategies_still_count(self):
        pg = {'Node Type': 'Aggregate', 'Strategy': 'Hashed', 'Plans': [scan('t')]}
        ai = {'Node Type': 'GroupAggregate', 'Plans': [scan('t')]}
        result = compare_plans(pg, ai)
        self.assertEqual(len(result['matches']), 2)
        self.assertEqual(result['difference_rate'], 0.5)
        self.assertIn('operator_changed', [d['kind'] for d in result['differences']])

    def test_planned_workers_are_compared(self):
        pg = {'Node Type': 'Gather', 'Workers Planned': 2, 'Plans': [scan('t')]}
        ai = deepcopy(pg)
        ai['Workers Planned'] = 8
        result = compare_plans(pg, ai)
        self.assertEqual(result['difference_rate'], 0.5)
        self.assertEqual(len(result['differences']), 1)
        self.assertEqual(result['differences'][0]['details']['field'], 'Workers Planned')

    def test_subplan_parent_relationship_is_compared(self):
        pg = {
            'Node Type': 'Result',
            'Plans': [dict(scan('t'), **{'Parent Relationship': 'InitPlan'})],
        }
        ai = deepcopy(pg)
        ai['Plans'][0]['Parent Relationship'] = 'SubPlan'
        result = compare_plans(pg, ai)
        self.assertEqual(result['difference_rate'], 0.5)
        self.assertEqual(len(result['differences']), 1)
        self.assertEqual(result['differences'][0]['details']['field'], 'Parent Relationship')

    def test_attributes_index_filter_group_sort(self):
        for field, before, after in [
            ('Filter', "x = 'A  B'", "x = 'A B'"),
            ('Index Name', 'idx_a', 'idx_b'),
            ('Group Key', ['a'], ['b']),
            ('Sort Key', ['a ASC'], ['a DESC']),
        ]:
            with self.subTest(field=field):
                p = dict(scan('t'), **{field: before})
                a = dict(scan('t'), **{field: after})
                result = compare_plans(p, a)
                self.assertEqual(result['difference_rate'], 1)
                self.assertEqual(result['differences'][0]['details']['field'], field)

    def test_extra_ai_node_and_gui_links(self):
        result = compare_plans(scan('t'), {'Node Type': 'Sort', 'Plans': [scan('t')]})
        self.assertGreater(result['difference_rate'], 0)
        self.assertTrue(any(n['source'] == 'ai' and n['status'] == 'unmatched'
                            for n in result['node_annotations']))
        ids = {d['id'] for d in result['differences']}
        for annotation in result['node_annotations']:
            self.assertTrue(set(annotation['difference_ids']) <= ids)

    def test_missing_information_and_no_input_mutation(self):
        p = dict(scan('t'), Filter='a > 1')
        a = scan('t')
        snapshot = deepcopy((p, a))
        result = compare_plans(p, a)
        self.assertFalse(result['differences'][0]['details']['ai_present'])
        self.assertEqual((p, a), snapshot)

    def test_legacy_fallback(self):
        result = compare_plans(scan('t'), {'steps': [{'operation': 'Index Scan / Filter'}]})
        self.assertEqual(result['mode'], 'legacy_steps')
        self.assertIsNone(result['difference_rate'])

    def test_invalid_inputs(self):
        for invalid in ({}, [], {'Node Type': 'Sort', 'Plans': [{}]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                compare_plans(scan('t'), invalid)


if __name__ == '__main__':
    unittest.main()

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

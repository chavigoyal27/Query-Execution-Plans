"""Offline prompt tests; pass --live when running this script to call Gemini."""

import argparse
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from preprocessing import build_qep_user_prompt, get_ai_query_execution_plan


class QepUserPromptTests(unittest.TestCase):
    def test_target_query_is_included_and_changes_the_prompt(self):
        first_query = "SELECT * FROM alpha WHERE id = 1;"
        second_query = "SELECT count(*) FROM beta;"

        first_prompt = build_qep_user_prompt(first_query)
        second_prompt = build_qep_user_prompt(second_query)

        self.assertIn("SQL query to plan:\n" + first_query, first_prompt)
        self.assertIn("SQL query to plan:\n" + second_query, second_prompt)
        self.assertNotIn(second_query, first_prompt)
        self.assertNotIn(first_query, second_prompt)
        self.assertNotEqual(first_prompt, second_prompt)

    def test_surrounding_whitespace_is_removed(self):
        query = "SELECT * FROM alpha;"
        self.assertEqual(build_qep_user_prompt(" \n" + query + "\n\t "),
                         build_qep_user_prompt(query))

    def test_multiline_query_is_preserved(self):
        query = "SELECT id,\n       name\nFROM alpha\nWHERE name = 'A  B';"
        self.assertIn("SQL query to plan:\n" + query + "\n\n",
                      build_qep_user_prompt(query))

    def test_example_is_explicitly_format_only(self):
        prompt = build_qep_user_prompt("SELECT * FROM alpha;")
        self.assertIn("Format-only example SQL:", prompt)
        self.assertIn("do not copy the example's tables, predicates, indexes, or estimates.",
                      prompt)
        self.assertIn("Return JSON only.", prompt)
        self.assertIn("PostgreSQL QEP (JSON):", prompt)
        self.assertIn('"Node Type"', prompt)
        self.assertIn('"Plans"', prompt)

    def test_empty_query_is_rejected(self):
        for query in (None, "", " \n\t "):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "cannot be empty"):
                build_qep_user_prompt(query)

    def test_non_select_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Only SELECT"):
            build_qep_user_prompt("DELETE FROM alpha;")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true',
                        help='Also request a plan from Gemini using the configured API key.')
    args = parser.parse_args()

    sample_query = """
    SELECT c.c_name,
           o.o_orderkey,
           SUM(l.l_extendedprice * (1 - l.l_discount)) AS total_amount
    FROM public.customer c
    JOIN public.orders o ON o.o_custkey = c.c_custkey
    JOIN public.lineitem l ON l.l_orderkey = o.o_orderkey
    WHERE o.o_orderdate >= DATE '1995-01-01'
      AND o.o_orderdate < DATE '1995-02-01'
    GROUP BY c.c_name, o.o_orderkey
    ORDER BY total_amount DESC
    LIMIT 10;
    """.strip()

    prompt = build_qep_user_prompt(sample_query)

    required_fragments = [
        "Return JSON only.",
        "PostgreSQL QEP (JSON):",
        '"Node Type"',
        '"Plans"',
        '"Startup Cost"',
        '"Total Cost"',
    ]

    missing = [fragment for fragment in required_fragments if fragment not in prompt]
    if missing:
        raise AssertionError(f"Prompt missing expected JSON-plan instructions: {missing}")

    print("Prompt validation passed.")
    print(prompt)

    if not args.live:
        return

    print("\nCalling get_ai_query_execution_plan()...")

    try:
        response = get_ai_query_execution_plan(sample_query)
        print(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"AI request failed: {exc}")


if __name__ == "__main__":
    main()

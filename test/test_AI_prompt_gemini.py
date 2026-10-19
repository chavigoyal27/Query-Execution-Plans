import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from preprocessing import get_ai_query_execution_plan


def main():
    # Delegate to preprocessing.get_ai_query_execution_plan (Gemini-first implementation)
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
    """

    print("Calling get_ai_query_execution_plan()...")

    try:
        response = get_ai_query_execution_plan(sample_query)
        print(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"AI request failed: {exc}")


if __name__ == "__main__":
    main()

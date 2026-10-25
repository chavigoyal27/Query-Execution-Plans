# Comparing PostgreSQL and AI query plans

## 1. What the project asks for

For the same SQL query, the software should obtain a plan from PostgreSQL and a
plan from an AI model. It should identify their similarities and differences and
explain them. The GUI should display both plans as trees and highlight changes.
The solution must work without hardcoding table names or SQL queries.

The report must explain the algorithm with examples, define and justify a
“difference rate”, test a diverse set of queries, and discuss limitations.
The document lets us choose the metric; it does not prescribe a formula.

## 2. What comparison.py does

The retrieval functions in preprocessing.py obtain the plans. Then call:

```python
result = compare_plans(postgresql_plan, ai_plan)
```

comparison.py compares the two supplied plans. It does not contact PostgreSQL or
Gemini. The caller must provide plans for the same SQL query and database.

Each plan is a tree. A **node** is one operation, such as a scan, join, or sort.
A node's **children** are the operations that provide its input.

```text
Hash Join
|-- Seq Scan on orders
`-- Seq Scan on customer
```

This simplified example has three nodes. Real PostgreSQL plans may have extra
nodes, such as a Hash node. Those nodes are included in our comparison.

## 3. What “fixture” means in the demo

A fixture is a prepared test example. In our demo, it is a small plan written in
Python so we know exactly what the expected answer should be. It does not come
from a new PostgreSQL or AI request.

| Demo name | What it checks |
|---|---|
| fixture_identical | Two copies of the same example plan should have no differences. |
| fixture_changed_scan | Change one scan from Sequential Scan to Index Scan; the comparator should locate that change. |
| fixture_reordered_inputs | Swap the two inputs of a join; the comparator should detect the changed order. |
| live | Retrieve actual PostgreSQL and Gemini plans for the same query and compare them. |

Prepared examples check that the code behaves as expected. The live tests across
many queries provide the results for the report. Do not present prepared examples
as evidence of how often the AI agrees with PostgreSQL.

## 4. How the comparison works

1. **Read both trees.** Give every node an ID, such as pg_0 or ai_0. Keep its
   original details and links to its children. Accept PostgreSQL-style JSON,
   including a root node directly, a Plan wrapper, or an EXPLAIN result array.
2. **Use consistent names.** For example, Sequential Scan becomes Seq Scan.
   HashAggregate and PostgreSQL's Aggregate with Strategy=Hashed are treated as
   the same operation and strategy. The same applies to GroupAggregate and
   Aggregate with Strategy=Sorted. Original attributes remain available for display.
3. **Find corresponding operations.** For each node, collect the tables and
   aliases used by that node and its input operations. Keep repeated occurrences.
   Combine that list with the general operation type, such as scan or join.
   Match a pair when this information identifies exactly one node on each side.
4. **Use matched parents to resolve more pairs.** Among the remaining children
   of a matched pair, match nodes whose information is unique on both sides.
   Repeat steps 3 and 4 until a complete pass adds no matches. A child match may
   make a previously ambiguous global pair unique. If several candidates remain,
   mark them uncertain rather than guessing.
5. **Compare each pair.** Check the operation, selected details, ordered inputs,
   and position in the tree. Record each definite difference with an explanation.
   An unresolved correspondence does not itself prove that a node moved or its
   inputs changed; mark affected pairs uncertain unless a difference is established.
6. **Return the results.** Include both trees, matched pairs, differences,
   similarities, node statuses, and the difference rate.

Example: both plans scan orders using alias o. One uses Seq Scan and the other
uses Index Scan. They can be paired because they access the same table and alias,
even though the scan method differs. The explanation is:

> For o, PostgreSQL uses Seq Scan; AI uses Index Scan.

The matching rules use names from the supplied plans, not a fixed list of tables.
Aliases help distinguish two uses of the same table in a self-join. Names and
aliases must be consistent between the two inputs.

The code checks details such as join type, filters, index names and conditions,
grouping keys, sort keys, output expressions, scan direction, and parallel settings.
Parallel settings include Parallel Aware, Partial Mode, and Workers Planned.
It also checks Parent Relationship (for example, InitPlan versus SubPlan), and
whether nodes have different parents or ordered children.

The matching procedure can be written as:

```text
matches = empty one-to-one mapping
repeat
    previous_count = size(matches)
    group all unmatched nodes by (operation family, relation/alias multiset)
    bind groups containing exactly one node from each plan
    for each currently matched parent pair
        group its unmatched immediate children by the same key
        bind groups containing exactly one child from each plan
until size(matches) = previous_count

compare each matched pair's canonical operator, strategy, and selected attributes
compare edges where correspondence is known or a difference can be established
mark remaining nodes unmatched or uncertain
return both trees, matches, differences, explanations, and the affected-node rate
```

For example, consider identical copies of
`Aggregate -> Gather -> Aggregate -> Hash Join -> scans`. Initially the two
aggregates share a family and input scope. Matching Gather identifies its child
aggregate. The next pass can then match the remaining root aggregates. The
seven-node version in the project brief is covered by an automated regression
test: all seven pairs match and the difference rate is zero.

Each successful pass adds at least one pair, so there are at most
`min(PostgreSQL node count, AI node count) + 1` passes, including the final pass
that makes no progress. With `n` nodes across both trees and bounded names and
attribute sizes, a conservative expected-time upper bound is `O(n^3)` with
ordinary hash-table grouping, and worst-case storage is `O(n^2)`. A node's stored
input scope and path can grow with tree size; scope-based grouping can therefore
take `O(n^2)` work per pass. These are upper bounds for the current implementation,
not a claim that typical query plans require cubic work. Deep trees are also
subject to Python's recursion limit.

The AI summary, assumptions, and suggested new indexes are kept separately. A
suggested index is not treated as an index actually used by the plan.

## 5. Why the difference-rate formula is (2*C + U) / N

We chose to measure **the share of nodes involved in a difference**, counting
nodes from both plans. This is our project metric, not a PostgreSQL formula or a
formula required by the document.

| Symbol | Meaning |
|---|---|
| C | Number of matched pairs with at least one difference |
| U | Number of individual nodes with no matching node in the other plan |
| N | Total number of nodes in both plans combined |

```text
difference_rate = (2*C + U) / N
```

Why multiply C by two? A changed pair contains two nodes: one PostgreSQL node
and one AI node. Both are involved in the difference. An unmatched node occurs
on only one side, so it contributes one.

### Example: one changed scan

Each plan has three nodes. Only one corresponding scan pair changes.

```text
C = 1 changed pair
U = 0 unmatched nodes
N = 3 + 3 = 6 nodes

Difference rate = (2*1 + 0) / 6 = 33.3%
```

### Example: one extra node

Suppose one plan adds a Sort above a three-node plan. The other plan still has
three nodes. With the current rules, the original root pair is also changed:
its position differs because one side now has a Sort parent.

```text
C = 1 changed pair
U = 1 extra Sort node
N = 3 + 4 = 7 nodes

Difference rate = (2*1 + 1) / 7 = 42.9%
```

A single edit can therefore affect several nodes. This score counts affected
nodes, not the smallest number of edits needed to change one tree into another.

A pair counts once even if its scan method, index name, and filter all differ.
The result ranges from 0 to 1; multiply by 100 for a percentage. Zero means no
differences in the properties we compare. It does not prove identical SQL results
or performance. A high score means more disagreement, not that AI is worse.

If matching is uncertain, difference_rate is null: the score is unavailable.
Do not turn null into zero when calculating averages.

The output also keeps operation_difference_rate, the older measure based only
on operation counts. That measure ignores tree order and can be zero even when
the join inputs differ. Use difference_rate as the main measure under these rules.

## 6. Information returned for the GUI

| Field | What it provides |
|---|---|
| mode | tree for the new format; legacy_steps for the older flat AI list |
| trees | Both trees, with root IDs, node details, and ordered child IDs |
| matches | Links between corresponding PostgreSQL and AI nodes |
| differences | What changed, before/after details, explanations, and affected node IDs |
| similarities | Same operation types found in corresponding nodes; other details may still differ |
| node_annotations | Status, counterpart ID, and difference IDs for nodes on both sides |
| unresolved_matches | Nodes whose correspondence could not be determined |
| ai_metadata | AI summary, assumptions, and suggested indexes |
| difference_rate | Main score defined above; null if matching is uncertain |
| metric | C, U, N, and the formula used to calculate the score |
| operation_difference_rate | Older score based only on counts of operation types |
| postgresql_operations / ai_operations | Counts of each operation type in each plan |
| shared_operations | Overlapping operation counts; not a list of matched node pairs |
| postgresql_unmatched_operations / ai_unmatched_operations | Leftover operation counts after subtracting overlaps |
| same_ordered_structure | Whether operators, relation identities, join types, and child order agree; it does not check every detail |
| unresolved_ai_steps | Ambiguous steps in the older AI format; empty for tree inputs |
| explanations | Text describing recorded differences, or a message that none were found |
| limitations | Notes about what the comparison does not establish |

Node statuses are unchanged, changed, unmatched, or uncertain. The GUI can assign
colors to these statuses. Unchanged means unchanged in the compared properties.
A matched pair can be uncertain when its parent or child correspondence remains
unresolved. If a definite difference is also established, its status is changed;
the overall rate remains unavailable while any correspondence is unresolved.

Each difference has an ID, kind, PostgreSQL node ID, AI node ID, details, and an
explanation. One side's ID is null for an unmatched node. The kinds are
operator_changed, attribute_changed, children_changed, parent_changed, and
unmatched_node. Node difference_ids link highlights to these explanations.

## 7. What to include in the report

Describe the matching steps above with a worked example. Define C, U, and N,
show a calculation, and justify the metric: it is bounded, gives each affected
node equal weight, and includes both changed pairs and unmatched nodes.
Also explain its weaknesses below. Do not change the rules after seeing results
just to obtain a preferred score.

Test a diverse set of your own queries, not only standard benchmark queries.
Include selective and broad filters, different joins, grouping, sorting, limits,
and other SQL features supported by the retrieval code. Test more than one schema
to demonstrate that the comparison does not depend on specific table names.

For each query, record the score and main differences. Report the mean score
for queries with available scores, the number included in that mean, and the
numbers of failed or uncertain comparisons. A category breakdown helps show
whether some query types are more difficult.

Record the database data, indexes, statistics, model, prompt, and test conditions.
The AI should generate its plan independently; do not give it PostgreSQL's answer.
Acknowledge LLM use as required by the project document. The report should cover
the completed system; this file describes the comparison component only.

## 8. Current limitations

- Matching follows fixed rules; it is not guaranteed to find the best possible
  correspondence. Different join groupings can leave intermediate joins unmatched.
- Repeated operations without enough identifying details may remain uncertain.
- Conditions are compared as written. Equivalent expressions with different
  spelling may be reported as differences. Quoted values are not rewritten.
- An omitted field counts as missing information. It does not prove the operation
  lacks that property when executed.
- Extra helper nodes remain in the trees and can affect several surrounding nodes.
- The score treats affected nodes equally; it does not measure how important or
  expensive a change is.
- Costs, row estimates, execution times, and unknown attributes are kept but are
  not included in the main score. AI estimates are not measured execution results.
- Unknown operation types are kept, but different spellings may not be matched.
- Large, deeply nested plans need more processing and memory because many nodes
  repeat information about the same input tables. No linear-time claim is made.
- The older flat steps format supports only operation counts, not full tree
  comparison or the main difference rate.

## 9. Running the examples

```powershell
# Prepared examples: no PostgreSQL or Gemini request
python test/demo_tree_comparison.py

# Prepared examples plus a real comparison: one Gemini request
python test/demo_tree_comparison.py --live

# Compare two saved JSON files
python comparison.py postgres_plan.json ai_plan.json

# Run the automated comparison tests
python -m unittest discover -s test -p test_comparison.py -v

# Check AI prompts without a database connection or Gemini request
python -m unittest discover -s test -p test_AI_prompt_gemini.py -v
```

The demo saves full JSON results under demo_output/tree_comparison.
The AI prompt includes the actual user query; its fixed example is labeled as a
format example. Run `python test/test_AI_prompt_gemini.py --live` only when you
intend to request a plan from Gemini.

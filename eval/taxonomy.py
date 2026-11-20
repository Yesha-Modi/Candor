"""Name every failure, so the README can describe them instead of counting them.

    python -m eval.taxonomy results/schema_gemini_gemini-3.1-flash-lite.jsonl
    python -m eval.taxonomy results/*.jsonl

"CANDOR answers 78% of questions" is a claim. "CANDOR's failures are 2
fan-outs, 3 silent column substitutions and 3 meaningless groupings" is
evidence, and the second one is what survives being asked a follow-up
question.

Every rule here was written from a failure actually observed in a run, not
from imagining what might go wrong. The rules read the SQL as a syntax tree
rather than as text, for the same reason the guard does.

The last category is `unexplained`. Its size is the honest measure of how
well these rules understand their own subject, so it is reported rather than
quietly absorbed into a neighbour.
"""

import argparse
import glob
import json
import re
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot import exp

from eval.run_gold import load_questions

# Columns that belong to one ORDER. Aggregating these after joining
# fct_order_items weights every order by how many items it contains.
ORDER_LEVEL = {
    "order_value", "days_to_deliver", "review_score", "worst_review_score",
    "review_count", "is_late", "freight_total",
}

# Pairs where one column is a plausible stand-in for the other and the
# difference is money. item_total includes freight; item_price does not.
SUBSTITUTES = {
    "item_total": "item_price",
    "freight_total": "freight_price",
}

# Date columns that cannot identify a period in a multi-year dataset.
# "April" is three different Aprils when the data spans 2016-2018.
AMBIGUOUS_DATE_COLUMNS = {"month_name", "day_name", "month", "quarter", "weekday"}

GOOD_VERDICTS = {"match", "match_reordered", "decision_right"}
NOT_SCORED = {"api_error", "gold_sql_error", "no_gold_sql"}


def dedupe(records: list[dict]) -> list[dict]:
    """Keep the LAST record per question id.

    The results file is an append-only log. A question retried after an
    api_error appears twice, and the later record is the real one. Counting
    both would score one question twice and skew every number built on it.
    """
    latest: dict[str, dict] = {}
    for r in records:
        latest[r["id"]] = r
    return list(latest.values())


def _tree(sql: str):
    try:
        return sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return None


def _columns(tree) -> set[str]:
    return {c.name.lower() for c in tree.find_all(exp.Column) if c.name}


def _tables(tree) -> set[str]:
    return {t.name.lower() for t in tree.find_all(exp.Table) if t.name}


def _aggregated_columns(tree) -> set[str]:
    """Columns sitting inside an aggregate function."""
    found = set()
    for node in tree.find_all(exp.AggFunc):
        found |= {c.name.lower() for c in node.find_all(exp.Column) if c.name}
    return found


def _has_distinct_dedup(tree) -> bool:
    """A `select distinct` anywhere -- the aggregate-then-join guard."""
    return any(s.args.get("distinct") for s in tree.find_all(exp.Select))


def _group_columns(tree) -> set[str]:
    found = set()
    for group in tree.find_all(exp.Group):
        found |= {c.name.lower() for c in group.find_all(exp.Column) if c.name}
    return found


def _filters(tree) -> set[str]:
    found = set()
    for where in tree.find_all(exp.Where):
        found |= {c.name.lower() for c in where.find_all(exp.Column) if c.name}
    return found


def _ratio_of_first_difference(detail: str) -> float | None:
    """Pull the two numbers out of a value_mismatch detail and divide them."""
    numbers = re.findall(r"(-?\d+\.\d+)", detail or "")
    if len(numbers) < 2:
        return None
    try:
        gold, agent = float(numbers[0]), float(numbers[1])
    except ValueError:
        return None
    if agent == 0:
        return None
    return abs(gold / agent)


def classify(record: dict, gold: dict | None, metric_names: set[str]) -> str:
    """One tag per failure. First matching rule wins, so order is the design."""
    verdict = record.get("verdict")

    if verdict in GOOD_VERDICTS:
        return "correct"
    if verdict in NOT_SCORED:
        return "not_scored"

    if verdict == "decision_wrong":
        return f"wrong_decision_{record.get('expected')}_got_{record.get('decision')}"

    if verdict == "guard_blocked":
        return "guard_blocked"

    if verdict == "answer_error":
        detail = record.get("detail", "")
        if "MAX_TOKENS" in detail:
            # A reasoning model that spent its whole output budget thinking
            # and had nothing left to answer with.
            return "exhausted_token_budget"
        if "not a valid AgentResponse" in detail:
            return "unparseable_output"
        return "no_answer_produced"

    if verdict == "sql_error":
        detail = record.get("detail", "")
        missing = re.search(r'column "([^"]+)" not found', detail)
        if missing and missing.group(1).lower() in metric_names:
            # Selecting a metric NAME as though it were a column: the failure
            # mode that appeared only after the column inventory was added.
            return "metric_used_as_column"
        if "not found" in detail or "does not have a column" in detail:
            return "invented_column"
        return "invalid_sql"

    agent_tree = _tree(record.get("sql") or "")
    gold_tree = _tree((gold or {}).get("sql") or "")

    if verdict == "shape_mismatch":
        detail = record.get("detail", "")
        m = re.search(r"gold (\d+)x(\d+), agent (\d+)x(\d+)", detail)
        if m:
            g_rows, g_cols, a_rows, a_cols = map(int, m.groups())
            if g_rows == a_rows and a_cols > g_cols:
                return "over_answering"
            if g_rows == a_rows and a_cols < g_cols:
                return "under_answering"
            return "wrong_row_set"
        return "shape_mismatch_other"

    if verdict == "value_mismatch" and agent_tree is not None:
        agg = _aggregated_columns(agent_tree)
        tables = _tables(agent_tree)

        # Fan-out: items joined in, then an order-level column aggregated,
        # with no de-duplication anywhere.
        if "fct_order_items" in tables and agg & ORDER_LEVEL \
                and not _has_distinct_dedup(agent_tree):
            return "fan_out"

        # Counting items where the gold counts distinct orders.
        if gold_tree is not None:
            gold_counts_distinct = any(
                c.args.get("this") and isinstance(c.args["this"], exp.Distinct)
                for c in gold_tree.find_all(exp.Count))
            agent_counts_distinct = any(
                c.args.get("this") and isinstance(c.args["this"], exp.Distinct)
                for c in agent_tree.find_all(exp.Count))
            if gold_counts_distinct and not agent_counts_distinct:
                return "fan_out_count"

        # A money column swapped for a near neighbour.
        agent_cols = _columns(agent_tree)
        gold_cols = _columns(gold_tree) if gold_tree is not None else set()
        for wrong, right in SUBSTITUTES.items():
            if wrong in agent_cols and right in gold_cols and wrong not in gold_cols:
                return "column_substitution"

        # Grouped by something that cannot identify the period.
        if _group_columns(agent_tree) & AMBIGUOUS_DATE_COLUMNS:
            return "meaningless_grouping"

        # A filter the gold applies and the agent does not.
        if gold_tree is not None:
            dropped = _filters(gold_tree) - _filters(agent_tree)
            if dropped & {"is_delivered", "review_count", "delivered_at"}:
                return "missing_filter"

        # Gold needs a window function and the agent wrote none.
        if gold_tree is not None and \
                any(gold_tree.find_all(exp.Window)) and \
                not any(agent_tree.find_all(exp.Window)):
            return "missing_window_function"

        # Out by a round factor of ten: a units disagreement, not an error.
        ratio = _ratio_of_first_difference(record.get("detail", ""))
        if ratio and any(abs(ratio - f) < 0.05 * f for f in (10, 100, 1000)):
            return "units_mismatch"

        return "unexplained_value_difference"

    return f"unclassified_{verdict}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", help="one or more results .jsonl")
    parser.add_argument("--list", action="store_true",
                        help="also print every failure with its tag")
    args = parser.parse_args()

    gold = {q["id"]: q for q in load_questions()}
    metric_names = {m["name"].lower() for m in
                    __import__("agent.prompt", fromlist=["load_layer"])
                    .load_layer()["metrics"]}

    # PowerShell does not expand wildcards before handing arguments to a
    # program -- that is the shell's job on Unix and the program's job on
    # Windows. So `results/semantic_*.jsonl` arrives here as a literal string
    # and has to be expanded here, or the tool works on one platform only.
    paths: list[Path] = []
    for pattern in args.results:
        matches = sorted(glob.glob(pattern))
        if matches:
            paths.extend(Path(m) for m in matches)
        else:
            paths.append(Path(pattern))

    for path in paths:
        if not path.exists():
            print(f"missing: {path}")
            continue

        with open(path, encoding="utf-8") as f:
            records = dedupe([json.loads(line) for line in f if line.strip()])

        tags = []
        for r in records:
            tag = classify(r, gold.get(r["id"]), metric_names)
            tags.append((r["id"], tag))

        failures = [(qid, t) for qid, t in tags
                    if t not in {"correct", "not_scored"}]

        print(f"\n{path.stem}")
        print("=" * 62)
        print(f"  {len(records) - len(failures)}/{len(records)} correct, "
              f"{len(failures)} failures\n")

        for tag, count in Counter(t for _, t in failures).most_common():
            ids = ", ".join(qid for qid, t in failures if t == tag)
            print(f"  {count:>2}  {tag}")
            print(f"      {ids}")

        unexplained = sum(1 for _, t in failures
                          if t == "unexplained_value_difference")
        if failures:
            print(f"\n  unexplained: {unexplained} of {len(failures)} failures "
                  f"({100 * unexplained / len(failures):.0f}%)")

        if args.list:
            print()
            for qid, tag in tags:
                if tag not in {"correct", "not_scored"}:
                    print(f"    {qid}  {tag}")


if __name__ == "__main__":
    main()
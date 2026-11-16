"""Compare an agent's result against the gold result.

Separated from the runner on purpose: this file is pure functions over
DataFrames, so it can be tested without an API key, a network, or a model.
The runner is thin and this is where the judgement lives.

Three ideas it rests on:

1. Column NAMES are not part of correctness. The agent may call the column
   `revenue`, `total`, or `round(sum(item_price), 2)`. Whether the label is
   good is a separate judgement, made by label_quality() below, because a
   right number under a wrong name is a different failure from a wrong number.
2. Row ORDER is not part of correctness unless the question asked for a
   ranking. Comparing sorted rows avoids calling a correct answer wrong
   because ORDER BY broke a tie differently.
3. Floats need a tolerance. Money rounded two ways can differ in the last
   cent without anyone being wrong.
"""

import math

MONEY_DP = 2


def _cell(value) -> object:
    """One comparable value: numbers rounded, nulls unified, rest as text."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return round(value, MONEY_DP)
    if isinstance(value, int):
        return float(value)
    if isinstance(value, bool):
        return bool(value)
    return str(value).strip()


def _rows(df) -> list[tuple]:
    return [tuple(_cell(v) for v in row) for row in df.itertuples(index=False)]


def compare(gold_df, agent_df, ordered: bool = False) -> tuple[str, str]:
    """Return (verdict, detail).

    verdict is one of:
      match               the same values, same column order
      match_reordered     the same values, columns in a different order
      value_mismatch      same shape, different values
      shape_mismatch      a different number of rows or columns
    """
    g, a = _rows(gold_df), _rows(agent_df)

    if gold_df.shape != agent_df.shape:
        return ("shape_mismatch",
                f"gold {gold_df.shape[0]}x{gold_df.shape[1]}, "
                f"agent {agent_df.shape[0]}x{agent_df.shape[1]}")

    if not ordered:
        g_cmp = sorted(g, key=lambda r: [str(x) for x in r])
        a_cmp = sorted(a, key=lambda r: [str(x) for x in r])
    else:
        g_cmp, a_cmp = g, a

    if g_cmp == a_cmp:
        return ("match", "")

    # Same values, columns in a different order: sort within each row too.
    # This fallback must honour `ordered` as well, or a ranking returned in the
    # wrong order gets forgiven here after being correctly caught above.
    g_loose = [tuple(sorted(str(x) for x in r)) for r in g]
    a_loose = [tuple(sorted(str(x) for x in r)) for r in a]
    if not ordered:
        g_loose, a_loose = sorted(g_loose), sorted(a_loose)
    if g_loose == a_loose:
        return ("match_reordered", "same values, different column order")

    differing = sum(1 for x, y in zip(g_cmp, a_cmp) if x != y)
    first = next(((x, y) for x, y in zip(g_cmp, a_cmp) if x != y), None)
    return ("value_mismatch",
            f"{differing} of {len(g_cmp)} rows differ; first DIFFERENCE at "
            f"gold {first[0]} vs agent {first[1]}" if first else "values differ")


def label_quality(agent_df, metrics_used: list[str]) -> tuple[str, str]:
    """Judge the column labels, separately from the numbers.

    Both cases below were found by hand in Session 8 and Session 9. Automating
    them is the only way they get counted rather than remembered.
    """
    problems = []

    for column in agent_df.columns:
        name = str(column)

        # An expression as a column name means no alias was given.
        if "(" in name or name.strip().isdigit():
            problems.append(f"column {name!r} has no alias")
            continue

        # "revenue" when the metric was item_revenue: right number, wrong name.
        # item_revenue excludes freight, so the plain word overstates nothing
        # -- it understates by whatever freight would have added.
        lower = name.lower()
        if lower in {"revenue", "total_revenue", "sales"} and \
                "item_revenue" in metrics_used and "revenue" not in metrics_used:
            problems.append(
                f"column {name!r} names the metric 'revenue' but "
                f"'item_revenue' was used, which excludes freight"
            )

    if not problems:
        return ("ok", "")
    return ("mislabelled", "; ".join(problems))
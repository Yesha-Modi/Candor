"""Decide whether a generated query is safe to execute.

The agent writes SQL. Nothing about a language model guarantees that SQL only
reads -- not the prompt, not the schema, not good behaviour on the last fifty
questions. So the query is inspected before it runs.

This parses the SQL into a syntax tree and judges the tree, not the text.
Judging text means regular expressions, and regular expressions lose to
comments, whitespace, casing, and nesting. The tree is what DuckDB will
actually execute.

    from agent.guard import validate_sql
    problems = validate_sql(sql, allowed_tables)
    if problems:
        ...refuse...
"""

import re

import sqlglot
from sqlglot import exp

# A query may only be a SELECT, or a set operation built from SELECTs.
ALLOWED_STATEMENTS = (exp.Select, exp.Union, exp.Except, exp.Intersect)

# Functions that reach outside the database: the local filesystem, the
# network, or the SQL parser itself. Patterns rather than a fixed list,
# because DuckDB ships roughly ninety read_*/`*_scan` functions and more
# arrive with every release.
DENIED_FUNCTION_PATTERNS = (
    re.compile(r"^read_"),            # read_csv, read_text, read_blob, read_parquet...
    re.compile(r"_scan$"),            # parquet_scan, arrow_scan, pandas_scan, postgres_scan
    re.compile(r"^glob$"),            # directory listing
    re.compile(r"^sniff_csv$"),       # inspects a file on disk
    re.compile(r"^parse_filename$"),
    re.compile(r"^parquet_"),         # parquet_metadata, parquet_schema, ...
    re.compile(r"serialize_sql$"),    # json_serialize_sql / json_deserialize_sql
    re.compile(r"^json_execute_"),    # json_execute_serialized_sql -- runs SQL from JSON
    re.compile(r"^duckdb_"),          # internal catalogs: duckdb_temporary_files, ...
)


def _tidy(error: Exception) -> str:
    """One readable line out of a parser error.

    sqlglot points at the offending token with ANSI colour codes and newlines,
    which is helpful in a terminal and unreadable inside a longer message.
    """
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(error))
    return " ".join(text.split())[:160]


def allowed_tables_from_layer(layer: dict) -> set[str]:
    """The table allowlist, taken from the semantic layer itself.

    Deliberately not a list typed into this file. The model is told which
    tables exist by the semantic layer; the guard must allow exactly those.
    Two hand-maintained lists drift, and a guard that drifts either blocks
    real questions or permits tables nobody declared.
    """
    return {t["name"].strip().lower() for t in layer["tables"]}


def _function_name(node: exp.Func) -> str:
    """The name as written, for both modelled and unmodelled functions."""
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return node.sql_name().lower()


def validate_sql(sql: str, allowed_tables: set[str]) -> list[str]:
    """Return a list of reasons the query must not run. Empty means safe.

    allowed_tables holds fully qualified lowercase names, e.g.
    {"marts.fct_orders", "marts.dim_products"}.
    """
    if not sql or not sql.strip():
        return ["the query is empty"]

    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except Exception as e:
        return [f"the query does not parse as DuckDB SQL: {_tidy(e)}"]

    if len(statements) != 1:
        return [f"expected exactly one statement, found {len(statements)}"]

    statement = statements[0]
    if statement is None:
        return ["the query parsed to nothing"]

    problems: list[str] = []

    # exp.Command is sqlglot's "I could not parse this" node. Anything that
    # lands there is unreadable, and unreadable is not the same as harmless.
    if isinstance(statement, exp.Command):
        problems.append(
            f"the query uses syntax the parser does not model "
            f"({statement.sql(dialect='duckdb')[:40]!r}), so it cannot be checked"
        )
    elif not isinstance(statement, ALLOWED_STATEMENTS):
        problems.append(
            f"only SELECT is allowed, this statement is "
            f"{type(statement).__name__.upper()}"
        )

    # CTE names look like tables in the tree, so they are allowed by name.
    cte_names = {c.alias_or_name.lower() for c in statement.find_all(exp.CTE)}

    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        schema = (table.db or "").lower()

        if not name:
            problems.append("a data source is a function or a file, not a table")
            continue

        if not schema and name in cte_names:
            continue

        qualified = f"{schema}.{name}" if schema else name
        if qualified not in allowed_tables:
            problems.append(f"table {qualified!r} is not in the semantic layer")

    for node in statement.find_all(exp.Func):
        fname = _function_name(node)
        if any(p.search(fname) for p in DENIED_FUNCTION_PATTERNS):
            problems.append(f"function {fname!r} reaches outside the database")

    return problems
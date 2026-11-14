"""Check that every definition in the semantic layer actually works.

A semantic layer is a promise to the agent about what exists. If a metric
references a dropped column or a join path is wrong, the agent inherits the
error and there is nothing in its output to reveal it. So every definition is
executed against the real database before it is trusted.
"""

import sys

import duckdb
import yaml

from src.config import PROJECT_ROOT, DB_PATH

LAYER_PATH = PROJECT_ROOT / "semantic" / "semantic_layer.yaml"


def load_layer() -> dict:
    with open(LAYER_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_metric_sql(metric: dict) -> str:
    sql = f"select {metric['expression']} as value from {metric['table']}"
    if metric.get("filters"):
        sql += " where " + " and ".join(metric["filters"])
    return sql


def build_join_sql(join: dict) -> str:
    on = join["condition"].replace("{from}", join["from"]).replace("{to}", join["to"])
    return f"select 1 from {join['from']} join {join['to']} on {on} limit 1"


def build_dimension_sql(dim: dict) -> str:
    return f"select {dim['column']} from {dim['table']} limit 1"


def main() -> None:
    layer = load_layer()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    failures = []

    print(f"\nValidating {LAYER_PATH.name}\n" + "=" * 62)

    # --- tables exist ---
    known = {
        f"{s}.{t}"
        for s, t in con.execute(
            "select table_schema, table_name from information_schema.tables"
        ).fetchall()
    }
    for table in layer["tables"]:
        ok = table["name"] in known
        print(f"{'ok  ' if ok else 'FAIL'}  table      {table['name']}")
        if not ok:
            failures.append(f"table {table['name']} does not exist")

    # --- metrics run and return a value ---
    for metric in layer["metrics"]:
        try:
            value = con.execute(build_metric_sql(metric)).fetchone()[0]
            print(f"ok    metric     {metric['name']:<24} = {value}")
        except Exception as e:
            failures.append(f"metric {metric['name']}: {str(e).splitlines()[0]}")
            print(f"FAIL  metric     {metric['name']:<24} {str(e).splitlines()[0]}")

    # --- dimensions exist ---
    for dim in layer["dimensions"]:
        try:
            con.execute(build_dimension_sql(dim))
            print(f"ok    dimension  {dim['name']}")
        except Exception as e:
            failures.append(f"dimension {dim['name']}: {str(e).splitlines()[0]}")
            print(f"FAIL  dimension  {dim['name']:<24} {str(e).splitlines()[0]}")

    # --- join paths are valid ---
    for join in layer["joins"]:
        label = f"{join['from']} -> {join['to']}"
        try:
            con.execute(build_join_sql(join))
            print(f"ok    join       {label}")
        except Exception as e:
            failures.append(f"join {label}: {str(e).splitlines()[0]}")
            print(f"FAIL  join       {label}: {str(e).splitlines()[0]}")

    # --- every metric and dimension names a declared table ---
    declared = {t["name"] for t in layer["tables"]}
    for item in layer["metrics"] + layer["dimensions"]:
        if item["table"] not in declared:
            failures.append(f"{item['name']} uses undeclared table {item['table']}")

    # --- synonyms must be unique across metrics and dimensions ---
    seen = {}
    for item in layer["metrics"] + layer["dimensions"]:
        for syn in item.get("synonyms", []):
            key = syn.lower()
            if key in seen:
                failures.append(
                    f"synonym '{syn}' claimed by both {seen[key]} and {item['name']}"
                )
            seen[key] = item["name"]

    con.close()

    print("=" * 62)
    if failures:
        print(f"{len(failures)} problem(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    counts = {k: len(v) for k, v in layer.items() if isinstance(v, list)}
    print("All definitions valid.")
    print("  " + "  ".join(f"{k}: {n}" for k, n in counts.items()))
    print()


if __name__ == "__main__":
    main()
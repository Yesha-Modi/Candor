"""Re-score a finished results file against the CURRENT gold file.

    python -m eval.rescore results/semantic_..._v1_nocolumns.jsonl

No API calls. It re-executes the SQL already stored in the results file and
compares it to the gold queries as they stand now, writing <name>_rescored.jsonl.

Why this is needed: the v1 run was scored against the old gold file and the v2
run against the repaired one. Comparing them directly measures the prompt
change AND the gold repair at once, and attributes the whole difference to
whichever one you were hoping for. Re-scoring v1 against the same gold that
scored v2 removes the gold repair from the comparison, leaving only the thing
that actually changed in the prompt.

The stored SQL is what the model produced at the time, so this is not a
re-run with hindsight -- it is the same answers, marked by the same rubric.
"""

import argparse
import json
from pathlib import Path

import duckdb

from src.config import DB_PATH
from eval.run_gold import load_questions
from eval.score import compare, label_quality

ORDERED_CATEGORIES = {"ranking"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", help="path to a results .jsonl")
    args = parser.parse_args()

    src = Path(args.results)
    if not src.exists():
        raise SystemExit(f"no such file: {src}")

    gold = {q["id"]: q for q in load_questions()}
    con = duckdb.connect(str(DB_PATH), read_only=True)
    out = src.with_name(src.stem + "_rescored.jsonl")

    changed = 0
    with open(src, encoding="utf-8") as f, open(out, "w", encoding="utf-8") as w:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            before = r.get("verdict")
            q = gold.get(r["id"])

            # Only answered questions can be re-scored. A decision verdict
            # does not depend on the gold SQL, so it carries over untouched.
            if q and r.get("decision") == "answer" and r.get("decision_correct") \
                    and r.get("sql") and q.get("sql"):
                try:
                    agent_df = con.execute(r["sql"]).fetchdf()
                except Exception as e:
                    r["verdict"] = "sql_error"
                    r["detail"] = f"{type(e).__name__}: {e}"
                else:
                    try:
                        gold_df = con.execute(q["sql"]).fetchdf()
                    except Exception as e:
                        r["verdict"] = "gold_sql_error"
                        r["detail"] = f"{type(e).__name__}: {e}"
                    else:
                        ordered = q["category"] in ORDERED_CATEGORIES
                        verdict, detail = compare(gold_df, agent_df, ordered=ordered)
                        r["verdict"] = verdict
                        r["detail"] = detail
                        lab, lab_detail = label_quality(
                            agent_df, r.get("metrics_used") or [])
                        r["label"] = lab
                        r["label_detail"] = lab_detail

            r["rescored_from"] = before
            if r["verdict"] != before:
                changed += 1
                print(f"  {r['id']}  {before} -> {r['verdict']}")
            w.write(json.dumps(r) + "\n")

    con.close()
    print(f"\n{changed} verdicts changed. Written to {out}")
    print("Report it with:  python -m eval.report --mode semantic")


if __name__ == "__main__":
    main()
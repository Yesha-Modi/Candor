"""Print the question and gold SQL for given ids.

    python -m eval.show_gold Q014,Q019,Q022
    python -m eval.show_gold --failing results/semantic_gemini_gemini-3.1-flash-lite.jsonl

For inspecting the reference queries when the benchmark disagrees with them.
The gold file is an artifact like any other: when agent and gold disagree,
the gold is a suspect too, not the arbiter.
"""

import argparse
import json
from pathlib import Path

from eval.run_gold import load_questions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="?", default=None,
                        help="comma-separated, e.g. Q014,Q019")
    parser.add_argument("--failing", default=None,
                        help="a results .jsonl -- show the gold for every failure in it")
    args = parser.parse_args()

    wanted: set[str] = set()
    if args.ids:
        wanted |= {i.strip().upper() for i in args.ids.split(",")}

    if args.failing:
        good = {"match", "match_reordered", "decision_right"}
        with open(args.failing, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r.get("verdict") not in good:
                        wanted.add(r["id"])

    if not wanted:
        raise SystemExit("give ids or --failing")

    for q in load_questions():
        if q["id"] not in wanted:
            continue
        print(f"\n{q['id']}  [{q['category']}]  expected={q['expected_behavior']}")
        print(f"  Q: {q['question']}")
        sql = (q.get("sql") or "").strip()
        if sql:
            for line in sql.splitlines():
                print(f"     {line}")


if __name__ == "__main__":
    main()
"""Run every gold query and show its result, so each answer can be verified by eye."""

import argparse

import duckdb
import pandas as pd
import yaml

from src.config import PROJECT_ROOT, DB_PATH

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

GOLD_PATH = PROJECT_ROOT / "eval" / "gold_questions.yaml"


def load_questions() -> list[dict]:
    with open(GOLD_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="run a single question, e.g. Q007")
    parser.add_argument("--category", help="run one category only")
    parser.add_argument("--unverified", action="store_true",
                        help="only questions not yet marked verified")
    args = parser.parse_args()

    questions = load_questions()

    if args.id:
        questions = [q for q in questions if q["id"] == args.id]
    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
    if args.unverified:
        questions = [q for q in questions if not q.get("verified", False)]

    if not questions:
        print("No questions matched those filters.")
        return

    con = duckdb.connect(str(DB_PATH), read_only=True)
    failures = []

    for q in questions:
        flag = "verified" if q.get("verified") else "UNVERIFIED"
        print(f"\n{'=' * 74}")
        print(f"{q['id']}  [{q['category']}]  ({flag})")
        print(f"{'=' * 74}")
        print(f"Q: {q['question']}\n")

        if q["expected_behavior"] != "answer":
            print(f"Expected behaviour: {q['expected_behavior'].upper()}")
            print(f"Reason: {q.get('reason', '(none given)')}")
            continue

        print(q["sql"].strip())
        print()

        try:
            print(con.execute(q["sql"]).fetchdf().to_string(index=False))
        except Exception as e:
            failures.append((q["id"], str(e).splitlines()[0]))
            print(f"ERROR: {e}")

    con.close()

    print(f"\n{'=' * 74}")
    print(f"Ran {len(questions)} questions, {len(failures)} errored.")
    for qid, msg in failures:
        print(f"  {qid}: {msg}")
    print()


if __name__ == "__main__":
    main()
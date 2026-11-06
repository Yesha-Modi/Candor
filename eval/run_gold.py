"""Run every gold query and show its result, so each answer can be verified by eye."""

import argparse
from collections import Counter

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


def show_summary(questions: list[dict]) -> None:
    done = Counter()
    total = Counter()

    for q in questions:
        total[q["category"]] += 1
        if q.get("verified"):
            done[q["category"]] += 1

    print("\nVerification progress")
    print("=" * 56)

    for category in total:
        n, d = done[category], total[category]
        filled = round(15 * n / d) if d else 0
        bar = "#" * filled + "." * (15 - filled)
        print(f"  {category:<20} {n:>3}/{d:<3}  {bar}")

    print("-" * 56)
    n, d = sum(done.values()), sum(total.values())
    pct = round(100 * n / d) if d else 0
    print(f"  {'TOTAL':<20} {n:>3}/{d:<3}  {pct}%\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="run a single question, e.g. Q007")
    parser.add_argument("--category", help="run one category only")
    parser.add_argument("--unverified", action="store_true",
                        help="only questions not yet marked verified")
    parser.add_argument("--summary", action="store_true",
                        help="show progress without running anything")
    args = parser.parse_args()

    questions = load_questions()

    if args.summary:
        show_summary(questions)
        return

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

        if q.get("notes"):
            print(f"\nNotes: {q['notes']}")

    con.close()

    print(f"\n{'=' * 74}")
    print(f"Ran {len(questions)} questions, {len(failures)} errored.")
    for qid, msg in failures:
        print(f"  {qid}: {msg}")

    show_summary(load_questions())


if __name__ == "__main__":
    main()
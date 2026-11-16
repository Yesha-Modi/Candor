"""Turn a results file into the numbers that go in the README.

    python -m eval.report --mode semantic
    python -m eval.report --mode semantic --mode schema     (compare two runs)

Reports per category, not one overall figure. 95% on simple aggregates and
40% on joins is a different story from 70% everywhere, and only the first
tells you what to fix.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from src.config import PROJECT_ROOT

RESULTS_DIR = PROJECT_ROOT / "results"

# A correct outcome is a correct DECISION plus, where it answered, the right
# numbers. Everything else is a failure of some named kind.
CORRECT_VERDICTS = {"match", "match_reordered", "decision_right"}

# Not the model's fault. Counted and reported, never scored.
EXCLUDED_VERDICTS = {"api_error", "gold_sql_error", "no_gold_sql"}


def load(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"no results at {path}. Run eval.benchmark first.")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def is_correct(r: dict) -> bool:
    if not r.get("decision_correct"):
        return False
    if r["expected"] in {"clarify", "refuse"}:
        return True          # the decision IS the answer for these
    return r.get("verdict") in CORRECT_VERDICTS


def show_failures(records: list[dict]) -> None:
    """Every failure with its reason, compactly.

    Written because triaging 60 results by reading them one at a time is how
    a systematic bug gets mistaken for a run of bad luck. A cluster of
    identical reasons is a different problem from scattered ones.
    """
    bad = [r for r in records if not is_correct(r)]
    if not bad:
        print("\n  No failures.")
        return

    print(f"\n  {len(bad)} failures\n")
    for r in bad:
        detail = " ".join(str(r.get("detail", "")).split())[:150]
        print(f"  {r['id']}  {r['category']:<18} {r['verdict']}")
        if detail:
            print(f"        {detail}")
        sql = " ".join(str(r.get("sql") or "").split())
        if r["verdict"] in {"sql_error", "shape_mismatch", "value_mismatch"} and sql:
            print(f"        SQL: {sql[:200]}")


def report(records: list[dict], label: str) -> dict:
    scored = [r for r in records if r.get("verdict") not in EXCLUDED_VERDICTS]
    excluded = [r for r in records if r.get("verdict") in EXCLUDED_VERDICTS]

    by_category = defaultdict(lambda: [0, 0])
    for r in scored:
        by_category[r["category"]][1] += 1
        if is_correct(r):
            by_category[r["category"]][0] += 1

    print(f"\n{label}")
    print("=" * 62)
    for category in sorted(by_category):
        n, d = by_category[category]
        pct = 100 * n / d if d else 0
        bar = "#" * round(15 * n / d) + "." * (15 - round(15 * n / d)) if d else ""
        print(f"  {category:<22} {n:>3}/{d:<3} {pct:>5.1f}%  {bar}")

    n = sum(v[0] for v in by_category.values())
    d = sum(v[1] for v in by_category.values())
    print("-" * 62)
    print(f"  {'OVERALL':<22} {n:>3}/{d:<3} {100*n/d if d else 0:>5.1f}%")

    print("\n  Failure modes")
    for verdict, count in Counter(
            r["verdict"] for r in scored if not is_correct(r)).most_common():
        print(f"    {verdict:<20} {count}")

    labels = Counter(r.get("label") for r in scored if r.get("label"))
    if labels.get("mislabelled"):
        print(f"\n  Right number, wrong label: {labels['mislabelled']} "
              f"of {sum(labels.values())} answered")

    if excluded:
        print(f"\n  Excluded from scoring (not the model's fault): {len(excluded)}")
        for verdict, count in Counter(r["verdict"] for r in excluded).most_common():
            print(f"    {verdict:<20} {count}")

    return {"correct": n, "scored": d}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", action="append", required=True,
                        choices=["semantic", "schema"])
    parser.add_argument("--model", default=None,
                        help="match a specific results file, e.g. gemini_gemini-3.8-flash")
    parser.add_argument("--failures", action="store_true",
                        help="list every failure with its reason, for triage")
    args = parser.parse_args()

    totals = {}
    for mode in args.mode:
        pattern = f"{mode}_{args.model}.jsonl" if args.model else f"{mode}_*.jsonl"
        matches = sorted(RESULTS_DIR.glob(pattern))
        if not matches:
            raise SystemExit(f"no results file matching {pattern}")
        for path in matches:
            records = load(path)
            totals[path.stem] = report(records, f"{path.stem}")
            if args.failures:
                show_failures(records)

    if len(totals) > 1:
        print("\nComparison")
        print("=" * 62)
        for name, t in totals.items():
            pct = 100 * t["correct"] / t["scored"] if t["scored"] else 0
            print(f"  {name:<40} {pct:>5.1f}%")
        values = [100 * t["correct"] / t["scored"] for t in totals.values() if t["scored"]]
        if len(values) == 2:
            print(f"\n  Difference: {values[0] - values[1]:+.1f} percentage points")
            print("  One run each, so this is a reading and not yet a result. "
                  "A gap becomes a measurement when it survives a repeat.")


if __name__ == "__main__":
    main()
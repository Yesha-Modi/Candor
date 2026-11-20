"""One table: every run side by side, per category.

    python -m eval.compare
    python -m eval.compare --mode semantic

Reads every results file in results/ and prints accuracy by category with one
column per run. This is the table that goes in the README, so it reports
per-category numbers rather than a single figure -- 95% on aggregates and 20%
on time series is a different project from 68% everywhere.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from src.config import PROJECT_ROOT

RESULTS_DIR = PROJECT_ROOT / "results"
CORRECT = {"match", "match_reordered", "decision_right"}
NOT_SCORED = {"api_error", "gold_sql_error", "no_gold_sql"}

CATEGORY_ORDER = ["simple_aggregate", "multi_table_join", "time_series",
                  "ambiguous", "unanswerable"]


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


def load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return dedupe([json.loads(line) for line in f if line.strip()])


def short_name(stem: str) -> str:
    """results/semantic_gemini_gemini-3.1-flash-lite -> semantic/3.1-flash-lite

    A --tag suffix is kept, because two runs of the same model are the point
    of running it twice: collapsing them into one column would hide the
    run-to-run variation they exist to measure.
    """
    mode, _, rest = stem.partition("_")
    rest = rest.replace("gemini_gemini-", "").replace("gemini_", "")
    return f"{mode}/{rest}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=None, choices=["semantic", "schema"])
    parser.add_argument("--runs", default=None,
                        help="comma-separated substrings; only matching result "
                             "files are included. Use it to leave out a "
                             "partial run, or an older prompt condition that "
                             "is not one of the models being compared")
    parser.add_argument("--common", action="store_true",
                        help="score every run on only the questions that ALL "
                             "runs completed, so an unfinished run can still "
                             "be compared fairly")
    args = parser.parse_args()

    pattern = f"{args.mode}_*.jsonl" if args.mode else "*.jsonl"
    paths = sorted(p for p in RESULTS_DIR.glob(pattern))
    if not paths:
        raise SystemExit(f"no results files matching {pattern} in {RESULTS_DIR}")

    if args.runs:
        wanted = [w.strip() for w in args.runs.split(",") if w.strip()]
        paths = [p for p in paths if any(w in p.stem for w in wanted)]
        if not paths:
            raise SystemExit(f"no results file matched any of {wanted}")

    records = {short_name(p.stem): load(p) for p in paths}

    # Restricting to the questions every run answered is what makes a partial
    # run comparable. A model that could not finish -- out of quota, out of
    # time -- is not thereby worse at the questions it did answer, and
    # comparing its 23 against another model's 60 would say it was.
    common: set[str] | None = None
    if args.common:
        sets = [
            {r["id"] for r in rs if r.get("verdict") not in NOT_SCORED}
            for rs in records.values()
        ]
        common = set.intersection(*sets) if sets else set()
        print(f"\n  Restricted to the {len(common)} questions completed by all "
              f"{len(records)} runs.")

    # run -> category -> [correct, scored]
    table: dict[str, dict[str, list[int]]] = {}
    for run, rs in records.items():
        counts = defaultdict(lambda: [0, 0])
        for r in rs:
            if r.get("verdict") in NOT_SCORED:
                continue
            if common is not None and r["id"] not in common:
                continue
            counts[r["category"]][1] += 1
            if r.get("verdict") in CORRECT:
                counts[r["category"]][0] += 1
        table[run] = counts

    runs = list(table)
    categories = [c for c in CATEGORY_ORDER if any(c in table[r] for r in runs)]
    categories += sorted({c for r in runs for c in table[r]} - set(CATEGORY_ORDER))

    width = max(len(c) for c in categories) + 2
    # Column width from the longest run name, so nothing is silently cut off.
    # A truncated model name in a model comparison is the one thing the table
    # must never do.
    col = max(max(len(r) for r in runs), 14) + 3
    header = " " * width + "".join(f"{r:>{col}}" for r in runs)
    print()
    print(header)
    print("-" * len(header))

    for category in categories:
        row = f"{category:<{width}}"
        for run in runs:
            n, d = table[run].get(category, [0, 0])
            cell = f"{n}/{d}  {100*n/d:.0f}%" if d else "-"
            row += f"{cell:>{col}}"
        print(row)

    print("-" * len(header))
    row = f"{'OVERALL':<{width}}"
    for run in runs:
        n = sum(v[0] for v in table[run].values())
        d = sum(v[1] for v in table[run].values())
        cell = f"{n}/{d}  {100*n/d:.1f}%" if d else "-"
        row += f"{cell:>{col}}"
    print(row)
    print("\n  One run per cell. Differences smaller than about three "
          "questions are not\n  distinguishable from run-to-run variation.")


if __name__ == "__main__":
    main()
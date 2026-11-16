"""Run the gold questions through the agent and score every answer.

    python -m eval.benchmark --mode semantic
    python -m eval.benchmark --mode schema
    python -m eval.benchmark --mode semantic --limit 5
    python -m eval.benchmark --mode semantic --only Q016,Q041

Results append to results/<mode>_<model>.jsonl, one JSON object per question.
A re-run SKIPS questions already in that file, so a run killed by 503s is
resumed rather than restarted. Delete the file to start over.

That design decision is the important one: on a free tier, a sixty-question
run will be interrupted. A harness that cannot resume is a harness that never
finishes, and one that silently redoes finished work burns the quota it needs.
"""

import argparse
import json
import time
from pathlib import Path

import duckdb
import pandas as pd

from src.config import DB_PATH, PROJECT_ROOT
from agent.guard import allowed_tables_from_layer, validate_sql
from agent.prompt import build_prompt, load_layer
from agent.provider import get_provider
from agent.schema import validate_shape
from eval.run_gold import load_questions
from eval.score import compare, label_quality

RESULTS_DIR = PROJECT_ROOT / "results"
PAUSE_SECONDS = 2.0

# Questions whose wording makes row order part of the answer.
ORDERED_CATEGORIES = {"ranking"}


def already_done(path: Path) -> set[str]:
    """Question ids already recorded, so a resumed run skips them."""
    if not path.exists():
        return set()
    done = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                done.add(json.loads(line)["id"])
    return done


def run_sql(con, sql: str):
    """Execute and return (dataframe, error)."""
    try:
        return con.execute(sql).fetchdf(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def score_one(question: dict, response, con, allowed: set[str]) -> dict:
    """Everything that can be judged about one answer, without an API call."""
    expected = question["expected_behavior"]
    result = {
        "decision": response.decision,
        "decision_correct": response.decision == expected,
        "confidence": response.confidence,
        "metrics_used": response.metrics_used,
        "shape_problems": validate_shape(response),
        "sql": response.sql,
    }

    # Wrong decision: nothing further to score. A refusal has no SQL to run,
    # and an answer to a question that should have been refused is already
    # the failure -- running it would only add noise.
    if not result["decision_correct"]:
        result["verdict"] = "decision_wrong"
        result["detail"] = f"expected {expected}, got {response.decision}"
        return result

    if response.decision != "answer":
        # For a clarify or refuse question the decision IS the whole answer:
        # there is no SQL and no number to compare.
        result["verdict"] = "decision_right"
        return result

    blocked = validate_sql(response.sql, allowed)
    if blocked:
        result["verdict"] = "guard_blocked"
        result["detail"] = "; ".join(blocked)
        return result

    agent_df, agent_err = run_sql(con, response.sql)
    if agent_err:
        result["verdict"] = "sql_error"
        result["detail"] = agent_err
        return result

    gold_sql = question.get("sql")
    if not gold_sql:
        result["verdict"] = "no_gold_sql"
        return result

    gold_df, gold_err = run_sql(con, gold_sql)
    if gold_err:
        # The gold query is the reference. If it fails, the gold file is
        # wrong, not the agent -- never score this as a model failure.
        result["verdict"] = "gold_sql_error"
        result["detail"] = gold_err
        return result

    ordered = question["category"] in ORDERED_CATEGORIES
    verdict, detail = compare(gold_df, agent_df, ordered=ordered)
    result["verdict"] = verdict
    result["detail"] = detail
    result["ordered_comparison"] = ordered

    label, label_detail = label_quality(agent_df, response.metrics_used or [])
    result["label"] = label
    result["label_detail"] = label_detail
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["semantic", "schema"], default="semantic",
                        help="semantic layer, or bare schema (the control)")
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many NEW questions")
    parser.add_argument("--only", default=None,
                        help="comma-separated ids, e.g. Q016,Q041")
    args = parser.parse_args()

    questions = load_questions()
    if args.only:
        wanted = {q.strip().upper() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    kwargs = {"model": args.model} if args.model else {}
    provider = get_provider(args.provider, **kwargs)

    RESULTS_DIR.mkdir(exist_ok=True)
    safe_model = provider.name.replace("/", "_")
    out_path = RESULTS_DIR / f"{args.mode}_{safe_model}.jsonl"

    done = already_done(out_path)
    todo = [q for q in questions if q["id"] not in done]
    if args.limit:
        todo = todo[:args.limit]

    print(f"mode={args.mode}  model={provider.name}")
    print(f"{len(done)} already recorded, {len(todo)} to run")
    print(f"writing to {out_path}\n")

    layer = load_layer()
    allowed = allowed_tables_from_layer(layer)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        for i, question in enumerate(todo, 1):
            qid = question["id"]
            prompt = build_prompt(question["question"], layer, mode=args.mode)

            started = time.perf_counter()
            try:
                response, meta = provider.generate(prompt)
            except Exception as e:
                # An API failure is NOT a wrong answer. It gets its own
                # verdict so a bad evening on the free tier never shows up as
                # the model getting questions wrong.
                record = {
                    "id": qid,
                    "category": question["category"],
                    "expected": question["expected_behavior"],
                    "verdict": "api_error",
                    "detail": str(e)[:300],
                    "seconds": round(time.perf_counter() - started, 2),
                }
                print(f"  {i:>2}/{len(todo)}  {qid}  API ERROR -- stopping")
                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
                print("\nRun this command again to resume from here.")
                break

            record = {
                "id": qid,
                "category": question["category"],
                "expected": question["expected_behavior"],
                "question": question["question"],
                "mode": args.mode,
                "model": provider.name,
                "seconds": meta["seconds"],
                "prompt_tokens": meta["prompt_tokens"],
                "output_tokens": meta["output_tokens"],
            }
            record.update(score_one(question, response, con, allowed))

            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

            mark = ("ok " if record["verdict"] in
                    {"match", "match_reordered", "decision_right"} else "   ")
            print(f"  {i:>2}/{len(todo)}  {qid}  {record['decision']:<8} "
                  f"{mark}{record['verdict']}")

            time.sleep(PAUSE_SECONDS)
    finally:
        con.close()

    print(f"\nDone. Score the file with:  python -m eval.report --mode {args.mode}")


if __name__ == "__main__":
    main()
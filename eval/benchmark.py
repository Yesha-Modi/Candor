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
DEFAULT_PAUSE_SECONDS = 2.0

# Two kinds of failure arrive through the same exception, and they need
# opposite responses.
#
#   Availability: 429, 503, a timeout. The service cannot serve anyone right
#   now, so the next 59 questions will fail too -- stop the run.
#
#   Per-question: the model produced nothing parseable, or spent its whole
#   token budget thinking. That says something about THIS question, and the
#   next one may well succeed -- record it as a failure and carry on.
#
# Treating the second kind as the first means one bad question ends the run,
# every time, and no progress is ever made.
# A per-minute quota needs a wait longer than the window itself. Retrying
# inside the window just spends the quota being waited for, which is why
# provider.py no longer retries a 429 at all -- it is handled here, where the
# sleep can be long enough to matter.
RATE_LIMIT_MARKERS = ("429", "resource_exhausted")
RATE_LIMIT_WAIT_SECONDS = 65
MAX_RATE_LIMIT_WAITS = 3

AVAILABILITY_MARKERS = (
    "429", "resource_exhausted",
    "500", "502", "503", "504", "unavailable",
    "deadline", "timeout", "timed out",
)

# Questions whose wording makes row order part of the answer.
ORDERED_CATEGORIES = {"ranking"}


def is_availability_error(error: Exception) -> bool:
    """True when the service is unavailable rather than this question failing."""
    text = f"{type(error).__name__}: {error}".lower()
    return any(marker in text for marker in AVAILABILITY_MARKERS)


def is_rate_limit(error: Exception) -> bool:
    """True for a quota refusal, which is worth waiting out rather than aborting."""
    text = f"{type(error).__name__}: {error}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def generate_with_quota_waits(provider, prompt: str, qid: str):
    """Ask the provider, waiting out a per-minute quota if one is hit.

    Returns (response, meta). Raises if the question cannot be answered.

    A rate limit is not a failure of the question or of the service -- it is
    the free tier saying "not this minute". The only useful response is to
    wait longer than the window and ask again, which is why this sleeps 65
    seconds rather than retrying immediately.
    """
    for attempt in range(MAX_RATE_LIMIT_WAITS + 1):
        try:
            return provider.generate(prompt)
        except Exception as e:
            if not is_rate_limit(e) or attempt == MAX_RATE_LIMIT_WAITS:
                raise
            waited = (attempt + 1) * RATE_LIMIT_WAIT_SECONDS
            print(f"      {qid}: rate limited, waiting {RATE_LIMIT_WAIT_SECONDS}s "
                  f"(attempt {attempt + 1} of {MAX_RATE_LIMIT_WAITS}, "
                  f"{waited}s total)")
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
    raise RuntimeError("unreachable")


def already_done(path: Path) -> set[str]:
    """Question ids that have a real result, so a resumed run skips them.

    An `api_error` does NOT count as done. It is the absence of an answer, and
    treating it as one meant a question hit by a 503 was skipped forever on
    every later resume -- permanently unanswered, permanently excluded from
    the score, and shrinking the denominator with nothing in the output
    saying so.

    Retrying appends a second record for that id, so every reader of this file
    keeps the LAST record per id. The file is an append-only log, not a table.
    """
    if not path.exists():
        return set()
    done = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("verdict") == "api_error":
                done.discard(record["id"])
            else:
                done.add(record["id"])
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
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS,
                        help="seconds between questions. Raise it for a model "
                             "that rate-limits on a free tier")
    parser.add_argument("--tag", default=None,
                        help="suffix for the results filename, so the same "
                             "model can be run twice without the second run "
                             "resuming the first")
    args = parser.parse_args()

    questions = load_questions()
    if args.only:
        wanted = {q.strip().upper() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    kwargs = {"model": args.model} if args.model else {}
    provider = get_provider(args.provider, **kwargs)

    RESULTS_DIR.mkdir(exist_ok=True)
    safe_model = provider.name.replace("/", "_")
    suffix = f"_{args.tag}" if args.tag else ""
    out_path = RESULTS_DIR / f"{args.mode}_{safe_model}{suffix}.jsonl"

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
                response, meta = generate_with_quota_waits(provider, prompt, qid)
            except Exception as e:
                unavailable = is_availability_error(e)
                record = {
                    "id": qid,
                    "category": question["category"],
                    "expected": question["expected_behavior"],
                    # api_error  = the service failed us; excluded from scoring
                    #              and retried on the next run.
                    # answer_error = the model failed this question; a real
                    #              result, scored as a failure, not retried.
                    "verdict": "api_error" if unavailable else "answer_error",
                    "detail": str(e)[:300],
                    "seconds": round(time.perf_counter() - started, 2),
                    "model": provider.name,
                    "mode": args.mode,
                }
                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

                if unavailable:
                    print(f"  {i:>2}/{len(todo)}  {qid}  SERVICE UNAVAILABLE "
                          f"-- stopping")
                    print("\nRun this command again to resume from here.")
                    break

                print(f"  {i:>2}/{len(todo)}  {qid}  answer_error "
                      f"(recorded, continuing)")
                time.sleep(args.pause)
                continue

            record = {
                "id": qid,
                "category": question["category"],
                "expected": question["expected_behavior"],
                "question": question["question"],
                "mode": args.mode,
                "model": provider.name,
                "tag": args.tag,
                "seconds": meta["seconds"],
                "prompt_tokens": meta["prompt_tokens"],
                "output_tokens": meta["output_tokens"],
                "thinking_tokens": meta.get("thinking_tokens"),
            }
            record.update(score_one(question, response, con, allowed))

            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

            mark = ("ok " if record["verdict"] in
                    {"match", "match_reordered", "decision_right"} else "   ")
            print(f"  {i:>2}/{len(todo)}  {qid}  {record['decision']:<8} "
                  f"{mark}{record['verdict']}")

            time.sleep(args.pause)
    finally:
        con.close()

    print(f"\nDone. Score the file with:  python -m eval.report --mode {args.mode}")


if __name__ == "__main__":
    main()
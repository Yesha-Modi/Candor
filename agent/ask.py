"""Ask the agent one question.

    python -m agent.ask "What is our revenue?"
    python -m agent.ask "What is our profit margin?" --show-prompt
"""

import argparse

import duckdb
import pandas as pd

from src.config import DB_PATH
from agent.prompt import build_prompt
from agent.provider import get_provider
from agent.schema import validate_shape

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", help="the business question, in quotes")
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--model", default=None)
    parser.add_argument("--show-prompt", action="store_true")
    parser.add_argument("--no-run", action="store_true",
                        help="generate the SQL but do not execute it")
    args = parser.parse_args()

    prompt = build_prompt(args.question)

    if args.show_prompt:
        print(prompt)
        print("=" * 70)

    kwargs = {"model": args.model} if args.model else {}
    provider = get_provider(args.provider, **kwargs)
    response, meta = provider.generate(prompt)

    print(f"\nQ: {args.question}")
    print(f"   [{meta['provider']}  {meta['seconds']}s  "
          f"{meta['prompt_tokens']} in / {meta['output_tokens']} out]\n")

    problems = validate_shape(response)
    if problems:
        print("SHAPE PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        print()

    print(f"DECISION: {response.decision.upper()}   (confidence: {response.confidence})")

    if response.decision == "clarify":
        print(f"\nAsks: {response.clarifying_question}")

    elif response.decision == "refuse":
        print(f"\nRefuses: {response.refusal_reason}")

    elif response.decision == "answer":
        if response.metrics_used:
            print(f"Metrics: {', '.join(response.metrics_used)}")
        print(f"\n{response.sql}\n")

        if args.no_run:
            print("(not executed)")
        else:
            con = duckdb.connect(str(DB_PATH), read_only=True)
            try:
                print(con.execute(response.sql).fetchdf().to_string(index=False))
            except Exception as e:
                print(f"SQL FAILED: {e}")
            finally:
                con.close()

    if response.assumptions:
        print("\nAssumptions:")
        for a in response.assumptions:
            print(f"  - {a}")

    print()


if __name__ == "__main__":
    main()
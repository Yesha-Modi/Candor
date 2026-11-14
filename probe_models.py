"""Probe which models actually answer right now.

list_models.py says which models exist. This says which ones are serving: it
sends the smallest possible real request to each candidate and reports what
came back.

Retries are deliberately OFF here and the timeout is short. provider.py wants
persistence; this wants a snapshot of the current moment.

    python probe_models.py
    python probe_models.py --all
"""

import argparse
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

API_VERSION = "v1beta"
PROBE_TIMEOUT_MS = 15_000
PROMPT = "Reply with the single word: ok"

CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-3.8-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="probe every generateContent model the key lists")
    args = parser.parse_args()

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set. Check your .env file.")
        return

    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(
            api_version=API_VERSION,
            timeout=PROBE_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    names = CANDIDATES
    if args.all:
        names = sorted(
            m.name.replace("models/", "")
            for m in client.models.list()
            if m.supported_actions and "generateContent" in m.supported_actions
        )

    print(f"probing {len(names)} models on {API_VERSION}, "
          f"{PROBE_TIMEOUT_MS // 1000}s each, no retries\n")

    working = []
    for name in names:
        started = time.perf_counter()

        try:
            client.models.generate_content(
                model=name,
                contents=PROMPT,
                config={
                    "max_output_tokens": 16,
                    "automatic_continuation": False,
                },
            )
        except Exception as e:
            code = getattr(e, "code", None) or type(e).__name__
            print(f"  {name:<26} {code}")
            continue

        print(f"  {name:<26} OK  {time.perf_counter() - started:.1f}s")
        working.append(name)

    print()
    if working:
        print("These are serving right now. Pick one:")
        for n in working:
            print(f'  python -m agent.ask "What is our revenue?" --model {n}')
    else:
        print("Nothing answered. All 503 means the free tier is saturated -- "
              "wait and rerun.\nAll 429 means you are rate limited -- wait a "
              "minute. All 404 means the API version is wrong.")


if __name__ == "__main__":
    main()
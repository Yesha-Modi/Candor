"""List the models this API key can reach, one API version at a time.

Run this when a call fails with a model-not-found error. It checks both API
versions, because the SDK and this script must agree on the version or their
answers disagree for reasons that have nothing to do with your key.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

HOST = "https://generativelanguage.googleapis.com"
VERSIONS = ("v1", "v1beta")
TIMEOUT_S = 15


def fetch(version: str, key: str) -> list[dict]:
    """Return the raw model entries for one API version."""
    query = urllib.parse.urlencode({"key": key, "pageSize": 200})
    url = f"{HOST}/{version}/models?{query}"
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
        return json.load(r).get("models", [])


def main() -> None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set. Check your .env file.")
        return

    print(f"key loaded ({len(key)} chars), {TIMEOUT_S}s timeout per version")

    for version in VERSIONS:
        print(f"\n=== {version} ===")

        try:
            models = fetch(version, key)
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} — {e.read().decode()[:300]}")
            continue
        except Exception as e:
            print(f"  {type(e).__name__}: {e}")
            print("  A timeout here means the network is blocking "
                  "generativelanguage.googleapis.com — try a phone hotspot.")
            continue

        rows = []
        for m in models:
            name = m["name"].replace("models/", "")
            if "flash" not in name and "pro" not in name:
                continue
            methods = m.get("supportedGenerationMethods") or []
            rows.append((name, "generateContent" in methods))

        usable = sum(1 for _, ok in rows if ok)
        print(f"  {len(models)} models total, "
              f"{usable} of the flash/pro ones support generateContent")

        for name, ok in sorted(rows):
            print(f"    {'OK ' if ok else '-- '}{name}")


if __name__ == "__main__":
    main()
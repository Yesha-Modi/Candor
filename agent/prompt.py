"""Turn the semantic layer into the context the model receives.

The layer is small enough — 14 metrics, 9 dimensions — to send whole. Retrieval
becomes worth building when it does not fit, which is somewhere north of a few
hundred definitions. Sending everything is simpler, deterministic, and removes a
failure mode: the agent can never fail because retrieval missed the one metric
it needed.
"""

import yaml

from src.config import PROJECT_ROOT

LAYER_PATH = PROJECT_ROOT / "semantic" / "semantic_layer.yaml"

SYSTEM_RULES = """\
You translate business questions into DuckDB SQL for an e-commerce dataset.

You have three choices, and choosing correctly matters more than answering.

ANSWER — the question is clear and the semantic layer can address it.
  Write one SELECT statement using only the tables, metrics and join paths below.

CLARIFY — the question has more than one defensible reading AND they produce
  different numbers. Ask which is wanted. Do not pick one and note the
  assumption; that is the failure this system exists to prevent.
  Metrics carrying an `ambiguity` note are the common cases.

REFUSE — the data cannot answer the question. Say which data is missing.
  The `not_available` section lists subjects with no data behind them. Never
  substitute a column that is merely adjacent — freight is not cost, reviews are
  not support tickets.

Rules for the SQL you write:
  - SELECT only. No INSERT, UPDATE, DELETE, CREATE, DROP or ATTACH.
  - Use only the tables and columns defined below.
  - Apply each metric's filters exactly as defined.
  - Respect every join warning.
  - Prefer joining dim_dates over computing dates inline.
  - Round money to 2 decimal places.

Report every choice the question did not specify in `assumptions`.
"""


def load_layer() -> dict:
    with open(LAYER_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _format_metric(m: dict) -> str:
    lines = [f"  {m['name']}  ({m['label']})"]
    lines.append(f"    sql:     {m['expression']} from {m['table']}")
    if m.get("filters"):
        lines.append(f"    filters: {' and '.join(m['filters'])}")
    if m.get("description"):
        lines.append(f"    means:   {' '.join(m['description'].split())}")
    if m.get("synonyms"):
        lines.append(f"    aka:     {', '.join(m['synonyms'])}")
    if m.get("ambiguity"):
        lines.append(f"    AMBIGUOUS: {' '.join(m['ambiguity'].split())}")
    return "\n".join(lines)


def _format_dimension(d: dict) -> str:
    lines = [f"  {d['name']}  ->  {d['table']}.{d['column']}"]
    if d.get("description"):
        lines.append(f"    means: {' '.join(d['description'].split())}")
    if d.get("synonyms"):
        lines.append(f"    aka:   {', '.join(d['synonyms'])}")
    return "\n".join(lines)


def _format_join(j: dict) -> str:
    on = j["condition"].replace("{from}", j["from"]).replace("{to}", j["to"])
    line = f"  {j['from']} -> {j['to']}  on {on}  ({j['cardinality']})"
    if j.get("warning"):
        line += f"\n    WARNING: {' '.join(j['warning'].split())}"
    if j.get("note"):
        line += f"\n    note:    {' '.join(j['note'].split())}"
    return line


def build_context(layer: dict) -> str:
    """Render the semantic layer as text for the prompt."""
    parts = []

    parts.append("TABLES")
    for t in layer["tables"]:
        line = f"  {t['name']}  —  {t['grain']}"
        if t.get("description"):
            line += f"\n    {' '.join(t['description'].split())}"
        parts.append(line)

    parts.append("\nMETRICS")
    parts.extend(_format_metric(m) for m in layer["metrics"])

    parts.append("\nDIMENSIONS")
    parts.extend(_format_dimension(d) for d in layer["dimensions"])

    parts.append("\nJOIN PATHS")
    parts.extend(_format_join(j) for j in layer["joins"])

    parts.append("\nNOT AVAILABLE — refuse questions about these")
    for n in layer["not_available"]:
        parts.append(
            f"  {n['topic']}\n    why: {' '.join(n['reason'].split())}"
            f"\n    aka: {', '.join(n.get('synonyms', []))}"
        )

    parts.append("\nDATASET CAVEATS — these apply to every question")
    for c in layer["caveats"]:
        parts.append(f"  {c['name']}: {' '.join(c['text'].split())}")

    return "\n".join(parts)


def build_prompt(question: str, layer: dict | None = None) -> str:
    layer = layer or load_layer()
    return (
        SYSTEM_RULES
        + "\n"
        + "=" * 70
        + "\nSEMANTIC LAYER\n"
        + "=" * 70
        + "\n"
        + build_context(layer)
        + "\n"
        + "=" * 70
        + f"\nQUESTION: {question}\n"
    )
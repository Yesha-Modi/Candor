"""Draw the README's charts from the results files.

    python -m eval.make_charts

Writes PNGs to docs/img/, a light and a dark version of each, which the
README shows with <picture> so each reader gets the one matching their
GitHub theme.

The charts are generated, never drawn by hand, for the same reason the gold
answers are computed: a chart someone typed numbers into is a claim, and a
chart produced from the committed results file is evidence. Re-run this after
any benchmark run and the README stays true.

Every input file is named in SOURCES below. "Which run produced this chart?"
should always have a one-line answer.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files; no window needed

import matplotlib.pyplot as plt  # noqa: E402

# Each platform's own interface font, falling back quietly: Segoe UI on
# Windows, then Inter, then the DejaVu Sans that matplotlib always ships.
plt.rcParams["font.family"] = ["sans-serif"]
plt.rcParams["font.sans-serif"] = ["Segoe UI", "Inter", "DejaVu Sans"]
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, PathPatch  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402

from agent.prompt import load_layer  # noqa: E402
from eval.report import is_correct, EXCLUDED_VERDICTS  # noqa: E402
from eval.run_gold import load_questions  # noqa: E402
from eval.taxonomy import classify, dedupe  # noqa: E402
from src.config import PROJECT_ROOT  # noqa: E402

RESULTS = PROJECT_ROOT / "results"
OUT = PROJECT_ROOT / "docs" / "img"

# One line per chart: which committed file feeds it.
SOURCES = {
    # The headline comparison: same day, same prompt version, same gold file.
    "schema": RESULTS / "schema_gemini_gemini-3.1-flash-lite.jsonl",
    "semantic": RESULTS / "archive" / "semantic_gemini_gemini-3.1-flash-lite_prefix.jsonl",
    # The noise floor: the same model and prompt, run twice.
    "run1": RESULTS / "semantic_gemini_gemini-3.1-flash-lite.jsonl",
    "run2": RESULTS / "semantic_gemini_gemini-3.1-flash-lite_run2.jsonl",
    # The failure taxonomy: the agent as it currently stands.
    "taxonomy": RESULTS / "semantic_gemini_gemini-3.1-flash-lite.jsonl",
}

# ---------------------------------------------------------------- the look
# Colours come from a palette validated for colour-blind separation and
# contrast in both themes. Schema-only is always blue and the semantic agent
# is always orange, in every chart: a colour that changes meaning halfway down
# a page is worse than no colour at all.
THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e",
        "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
        "schema": "#2a78d6", "semantic": "#eb6834",
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7",
        "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
        "schema": "#3987e5", "semantic": "#d95926",
    },
}

# The figure is 8 inches wide and shown at about 800 pixels, so one "CSS
# pixel" is 1/100 inch. Rendering at 200 dpi makes every image 2x for sharp
# text on high-density screens.
DPI = 200
CSS_PX = 1 / 100            # inches
BAR_PX = 18                 # bar thickness, capped well under 24
RADIUS_PX = 4               # rounded data-end
GAP_PX = 2                  # surface gap between touching bars

CATEGORY_ORDER = ["simple_aggregate", "multi_table_join", "time_series",
                  "ambiguous", "unanswerable"]
CATEGORY_LABEL = {
    "simple_aggregate": "Simple aggregates",
    "multi_table_join": "Multi-table joins",
    "time_series": "Time series",
    "ambiguous": "Ambiguous (should clarify)",
    "unanswerable": "Unanswerable (should refuse)",
}


# ---------------------------------------------------------------- data
def load(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing results file: {path}\n"
                         f"Check SOURCES at the top of eval/make_charts.py.")
    with open(path, encoding="utf-8") as f:
        return dedupe([json.loads(line) for line in f if line.strip()])


def by_category(records: list[dict]) -> dict[str, tuple[int, int]]:
    """category -> (correct, scored), using report.py's definition of correct.

    Importing is_correct rather than re-implementing it is deliberate: a chart
    that counted differently from the report would put two different numbers
    for the same run in the same README.
    """
    counts = defaultdict(lambda: [0, 0])
    for r in records:
        if r.get("verdict") in EXCLUDED_VERDICTS:
            continue
        counts[r["category"]][1] += 1
        if is_correct(r):
            counts[r["category"]][0] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


# ---------------------------------------------------------------- drawing
def _style(ax, t):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.tick_params(colors=t["muted"], labelsize=9, length=0)
    ax.xaxis.grid(True, color=t["grid"], linewidth=0.6)
    ax.set_axisbelow(True)


def _hbar(ax, y, x0, x1, height, color):
    """A horizontal bar, square at the baseline, rounded at the data end.

    matplotlib has no such bar, and the corner radius must be fixed in pixels
    rather than data units, or it would stretch with the axis scale. So the
    radius is converted to data units on each axis separately.
    """
    if x1 <= x0:
        return
    fig = ax.figure
    to_px = ax.transData.transform
    (px0, py0), (px1, py1) = to_px((0, 0)), to_px((1, 1))
    per_x = abs(px1 - px0)                       # display px per data unit
    per_y = abs(py1 - py0)
    r_disp = RADIUS_PX * CSS_PX * fig.dpi
    rx = min(r_disp / per_x, (x1 - x0))
    ry = min(r_disp / per_y, height / 2)
    k = 0.5523                                   # quarter-circle Bezier
    b, top = y - height / 2, y + height / 2
    verts = [
        (x0, b), (x1 - rx, b),
        (x1 - rx + k * rx, b), (x1, b + ry - k * ry), (x1, b + ry),
        (x1, top - ry),
        (x1, top - ry + k * ry), (x1 - rx + k * rx, top), (x1 - rx, top),
        (x0, top), (x0, b),
    ]
    codes = [MplPath.MOVETO, MplPath.LINETO,
             MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
             MplPath.LINETO,
             MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
             MplPath.LINETO, MplPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=color,
                           edgecolor="none", linewidth=0))


def _units_per_px(ax) -> float:
    """Data units on the y axis that one CSS pixel spans."""
    (_, y0), (_, y1) = ax.transData.transform((0, 0)), ax.transData.transform((0, 1))
    return (CSS_PX * ax.figure.dpi) / abs(y1 - y0)


def _side_label(ax, y, text, t, strong):
    """A value in a column just right of the plot, never on top of a mark.

    Placed in axes coordinates rather than at a data x position: a label at
    x=101 sits on any dot that reaches 100, which is exactly the row a reader
    most wants to read.
    """
    ax.text(1.045, y, text, transform=ax.get_yaxis_transform(),
            va="center", ha="center", fontsize=9.5, fontweight="bold",
            color=t["ink"] if strong else t["muted"], clip_on=False)


def _column_head(fig, ax, text, t):
    """A small heading centred over the side-label column."""
    ax.text(1.045, 1.02, text, transform=ax.transAxes, ha="center",
            va="bottom", fontsize=8, color=t["muted"], linespacing=1.1,
            clip_on=False)


def _title(fig, t, title, subtitle):
    fig.text(0.02, 0.965, title, ha="left", va="top", fontsize=11.5,
             fontweight="bold", color=t["ink"])
    fig.text(0.02, 0.905, subtitle, ha="left", va="top", fontsize=9,
             color=t["ink2"])


def _save(fig, name, mode):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{mode}.png"
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


# ---------------------------------------------------------------- chart 1
def chart_benchmark(mode: str) -> Path:
    t = THEMES[mode]
    schema = by_category(load(SOURCES["schema"]))
    semantic = by_category(load(SOURCES["semantic"]))

    def pct(d, c):
        n, total = d.get(c, (0, 0))
        return 100 * n / total if total else 0

    # Ordered by the size of the gap: the chart is about where the semantic
    # layer helps, so the largest effect reads first.
    cats = [c for c in CATEGORY_ORDER if c in schema or c in semantic]
    cats.sort(key=lambda c: (-(pct(semantic, c) - pct(schema, c)), c))

    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=DPI)
    fig.patch.set_facecolor(t["surface"])
    fig.subplots_adjust(left=0.30, right=0.90, top=0.78, bottom=0.12)
    _style(ax, t)
    ax.set_xlim(0, 100)
    ax.set_ylim(len(cats) - 0.5, -0.5)          # first category at the top
    fig.canvas.draw()

    u = _units_per_px(ax)
    h = BAR_PX * u
    gap = GAP_PX * u
    for i, c in enumerate(cats):
        _hbar(ax, i - (h + gap) / 2, 0, pct(schema, c), h, t["schema"])
        _hbar(ax, i + (h + gap) / 2, 0, pct(semantic, c), h, t["semantic"])
        delta = round((semantic[c][0] if c in semantic else 0)
                      - (schema[c][0] if c in schema else 0))
        # The one label the story needs: how many more questions the semantic
        # layer got right in this category. The axis carries the rest.
        sign = "+" if delta > 0 else ("±" if delta == 0 else "−")
        _side_label(ax, i, f"{sign}{abs(delta)}", t, strong=bool(delta))

    ax.set_yticks(range(len(cats)))
    ax.set_yticklabels([CATEGORY_LABEL.get(c, c) for c in cats],
                       color=t["ink2"], fontsize=9.5)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])

    s_n = sum(v[0] for v in schema.values())
    m_n = sum(v[0] for v in semantic.values())
    total = sum(v[1] for v in semantic.values())
    _title(fig, t, "Where the semantic layer helps",
           f"Share of questions answered correctly, by category · "
           f"schema-only {s_n}/{total}, semantic layer {m_n}/{total}")
    _column_head(fig, ax, "questions\ngained", t)

    handles = [Patch(facecolor=t["schema"], label="Schema only"),
               Patch(facecolor=t["semantic"], label="With semantic layer")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.30, 0.86),
               ncol=2, frameon=False, fontsize=9, labelcolor=t["ink2"],
               handlelength=1.0, handleheight=0.8, columnspacing=1.6)
    return _save(fig, "benchmark-by-category", mode)


# ---------------------------------------------------------------- chart 2
def chart_noise(mode: str) -> Path:
    t = THEMES[mode]
    r1 = by_category(load(SOURCES["run1"]))
    r2 = by_category(load(SOURCES["run2"]))
    cats = [c for c in CATEGORY_ORDER if c in r1 and c in r2]

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=DPI)
    fig.patch.set_facecolor(t["surface"])
    fig.subplots_adjust(left=0.30, right=0.90, top=0.78, bottom=0.13)
    _style(ax, t)
    ax.set_xlim(0, 100)
    ax.set_ylim(len(cats) - 0.5, -0.5)
    fig.canvas.draw()

    # One entity sampled twice, so one colour: the line is the range the same
    # model covered on identical questions, and its length is the noise.
    for i, c in enumerate(cats):
        a = 100 * r1[c][0] / r1[c][1]
        b = 100 * r2[c][0] / r2[c][1]
        lo, hi = min(a, b), max(a, b)
        # clip_on=False: a dot at exactly 100% must not be cut in half by the
        # edge of the plot.
        ax.plot([lo, hi], [i, i], color=t["semantic"], linewidth=2,
                solid_capstyle="round", zorder=2, clip_on=False)
        ax.scatter([a, b], [i, i], s=46, color=t["semantic"],
                   edgecolors=t["surface"], linewidths=2, zorder=3,
                   clip_on=False)
        swing = abs(r1[c][0] - r2[c][0])
        _side_label(ax, i, str(swing), t, strong=bool(swing))

    ax.set_yticks(range(len(cats)))
    ax.set_yticklabels([CATEGORY_LABEL.get(c, c) for c in cats],
                       color=t["ink2"], fontsize=9.5)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])

    n1 = sum(v[0] for v in r1.values())
    n2 = sum(v[0] for v in r2.values())
    total = sum(v[1] for v in r1.values())
    _title(fig, t, "The noise floor: one model, run twice",
           f"Same model, prompt and questions · {n1}/{total} then "
           f"{n2}/{total} · the line is how far identical runs moved")
    _column_head(fig, ax, "questions\napart", t)
    return _save(fig, "noise-floor", mode)


# ---------------------------------------------------------------- chart 3
# Which kind of mistake each tag is. Grouped by position and a heading rather
# than a third set of colours, so orange keeps meaning "the semantic agent".
GROUPS = [
    ("Touched the wrong data", ["fan_out", "fan_out_count", "missing_filter",
                                "invented_column", "column_substitution",
                                "meaningless_grouping", "missing_window_function",
                                "wrong_row_set"]),
    ("Right data, wrong form", ["over_answering", "under_answering",
                                "units_mismatch", "metric_used_as_column"]),
    ("Wrong decision", ["wrong_decision_clarify_got_answer",
                        "wrong_decision_clarify_got_refuse",
                        "wrong_decision_answer_got_clarify",
                        "wrong_decision_answer_got_refuse",
                        "wrong_decision_refuse_got_answer"]),
    ("Not yet explained", ["unexplained_value_difference"]),
]
TAG_LABEL = {
    "fan_out": "Fan-out (join multiplied rows)",
    "fan_out_count": "Fan-out in a count",
    "missing_filter": "Dropped a required filter",
    "invented_column": "Invented a column",
    "column_substitution": "Swapped in a near-miss column",
    "meaningless_grouping": "Grouped by an ambiguous period",
    "missing_window_function": "Missed a running total",
    "wrong_row_set": "Wrong set of rows",
    "over_answering": "Returned extra columns",
    "under_answering": "Returned too few columns",
    "units_mismatch": "Wrong units (×100)",
    "metric_used_as_column": "Used a metric name as a column",
    "wrong_decision_clarify_got_answer": "Answered instead of clarifying",
    "wrong_decision_clarify_got_refuse": "Refused instead of clarifying",
    "wrong_decision_answer_got_clarify": "Clarified a clear question",
    "wrong_decision_answer_got_refuse": "Refused an answerable question",
    "wrong_decision_refuse_got_answer": "Answered the unanswerable",
    "unexplained_value_difference": "Unexplained difference",
}


def chart_taxonomy(mode: str) -> Path:
    t = THEMES[mode]
    gold = {q["id"]: q for q in load_questions()}
    metrics = {m["name"].lower() for m in load_layer()["metrics"]}
    records = load(SOURCES["taxonomy"])
    tags = Counter(
        tag for tag in (classify(r, gold.get(r["id"]), metrics) for r in records)
        if tag not in {"correct", "not_scored"}
    )

    rows = []                     # (label, count, is_group_heading, is_residual)
    for heading, members in GROUPS:
        present = sorted(((tags[m], m) for m in members if tags.get(m)),
                         key=lambda x: (-x[0], x[1]))
        if not present:
            continue
        rows.append((heading, sum(n for n, _ in present), True, False))
        for n, m in present:
            rows.append((TAG_LABEL.get(m, m), n, False,
                         m == "unexplained_value_difference"))
    known = {m for _, ms in GROUPS for m in ms}
    for m, n in tags.items():
        if m not in known:          # a tag the chart has no group for yet
            rows.append((m, n, False, True))

    if not rows:
        # A clean run is a real outcome, not an error: say so rather than
        # drawing an empty axis or crashing on a zero-height chart.
        fig = plt.figure(figsize=(8, 1.6), dpi=DPI)
        fig.patch.set_facecolor(t["surface"])
        _title(fig, t, "How the agent fails", "No failures in this run.")
        return _save(fig, "failure-taxonomy", mode)

    fig, ax = plt.subplots(figsize=(8, 0.62 + 0.30 * len(rows) + 0.9), dpi=DPI)
    fig.patch.set_facecolor(t["surface"])
    top_in = 0.95
    fig.subplots_adjust(left=0.40, right=0.95,
                        top=1 - top_in / fig.get_figheight(),
                        bottom=0.42 / fig.get_figheight())
    _style(ax, t)
    biggest = max((n for _, n, head, _ in rows if not head), default=1)
    ax.set_xlim(0, biggest + 0.4)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    fig.canvas.draw()

    u = _units_per_px(ax)
    for i, (label, n, head, residual) in enumerate(rows):
        if head:
            continue
        _hbar(ax, i, 0, n, BAR_PX * u,
              t["muted"] if residual else t["semantic"])

    ax.set_yticks(range(len(rows)))
    labels = ax.set_yticklabels([label for label, *_ in rows], fontsize=9.5)
    for tick, (_, n, head, _) in zip(labels, rows):
        tick.set_color(t["ink"] if head else t["ink2"])
        tick.set_fontweight("bold" if head else "normal")
    ax.set_xticks(range(0, biggest + 1))
    ax.xaxis.set_tick_params(labelsize=9)

    failures = sum(tags.values())
    unexplained = tags.get("unexplained_value_difference", 0)
    _title(fig, t, "How the agent fails",
           f"Every failure in one run, named from its SQL · {failures} failures, "
           f"{unexplained} unexplained")
    return _save(fig, "failure-taxonomy", mode)


def main() -> None:
    for mode in ("light", "dark"):
        for draw in (chart_benchmark, chart_noise, chart_taxonomy):
            print(f"  wrote {draw(mode).relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
"""
Figure: pipeline output versus human review, for one run.

Reads data/artifacts/runs/<run_id>/eval/correction.json (written by `k1 eval`)
and writes a PNG. matplotlib is not a project dependency, so run it with:

    uv run --with matplotlib python scripts/review_figure.py --run scope02
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent.parent

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e6e5e1"
BLUE = "#2a78d6"    # the pipeline, and steps corrected from its output
ORANGE = "#eb6834"  # steps annotated from scratch

FIELD_LABELS = {
    "node_type": "Node type",
    "pre_conditions": "State before the step",
    "post_conditions": "State after the step",
    "tools": "Utensils",
    "has_safety_bound": "Heat flag",
    "action_phrase": "Action wording",
}


def _style(ax, title: str, subtitle: str) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", length=0, colors=INK_2, labelsize=9.5)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=28)
    # Offset in points, so the gap is the same whatever the height of the panel.
    ax.annotate(subtitle, xy=(0, 1), xycoords="axes fraction", xytext=(0, 9),
                textcoords="offset points", fontsize=9.5, color=INK_2, va="bottom")


def _hbars(ax, labels, values, color, fmt, xmax) -> None:
    y = range(len(labels))
    ax.barh(list(y), values, height=0.56, color=color)
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, xmax)
    for i, v in zip(y, values):
        ax.text(v + xmax * 0.015, i, fmt(v), va="center", fontsize=9.5, color=INK)


def build(run_id: str, out_path: Path) -> Path:
    m = json.loads((ROOT / "data" / "artifacts" / "runs" / run_id / "eval" / "correction.json").read_text())
    acc, eff, tm, cov = m["accuracy_all"], m["effort"], m["time"], m["coverage"]

    fig = plt.figure(figsize=(12, 8.2), facecolor=SURFACE)
    fig.text(0.045, 0.955, "Building K1 with an LLM pipeline, then correcting it by hand",
             fontsize=16, fontweight="bold", color=INK)
    fig.text(0.045, 0.925,
             f"Run {run_id} · {cov['recipes_in_queue']} scrambled-egg recipes · "
             f"{cov['steps_reviewed']} recipe steps, all reviewed by the author",
             fontsize=10.5, color=INK_2)

    # Headline figures
    tiles = [
        (f"{acc['scope_agreement_pct']:.0f}%", "of keep-or-drop decisions\nmatched the reviewer"),
        (f"{acc['unchanged_ignoring_wording_pct']:.0f}%", "of steps needed no change\n(ignoring wording)"),
        (f"{eff['edits_per_step']:.1f}", f"edits per step\n({eff['total_edits']} in total)"),
        (f"{tm['saving']['pct_saved_per_step']:.0f}%", "less time per step than\nannotating from scratch"),
    ]
    for i, (big, small) in enumerate(tiles):
        x = 0.045 + i * 0.235
        fig.text(x, 0.835, big, fontsize=26, fontweight="bold", color=INK)
        fig.text(x, 0.79, small, fontsize=9.5, color=INK_2, linespacing=1.35)

    gs = fig.add_gridspec(2, 2, left=0.19, right=0.965, top=0.675, bottom=0.07,
                          wspace=0.62, hspace=0.72, width_ratios=[1.15, 1])

    # A. Accuracy by field
    ax = fig.add_subplot(gs[:, 0])
    fields = sorted(acc["field_accuracy_pct"].items(), key=lambda kv: -kv[1])
    labels = ["Keep or drop the step"] + [FIELD_LABELS[k] for k, _ in fields]
    values = [acc["scope_agreement_pct"]] + [v for _, v in fields]
    _style(ax, "How often the pipeline was right",
           f"% of steps matching the reviewer (n = {acc['steps_kept_by_both']}; keep or drop n = {acc['steps']})")
    _hbars(ax, labels, values, BLUE, lambda v: f"{v:.0f}%", 112)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"])

    # B. Time per step
    ax = fig.add_subplot(gs[0, 1])
    c, s = tm["corrected"], tm["from_scratch"]
    _style(ax, "Time per step", "Mean seconds of active work per step")
    names = [f"Corrected from\npipeline output (n = {c['steps_timed']})",
             f"Annotated from\nscratch (n = {s['steps_timed']})"]
    vals = [c["mean_seconds_per_step"], s["mean_seconds_per_step"]]
    xmax = max(vals) * 1.5
    ax.barh([0, 1], vals, height=0.5, color=[BLUE, ORANGE])
    ax.set_yticks([0, 1], names)
    ax.invert_yaxis()
    ax.set_xlim(0, xmax)
    for i, (v, med) in enumerate(zip(vals, [c["median_seconds_per_step"], s["median_seconds_per_step"]])):
        ax.text(v + xmax * 0.02, i - 0.09, f"{v:.0f} s", va="center", fontsize=10.5, fontweight="bold", color=INK)
        ax.text(v + xmax * 0.02, i + 0.13, f"median {med:.0f} s", va="center", fontsize=8.5, color=INK_2)

    # C. Edits by field
    ax = fig.add_subplot(gs[1, 1])
    edits = {FIELD_LABELS[k]: v for k, v in eff["edits_by_field"].items()}
    edits["Keep or drop the step"] = eff["scope_fixes"]
    ordered = sorted(edits.items(), key=lambda kv: -kv[1])
    _style(ax, "What the reviewer had to change",
           f"Number of edits by field ({eff['total_edits']} edits over {cov['steps_reviewed']} steps)")
    _hbars(ax, [k for k, _ in ordered], [v for _, v in ordered], BLUE,
           lambda v: f"{v:.0f}", max(v for _, v in ordered) * 1.16)

    fig.text(0.045, 0.02,
             "One annotator. Edit counts include rule-based fixes applied after the timed review; times do not. "
             "Time includes a second pass fixing inconsistencies.",
             fontsize=8, color=MUTED)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    out = Path(args.out) if args.out else ROOT.parent / "Notes" / "figures" / f"k1-review-{args.run}.png"
    print(build(args.run, out))

"""Render the two figures used in README.md / BENCHMARKS.md.

Inputs are the raw measurement files in bench/results/, so the figures can be
regenerated from the data and never drift from the tables.

    python bench/make_figures.py

Output:
    docs/assets/speedup.png     upstream vs. this build, per benchmark case
    docs/assets/ablation.png    which of the two changes is responsible
"""

from __future__ import annotations

import json
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "assets")

INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"
GRID = "#ddd3c4"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": INK,
    "figure.facecolor": PAPER,
    "axes.facecolor": PAPER,
    "savefig.facecolor": PAPER,
})

CASE_LABELS = {
    "queens-8-all": "8-queens, all solutions",
    "queens-10-all": "10-queens, all solutions",
    "queens-11-all": "11-queens, all solutions",
    "queens-16-first": "16-queens, first solution",
    "queens-20-first": "20-queens, first solution",
    "sudoku-hard-all": "sudoku (hard), all solutions",
    "dedispersion-all": "dedispersion space (11 130 sol.)",
    "microhh-small-all": "microhh space (11 340 sol.)",
    "hotspot-all": "hotspot space (349 853 sol.)",
}

# cases where the win comes from visiting fewer nodes, vs. only from cheaper nodes
TREE_REDUCTION = {"queens-16-first", "queens-20-first", "sudoku-hard-all"}


def load(name: str):
    """Load one raw measurement file from bench/results/."""
    with open(os.path.join(HERE, "results", name), encoding="utf-8") as fh:
        return json.load(fh)


def figure_speedup():
    """Render docs/assets/speedup.png from ab_default.json."""
    data = load("ab_default.json")["cases"]
    order = [
        "queens-20-first",
        "queens-16-first",
        "sudoku-hard-all",
        "microhh-small-all",
        "queens-10-all",
        "dedispersion-all",
        "queens-8-all",
        "hotspot-all",
    ]
    values = [data[c]["ratio_median"] for c in order]
    labels = [CASE_LABELS[c] for c in order]
    colors = [TERRACOTTA if c in TREE_REDUCTION else AMBER for c in order]

    fig, ax = plt.subplots(figsize=(9.6, 5.0), dpi=200)
    y = list(range(len(order)))
    bars = ax.barh(y, values, color=colors, height=0.62, zorder=3)

    ax.set_xscale("log")
    ax.set_xlim(0.9, 2000)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("speed-up over upstream 2.7.3  (times faster, log scale)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax.axvline(1.0, color=MUTED, linestyle=(0, (4, 3)), linewidth=1.1, zorder=4)
    ax.annotate("no change", xy=(1.0, -0.62), xytext=(1.06, -0.62), color=MUTED,
                fontsize=8.5, va="center", ha="left", annotation_clip=False)

    for bar, value, case in zip(bars, values, order):
        text = f"{value:,.0f}x" if value >= 10 else f"{value:.2f}x"
        ax.text(bar.get_width() * 1.09, bar.get_y() + bar.get_height() / 2,
                text, va="center", ha="left", fontsize=9.5, color=INK, fontweight="bold")

    ax.set_title("Fewer search nodes where forward checking prunes,\n"
                 "cheaper nodes everywhere else",
                 loc="left", fontsize=12.5, color=INK, pad=14, fontweight="bold")

    legend = [
        Patch(facecolor=TERRACOTTA, label="win comes from a smaller search tree"),
        Patch(facecolor=AMBER, label="win comes from cheaper nodes only"),
    ]
    ax.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=2, frameon=False, fontsize=9)

    fig.text(0.012, 0.012,
             "Median of 7 interleaved rounds, one process per sample, both arms at identical repeat counts. "
             "Raw data: bench/results/ab_default.json",
             fontsize=7.6, color=MUTED)
    fig.tight_layout(rect=(0.012, 0.045, 1, 0.97))
    path = os.path.join(OUT, "speedup.png")
    fig.savefig(path)
    plt.close(fig)
    print("wrote", path)


def figure_ablation():
    """Diverging log2 axis.

    A plain log axis cannot show a value below 1.0 (the bar would have zero
    length, i.e. it would look like "no change"), and the ablation contains
    exactly such values.  Plotting log2(speed-up) around a zero baseline keeps
    both directions visible and still compresses the 700x outlier.
    """
    data = load("ablation.json")["cases"]
    arms = [
        ("legacy", "both off (upstream behaviour)", MUTED),
        ("mrv", "dynamic MRV only", TERRACOTTA),
        ("scope", "restricted push only", OLIVE),
        ("both", "both (new default)", AMBER),
    ]
    order = ["sudoku-hard-all", "queens-20-first", "queens-11-all",
             "hotspot-all", "microhh-small-all", "dedispersion-all"]

    fig, ax = plt.subplots(figsize=(10.6, 5.6), dpi=200)
    group_gap = 0.86
    bar_h = group_gap / len(arms)
    yticks, ylabels = [], []
    xmax = 0.0

    for gi, case in enumerate(order):
        base = gi * group_gap
        yticks.append(base + (len(arms) - 1) * bar_h / 2)
        ylabels.append(CASE_LABELS[case])
        values = [data[case]["arms"][arm]["speedup_median"] for arm, _l, _c in arms]
        for ai, ((arm, _label, color), value) in enumerate(zip(arms, values)):
            y = base + ai * bar_h
            fold = math.log2(value)
            xmax = max(xmax, fold)
            # legacy is exactly 1.0 -> zero length, drawn as a tick instead of a bar
            if arm == "legacy":
                ax.plot([0], [y + bar_h * 0.43], marker="|", color=MUTED, markersize=7, zorder=4)
                continue
            ax.barh(y, fold, height=bar_h * 0.84, color=color, zorder=3,
                    edgecolor=TERRACOTTA if fold < 0 else "none", linewidth=0.8)
            text = f"{value:,.0f}x" if value >= 10 else f"{value:.2f}x"
            if fold >= 0:
                ax.text(fold + 0.14, y + bar_h * 0.43, text, va="center", ha="left",
                        fontsize=7.4, color=INK)
            else:
                # a sub-1.0 bar is only ~0.25 wide on this axis, far too narrow for
                # a label: place it to the left of the bar on an opaque backing so
                # it stays readable across the zero baseline
                ax.text(fold - 0.10, y + bar_h * 0.43, text, va="center", ha="right",
                        fontsize=7.2, color=TERRACOTTA, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.15", facecolor=PAPER,
                                  edgecolor="none", alpha=0.92))

    ticks = [0, 1, 2, 3, 4, 5, 6, 8, 10]
    tick_labels = ["1x", "2x", "4x", "8x", "16x", "32x", "64x", "256x", "1024x"]
    ax.set_xticks(ticks)
    ax.set_xticklabels(tick_labels, fontsize=8.6)
    ax.set_xlim(-1.45, 11.4)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=9.5)
    ax.set_ylim(-0.46, len(order) * group_gap - 0.10)
    ax.invert_yaxis()
    ax.set_xlabel("speed-up relative to the same build with both switches off  (linear in log2)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax.axvline(0, color=INK, linewidth=1.2, zorder=4)
    ax.annotate("slower", xy=(-1.35, -0.20), color=TERRACOTTA,
                fontsize=7.6, ha="left", va="center", annotation_clip=False)
    ax.annotate("faster", xy=(0.14, -0.20), color=INK,
                fontsize=7.6, ha="left", va="center", annotation_clip=False)

    ax.set_title("Dynamic MRV buys the orders of magnitude, and loses on pure enumeration;\n"
                 "the restricted push list is what pays there",
                 loc="left", fontsize=11.8, color=INK, pad=22, fontweight="bold")

    handles = [Patch(facecolor=color, label=label) for _a, label, color in arms]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.115),
              ncol=4, frameon=False, fontsize=8.2, handlelength=1.4, columnspacing=1.6)

    fig.text(0.012, 0.013,
             "All four arms are the same patched package; only the two constructor switches differ. "
             "Median of 5 rounds, one process per sample. Raw data: bench/results/ablation.json",
             fontsize=7.4, color=MUTED)
    # explicit margins: the y labels are long and tight_layout's rect would clip them
    fig.subplots_adjust(left=0.315, right=0.985, top=0.85, bottom=0.215)
    path = os.path.join(OUT, "ablation.png")
    fig.savefig(path)
    plt.close(fig)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    figure_speedup()
    figure_ablation()

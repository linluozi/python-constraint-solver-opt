"""Turn the benchmark JSON files into the markdown tables used in BENCHMARKS.md.

Usage:
    python make_report.py --base final_upstream.json --opt final_python-constraint-opt.json \
                          --ablation ablation_final.json --out tables.md
"""

import argparse
import json


def load(path):
    """Load a benchmark JSON file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fmt(x):
    """Format a number for a markdown table."""
    if x >= 100:
        return f"{x:,.0f}"
    if x >= 10:
        return f"{x:.1f}"
    return f"{x:.3f}"


def main():
    """Write the markdown tables to stdout and optionally to --out."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--opt", required=True)
    parser.add_argument("--ablation", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    base = load(args.base)["cases"]
    opt = load(args.opt)["cases"]
    ablation = load(args.ablation)["cases"] if args.ablation else {}

    lines = []
    lines.append("### Upstream vs. optimized (`OptimizedBacktrackingSolver`, default settings)\n")
    lines.append(
        "| case | solutions | constraint calls (upstream) | constraint calls (optimized) | calls ratio "
        "| best of 5 (upstream) | best of 5 (optimized) | speed-up |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")

    for case in base:
        b = base[case]["OptimizedBacktrackingSolver"]
        o = opt[case]["OptimizedBacktrackingSolver"]
        calls_ratio = b["constraint_calls"] / o["constraint_calls"] if o["constraint_calls"] else float("nan")
        speed = b["best_s"] / o["best_s"] if o["best_s"] else float("nan")
        lines.append(
            f"| `{case}` | {b['solutions']:,} | {b['constraint_calls']:,} | {o['constraint_calls']:,} "
            f"| {calls_ratio:.2f}x | {b['best_s']:.3f} s | {o['best_s']:.3f} s | {speed:.2f}x |"
        )

    if ablation:
        lines.append("\n### Ablation: which optimization is responsible\n")
        arms = ["OptimizedLegacy", "OptimizedMRVOnly", "OptimizedScopeOnly", "OptimizedBacktrackingSolver"]
        present = [a for a in arms if a in next(iter(ablation.values()))]
        header = "| case | " + " | ".join(f"{a} (s)" for a in present) + " |"
        lines.append(header)
        lines.append("|---|" + "---:|" * len(present))
        for case in ablation:
            row = [f"| `{case}` "]
            for arm in present:
                row.append(f"| {ablation[case][arm]['best_s']:.3f} ")
            lines.append("".join(row) + "|")

        lines.append("\n### Ablation: constraint invocations\n")
        lines.append(header.replace("(s)", "(calls)"))
        lines.append("|---|" + "---:|" * len(present))
        for case in ablation:
            row = [f"| `{case}` "]
            for arm in present:
                row.append(f"| {ablation[case][arm]['constraint_calls']:,} ")
            lines.append("".join(row) + "|")

    text = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

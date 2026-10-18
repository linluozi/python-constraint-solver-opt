"""Ablation: which of the two optimizations is responsible for the speed-up.

All arms run the *same* patched package, only the two switches differ, so the
comparison isolates the change instead of comparing two different code bases.

Arms (all `OptimizedBacktrackingSolver`):
    legacy   dynamic_mrv=False, restricted_pushdomains=False   (== upstream behaviour)
    mrv      dynamic_mrv=True,  restricted_pushdomains=False
    scope    dynamic_mrv=False, restricted_pushdomains=True
    both     dynamic_mrv=True,  restricted_pushdomains=True    (the new default)

One process per sample, arms rotated every round, median of per-round ratios
against `legacy`, plus the number of rounds each arm won.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ARMS = {
    "legacy": (False, False),
    "mrv": (True, False),
    "scope": (False, True),
    "both": (True, True),
}


def run_arm(pkg: str, case: str, arm: str, repeats: int) -> dict:
    """Time one case with one arm configuration in a child process."""
    dynamic_mrv, restricted = ARMS[arm]
    cmd = [
        sys.executable,
        os.path.join(HERE, "ablation_worker.py"),
        "--pkg",
        pkg,
        "--case",
        case,
        "--dynamic-mrv",
        str(int(dynamic_mrv)),
        "--restricted",
        str(int(restricted)),
        "--repeats",
        str(repeats),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{arm}/{case} failed:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def calibrate(pkg: str, case: str) -> tuple[int, int]:
    """Return (repeats, solutions) from a baseline calibration run."""
    payload = run_arm(pkg, case, "legacy", repeats=0)
    return payload["repeats"], payload["solutions"]


def main():
    """Run the ablation for every requested case and print the table."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pkg", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--cases", default="queens-11-all,sudoku-hard-all,dedispersion-all,"
                                            "microhh-small-all,hotspot-all,queens-20-first")
    parser.add_argument("--out")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    results = {"pkg": os.path.abspath(args.pkg), "cases": {}}

    for case in args.cases.split(","):
        repeats, solutions = calibrate(args.pkg, case)
        order = list(ARMS)
        samples = {arm: [] for arm in order}

        for round_index in range(args.rounds):
            rotated = order[round_index % len(order):] + order[: round_index % len(order)]
            for arm in rotated:
                payload = run_arm(args.pkg, case, arm, repeats)
                if payload["solutions"] != solutions:
                    raise RuntimeError(f"{arm}/{case}: solution count changed")
                samples[arm].append(payload["seconds"])

        entry = {"repeats": repeats, "solutions": solutions, "arms": {}}
        base = samples["legacy"]
        for arm in order:
            # speed-up = legacy time / arm time  ->  > 1 means the arm is faster
            ratios = [a / b for a, b in zip(base, samples[arm])]
            entry["arms"][arm] = {
                "median_ms": round(statistics.median(samples[arm]) / repeats * 1000, 3),
                "speedup_median": round(statistics.median(ratios), 3),
                "speedup_min": round(min(ratios), 3),
                "speedup_max": round(max(ratios), 3),
                "won_rounds": sum(1 for r in ratios if r > 1),
            }
        results["cases"][case] = entry

        cells = "  ".join(
            f"{arm}={entry['arms'][arm]['median_ms']:.2f}ms" for arm in order
        )
        speed = "  ".join(f"{arm}={entry['arms'][arm]['speedup_median']:.2f}x" for arm in order)
        print(f"{case:20s} n={repeats:<3d} {cells}", flush=True)
        print(f"{'':20s}        speed-up vs legacy: {speed}", flush=True)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=2, ensure_ascii=False)
        print("written", args.out)


if __name__ == "__main__":
    main()

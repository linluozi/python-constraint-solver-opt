"""Interleaved A/B benchmark between two checkouts of the `constraint` package.

Why this script exists
----------------------
Small CSP cases finish in a few milliseconds, which is far below the noise of a
shared desktop machine (two runs of byte-identical code were measured 2-3x
apart).  Measuring A, then B, and dividing the totals therefore says nothing.
This script does what actually holds up:

  * every case runs in its own process, so no case can pollute the next one's
    profile;
  * the two packages alternate every round (A, B, A, B, ...) and the *order* is
    rotated too, so a slow period of the machine hits both arms;
  * inside the timed window the case is repeated until the window lasts at least
    ``--min-seconds``, which lifts the signal well above the timer granularity;
  * the reported number is the **median of the per-round ratios**, never the
    ratio of two medians, and the min/max spread plus the win count are printed
    next to it so that a non-result is visible as a non-result.

Usage
-----
    # full run
    python ab_bench.py --a ../upstream --b ../frozen/pkg --rounds 9 \
                       --out ab_final.json

    # single case
    python ab_bench.py --a ../upstream --b ../frozen/pkg --cases sudoku-hard-all

    # worker mode (used internally by the driver)
    python ab_bench.py --worker --pkg ../frozen/pkg --case sudoku-hard-all \
                       --solver OptimizedBacktrackingSolver --min-seconds 0.4
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def worker(pkg: str, case: str, solver: str, min_seconds: float, repeats: int = 0) -> dict:
    """Time one case in this process and print a JSON line."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import importlib

    import run_bench

    run_bench.load_pkg(pkg)
    solvers_mod = importlib.import_module("constraint.solvers")
    solver_obj = getattr(solvers_mod, solver)()

    catalogue = {
        name: (builder, mode, expected)
        for name, builder, mode, expected in run_bench.build_cases(solver, lambda _n: solver_obj)
    }
    builder, mode, expected = catalogue[case]

    # warm-up: also validates the expected solution count before anything is timed
    elapsed, count = run_bench.run_case(builder, mode, expected)

    # Calibrate a fixed repeat count from the warm-up, using a *fixed* number for
    # both arms (--repeats) so that two runs are directly comparable.  Falling
    # back to per-arm calibration would compare different amounts of work.
    if repeats:
        n_repeats = repeats
    else:
        # ceil, capped at 20: enough to lift a 10 ms case out of timer noise,
        # while keeping a 17 s case from running for minutes.
        n_repeats = min(20, max(1, math.ceil(min_seconds / max(elapsed, 1e-6))))

    t0 = time.perf_counter()
    for _ in range(n_repeats):
        _, again = run_bench.run_case(builder, mode, expected)
    total = time.perf_counter() - t0
    if again != count:
        raise RuntimeError("non-deterministic solution count")

    return {
        "pkg": os.path.abspath(pkg),
        "case": case,
        "solver": solver,
        "solutions": count,
        "repeats": n_repeats,
        "seconds": total,
        "per_run_ms": total / n_repeats * 1000,
    }


def run_worker(pkg: str, case: str, solver: str, min_seconds: float, repeats: int = 0) -> dict:
    """Spawn one worker process and return its JSON payload."""
    cmd = [
        sys.executable,
        os.path.abspath(__file__),
        "--worker",
        "--pkg",
        pkg,
        "--case",
        case,
        "--solver",
        solver,
        "--min-seconds",
        str(min_seconds),
        "--repeats",
        str(repeats),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"worker failed ({pkg}/{case}):\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def driver(args) -> None:
    """Run the interleaved A/B comparison and print one line per case."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    results = {"a": os.path.abspath(args.a), "b": os.path.abspath(args.b), "rounds": args.rounds, "cases": {}}

    for case in args.cases.split(","):
        # One calibration pass so that *both* arms do exactly the same amount of
        # work per sample.  Calibrating each arm separately would compare
        # different numbers of repetitions.
        calibration = run_worker(args.a, case, args.solver, args.min_seconds, repeats=0)
        repeats = calibration["repeats"]

        samples = {"a": [], "b": []}
        for round_index in range(args.rounds):
            # rotate the order so that neither arm is systematically first
            arms = [("a", args.a), ("b", args.b)]
            if round_index % 2:
                arms.reverse()
            for arm, pkg in arms:
                payload = run_worker(pkg, case, args.solver, args.min_seconds, repeats)
                samples[arm].append(payload["seconds"])

        ratios = [a / b for a, b in zip(samples["a"], samples["b"])]
        entry = {
            "repeats": repeats,
            "a_seconds": samples["a"],
            "b_seconds": samples["b"],
            "a_median_s": statistics.median(samples["a"]),
            "b_median_s": statistics.median(samples["b"]),
            "ratio_median": statistics.median(ratios),
            "ratio_min": min(ratios),
            "ratio_max": max(ratios),
            "b_faster_rounds": sum(1 for r in ratios if r > 1),
            "rounds": len(ratios),
        }
        results["cases"][case] = entry
        print(
            f"{case:20s} n={repeats:<3d} A={entry['a_median_s'] / repeats * 1000:8.2f} ms  "
            f"B={entry['b_median_s'] / repeats * 1000:8.2f} ms  "
            f"ratio median={entry['ratio_median']:.2f}x "
            f"[{entry['ratio_min']:.2f}-{entry['ratio_max']:.2f}]  "
            f"B faster in {entry['b_faster_rounds']}/{entry['rounds']} rounds",
            flush=True,
        )

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=2, ensure_ascii=False)
        print("written", args.out)


def main():
    """Dispatch between worker mode and driver mode."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", help="baseline package directory")
    parser.add_argument("--b", help="optimized package directory")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--pkg")
    parser.add_argument("--case")
    parser.add_argument("--cases", default="queens-8-all,queens-10-all,queens-16-first,queens-20-first,"
                                            "sudoku-hard-all,dedispersion-all,microhh-small-all,hotspot-all")
    parser.add_argument("--solver", default="OptimizedBacktrackingSolver")
    parser.add_argument("--rounds", type=int, default=9)
    parser.add_argument("--min-seconds", type=float, default=0.4)
    parser.add_argument("--repeats", type=int, default=0,
                        help="fixed repeat count per sample; 0 = calibrate from --min-seconds")
    parser.add_argument("--out")
    args = parser.parse_args()

    if args.worker:
        print(json.dumps(worker(args.pkg, args.case, args.solver, args.min_seconds, args.repeats)))
        return
    driver(args)


if __name__ == "__main__":
    main()

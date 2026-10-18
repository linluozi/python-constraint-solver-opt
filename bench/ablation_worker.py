"""Worker for ablation.py: time one case with one arm configuration.

Prints a single JSON line. `--repeats 0` calibrates the repeat count from the
warm-up run and reports it (the driver then passes that exact count to every arm,
so all arms do the same amount of work).
"""

import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_bench  # noqa: E402


def main():
    """Time the case once and print a single JSON line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pkg", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--dynamic-mrv", type=int, required=True)
    parser.add_argument("--restricted", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=0)
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import importlib

    run_bench.load_pkg(args.pkg)
    solvers_mod = importlib.import_module("constraint.solvers")
    solver = solvers_mod.OptimizedBacktrackingSolver(
        dynamic_mrv=bool(args.dynamic_mrv), restricted_pushdomains=bool(args.restricted)
    )

    catalogue = {
        name: (builder, mode, expected)
        for name, builder, mode, expected in run_bench.build_cases("OptimizedBacktrackingSolver", lambda _n: solver)
    }
    builder, mode, expected = catalogue[args.case]

    elapsed, count = run_bench.run_case(builder, mode, expected)
    repeats = args.repeats or min(20, max(1, math.ceil(0.4 / max(elapsed, 1e-6))))

    t0 = time.perf_counter()
    for _ in range(repeats):
        _, again = run_bench.run_case(builder, mode, expected)
    total = time.perf_counter() - t0
    if again != count:
        raise RuntimeError("non-deterministic solution count")

    print(json.dumps({"case": args.case, "solutions": count, "repeats": repeats, "seconds": total}))


if __name__ == "__main__":
    main()

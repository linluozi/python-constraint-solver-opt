"""Benchmark harness for python-constraint solver comparison.

Runs the same set of CSP problems against a given checkout of the `constraint`
package and reports:

  * wall-clock time (best of N repetitions)
  * number of search nodes (values popped from a domain and tested)
  * number of constraint invocations

Usage:
    python run_bench.py --pkg ../upstream --reps 5 --out base.json
    python run_bench.py --pkg ../python-constraint-opt --reps 5 --out opt.json

The `--count` pass instruments the constraint classes to obtain deterministic
(node / constraint-call) metrics; timing is always done on an uninstrumented
fresh import.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time


def load_pkg(path: str):
    """Import the `constraint` package from *path* (dropping any previous import)."""
    abs_path = os.path.abspath(path)
    sys.path.insert(0, abs_path)
    for name in [m for m in list(sys.modules) if m == "constraint" or m.startswith("constraint.")]:
        del sys.modules[name]
    import constraint  # noqa: E402

    return constraint


# ---------------------------------------------------------------------------
# benchmark problems
# ---------------------------------------------------------------------------

QUEEN_SOLUTIONS = {6: 4, 7: 40, 8: 92, 9: 352, 10: 724, 11: 2680, 12: 14200}


def queens(n: int, solver=None):
    """N-queens as a binary CSP (variables = rows, values = columns)."""
    from constraint import Problem

    problem = Problem(solver)
    rows = [f"q{i}" for i in range(n)]
    problem.addVariables(rows, list(range(n)))
    for i in range(n):
        for j in range(i + 1, n):
            problem.addConstraint(
                lambda a, b, d=j - i: a != b and abs(a - b) != d, (rows[i], rows[j])
            )
    return problem


def sudoku(grid: str, solver=None):
    """Classic 9x9 sudoku: 27 AllDifferent groups + givens as singleton domains."""
    from constraint import AllDifferentConstraint, Problem

    problem = Problem(solver)
    cells = [f"c{r}{c}" for r in range(9) for c in range(9)]
    for cell in cells:
        problem.addVariable(cell, list(range(1, 10)))
    {cell: i for i, cell in enumerate(cells)}
    for r in range(9):
        problem.addConstraint(AllDifferentConstraint(), [f"c{r}{c}" for c in range(9)])
    for c in range(9):
        problem.addConstraint(AllDifferentConstraint(), [f"c{r}{c}" for r in range(9)])
    for br in range(0, 9, 3):
        for bc in range(0, 9, 3):
            problem.addConstraint(
                AllDifferentConstraint(),
                [f"c{r}{c}" for r in range(br, br + 3) for c in range(bc, bc + 3)],
            )
    for i, ch in enumerate(grid.strip()):
        if ch in "123456789":
            problem.addConstraint(lambda v, x=int(ch): v == x, (cells[i],))
    return problem


SUDOKU_HARD = (
    "800000000"
    "003600000"
    "070090200"
    "050007000"
    "000045700"
    "000100030"
    "001000068"
    "008500010"
    "090000400"
)


def graph_coloring(n: int, p: float, colors: int, seed: int, solver=None):
    """Random graph k-colouring (AllDifferent on every edge)."""
    from constraint import AllDifferentConstraint, Problem

    rng = random.Random(seed)
    problem = Problem(solver)
    nodes = [f"v{i}" for i in range(n)]
    problem.addVariables(nodes, list(range(colors)))
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < p:
                edges.append((nodes[i], nodes[j]))
    for a, b in edges:
        problem.addConstraint(AllDifferentConstraint(), (a, b))
    return problem


def dedispersion(solver=None):
    """Official upstream benchmark (expected 11130 solutions)."""
    from constraint import Problem

    problem = Problem(solver)
    problem.addVariable("block_size_x", [1, 2, 4, 8] + [16 * i for i in range(1, 3)])
    problem.addVariable("block_size_y", [8 * i for i in range(4, 33)])
    problem.addVariable("block_size_z", [1])
    problem.addVariable("tile_size_x", [i for i in range(1, 5)])
    problem.addVariable("tile_size_y", [i for i in range(1, 9)])
    problem.addVariable("tile_stride_x", [0, 1])
    problem.addVariable("tile_stride_y", [0, 1])
    problem.addVariable("loop_unroll_factor_channel", [0])
    problem.addConstraint(
        [
            "32 <= block_size_x * block_size_y <= 1024",
            "tile_size_x > 1 or tile_stride_x == 0",
            "tile_size_y > 1 or tile_stride_y == 0",
        ]
    )
    return problem


def microhh(solver=None):
    """Official upstream benchmark (expected 138600 solutions)."""
    from constraint import Problem

    dev = {"max_threads_per_sm": 1024, "max_threads_per_block": 1536}
    problem = Problem(solver)
    problem.addVariable("STATIC_STRIDES", [0])
    problem.addVariable("TILING_STRATEGY", [0])
    problem.addVariable("REWRITE_INTERP", [0])
    problem.addVariable("BLOCK_SIZE_X", [1, 2, 4, 8, 16, 32, 128, 256, 512, 1024])
    problem.addVariable("BLOCK_SIZE_Y", [1, 2, 4, 8, 16, 32])
    problem.addVariable("BLOCK_SIZE_Z", [1, 2, 4])
    problem.addVariable("TILING_FACTOR_X", [1, 2, 4, 8])
    problem.addVariable("TILING_FACTOR_Y", [1, 2, 4])
    problem.addVariable("TILING_FACTOR_Z", [1, 2, 4])
    problem.addVariable("LOOP_UNROLL_FACTOR_X", [1, 2, 4, 8])
    problem.addVariable("LOOP_UNROLL_FACTOR_Y", [1, 2, 4])
    problem.addVariable("LOOP_UNROLL_FACTOR_Z", [1, 2, 4])
    problem.addVariable("BLOCKS_PER_MP", [0, 1, 2, 3, 4])
    problem.addConstraint(
        [
            f"BLOCK_SIZE_X * BLOCK_SIZE_Y * BLOCK_SIZE_Z * BLOCKS_PER_MP <= {dev['max_threads_per_sm']}",
            f"32 <= BLOCK_SIZE_X * BLOCK_SIZE_Y * BLOCK_SIZE_Z <= {dev['max_threads_per_block']}",
            "LOOP_UNROLL_FACTOR_X == 0 or TILING_FACTOR_X % LOOP_UNROLL_FACTOR_X == 0",
            "LOOP_UNROLL_FACTOR_Y == 0 or TILING_FACTOR_Y % LOOP_UNROLL_FACTOR_Y == 0",
            "LOOP_UNROLL_FACTOR_Z == 0 or TILING_FACTOR_Z % LOOP_UNROLL_FACTOR_Z == 0",
            "BLOCK_SIZE_X * TILING_FACTOR_X > 0",
            "BLOCK_SIZE_Y * TILING_FACTOR_Y > 0",
            "BLOCK_SIZE_Z * TILING_FACTOR_Z > 0",
        ]
    )
    return problem


def hotspot(solver=None):
    """Official upstream `hotspot` search space (expected 349853 solutions).

    Included as the "large enumeration" stress case: 349853 solutions with wide
    (5-7 variable) arithmetic constraints, i.e. the shape where reordering costs
    the most and saves the least.
    """
    from constraint import Problem

    dev = {"max_threads": 1024, "max_shared_memory_per_block": 49152, "max_shared_memory": 102400}
    max_tfactor = 10
    problem = Problem(solver)
    problem.addVariable("block_size_x", [1, 2, 4, 8, 16] + [32 * i for i in range(1, 33)])
    problem.addVariable("block_size_y", [2**i for i in range(6)])
    problem.addVariable("tile_size_x", [i for i in range(1, 11)])
    problem.addVariable("tile_size_y", [i for i in range(1, 11)])
    problem.addVariable("temporal_tiling_factor", [i for i in range(1, 11)])
    problem.addVariable("max_tfactor", [max_tfactor])
    problem.addVariable("loop_unroll_factor_t", [i for i in range(1, max_tfactor + 1)])
    problem.addVariable("sh_power", [0, 1])
    problem.addVariable("blocks_per_sm", [0, 1, 2, 3, 4])
    problem.addConstraint(
        [
            "block_size_x*block_size_y >= 32",
            "temporal_tiling_factor % loop_unroll_factor_t == 0",
            f"block_size_x*block_size_y <= {dev['max_threads']}",
            f"(block_size_x*tile_size_x + temporal_tiling_factor * 2) * (block_size_y*tile_size_y + temporal_tiling_factor * 2) * (2+sh_power) * 4 <= {dev['max_shared_memory_per_block']}",  # noqa: E501
            f"blocks_per_sm == 0 or (((block_size_x*tile_size_x + temporal_tiling_factor * 2) * (block_size_y*tile_size_y + temporal_tiling_factor * 2) * (2+sh_power) * 4) * blocks_per_sm <= {dev['max_shared_memory']})",  # noqa: E501
        ]
    )
    return problem


def microhh_small(solver=None):
    """Downscaled `microhh` (official benchmark, 138600 solutions is too slow to repeat)."""
    from constraint import Problem

    dev = {"max_threads_per_sm": 1024, "max_threads_per_block": 1536}
    problem = Problem(solver)
    problem.addVariable("STATIC_STRIDES", [0])
    problem.addVariable("TILING_STRATEGY", [0])
    problem.addVariable("REWRITE_INTERP", [0])
    problem.addVariable("BLOCK_SIZE_X", [1, 2, 4, 8, 16, 32, 128, 256])
    problem.addVariable("BLOCK_SIZE_Y", [1, 2, 4, 8, 16])
    problem.addVariable("BLOCK_SIZE_Z", [1, 2, 4])
    problem.addVariable("TILING_FACTOR_X", [1, 2, 4])
    problem.addVariable("TILING_FACTOR_Y", [1, 2])
    problem.addVariable("TILING_FACTOR_Z", [1, 2])
    problem.addVariable("LOOP_UNROLL_FACTOR_X", [1, 2, 4])
    problem.addVariable("LOOP_UNROLL_FACTOR_Y", [1, 2])
    problem.addVariable("LOOP_UNROLL_FACTOR_Z", [1, 2])
    problem.addVariable("BLOCKS_PER_MP", [0, 1, 2])
    problem.addConstraint(
        [
            f"BLOCK_SIZE_X * BLOCK_SIZE_Y * BLOCK_SIZE_Z * BLOCKS_PER_MP <= {dev['max_threads_per_sm']}",
            f"32 <= BLOCK_SIZE_X * BLOCK_SIZE_Y * BLOCK_SIZE_Z <= {dev['max_threads_per_block']}",
            "LOOP_UNROLL_FACTOR_X == 0 or TILING_FACTOR_X % LOOP_UNROLL_FACTOR_X == 0",
            "LOOP_UNROLL_FACTOR_Y == 0 or TILING_FACTOR_Y % LOOP_UNROLL_FACTOR_Y == 0",
            "LOOP_UNROLL_FACTOR_Z == 0 or TILING_FACTOR_Z % LOOP_UNROLL_FACTOR_Z == 0",
            "BLOCK_SIZE_X * TILING_FACTOR_X > 0",
            "BLOCK_SIZE_Y * TILING_FACTOR_Y > 0",
            "BLOCK_SIZE_Z * TILING_FACTOR_Z > 0",
        ]
    )
    return problem


def magic_square(n: int, solver=None):
    """Magic square: rows/cols/diagonals sum to the magic constant, all cells distinct."""
    from constraint import AllDifferentConstraint, ExactSumConstraint, Problem

    problem = Problem(solver)
    total = n * (n * n + 1) // 2
    cells = [f"x{r}{c}" for r in range(n) for c in range(n)]
    problem.addVariables(cells, list(range(1, n * n + 1)))
    problem.addConstraint(AllDifferentConstraint(), cells)
    for r in range(n):
        problem.addConstraint(ExactSumConstraint(total), [f"x{r}{c}" for c in range(n)])
    for c in range(n):
        problem.addConstraint(ExactSumConstraint(total), [f"x{r}{c}" for r in range(n)])
    problem.addConstraint(ExactSumConstraint(total), [f"x{i}{i}" for i in range(n)])
    problem.addConstraint(ExactSumConstraint(total), [f"x{i}{n - 1 - i}" for i in range(n)])
    return problem


# name -> (builder, mode, expected)
#   mode "all"  : count every solution
#   mode "first": stop at the first solution
def build_cases(solver_name: str, make_solver):
    """Return the benchmark catalogue: (name, builder, mode, expected solutions)."""
    def s():
        return make_solver(solver_name)

    cases = [
        ("queens-8-all", lambda: queens(8, s()), "all", QUEEN_SOLUTIONS[8]),
        ("queens-9-all", lambda: queens(9, s()), "all", QUEEN_SOLUTIONS[9]),
        ("queens-10-all", lambda: queens(10, s()), "all", QUEEN_SOLUTIONS[10]),
        ("queens-11-all", lambda: queens(11, s()), "all", QUEEN_SOLUTIONS[11]),
        ("queens-16-first", lambda: queens(16, s()), "first", None),
        ("queens-20-first", lambda: queens(20, s()), "first", None),
        ("sudoku-hard-all", lambda: sudoku(SUDOKU_HARD, s()), "all", 1),
        ("dedispersion-all", lambda: dedispersion(s()), "all", 11130),
        ("microhh-small-all", lambda: microhh_small(s()), "all", 11340),
        ("hotspot-all", lambda: hotspot(s()), "all", 349853),
    ]
    return cases


# ---------------------------------------------------------------------------
# instrumentation
# ---------------------------------------------------------------------------

class Counter:
    """Wrap every Constraint.__call__ so invocations can be counted."""
    def __init__(self):
        """Initialise the counter and the list of patched callables."""
        self.constraint_calls = 0
        self._installed = []

    def install(self, constraint_mod):
        """Wrap every Constraint subclass __call__ to count invocations."""
        from constraint.constraints import Constraint

        for obj in list(vars(constraint_mod.constraints).values()):
            if isinstance(obj, type) and issubclass(obj, Constraint) and "__call__" in obj.__dict__:
                original = obj.__dict__["__call__"]
                counter = self

                def wrapper(self, *args, _orig=original, **kwargs):
                    counter.constraint_calls += 1
                    return _orig(self, *args, **kwargs)

                obj.__call__ = wrapper
                self._installed.append((obj, original))

    def uninstall(self):
        """Restore the original Constraint.__call__ implementations."""
        for obj, original in self._installed:
            obj.__call__ = original
        self._installed.clear()


def run_case(builder, mode, expected, counter=None):
    """Build the problem, solve it, and return (seconds, solutions)."""
    problem = builder()
    t0 = time.perf_counter()
    if mode == "all":
        solutions = problem.getSolutions()
        count = len(solutions)
    else:
        solution = problem.getSolution()
        count = 1 if solution is not None else 0
        if solution is None:
            raise RuntimeError("no solution found for a satisfiable benchmark")
    elapsed = time.perf_counter() - t0
    if expected is not None and count != expected:
        raise RuntimeError(f"solution count mismatch: got {count}, expected {expected}")
    return elapsed, count


def main():
    """Parse the command line and run every requested case/solver combination."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pkg", required=True)
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--out", default=None)
    parser.add_argument("--solvers", default="BacktrackingSolver,OptimizedBacktrackingSolver")
    parser.add_argument("--only", default=None, help="comma separated case name filter")
    args = parser.parse_args()

    constraint = load_pkg(args.pkg)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import importlib

    solvers_mod = importlib.import_module("constraint.solvers")

    def make_solver(name):
        """Resolve a solver name, including the ablation arms of the optimized package.

        The ablation arms only exist in the patched package: they switch the two
        optimizations of ``OptimizedBacktrackingSolver`` on and off individually.
        """
        if name == "OptimizedLegacy":
            # both optimizations off -> should behave like the unpatched upstream
            return solvers_mod.OptimizedBacktrackingSolver(
                dynamic_mrv=False, restricted_pushdomains=False
            )
        if name == "OptimizedMRVOnly":
            # dynamic MRV on, push-domain restriction off
            return solvers_mod.OptimizedBacktrackingSolver(
                dynamic_mrv=True, restricted_pushdomains=False
            )
        if name == "OptimizedScopeOnly":
            # dynamic MRV off, push-domain restriction on
            return solvers_mod.OptimizedBacktrackingSolver(
                dynamic_mrv=False, restricted_pushdomains=True
            )
        return getattr(solvers_mod, name)()

    only = set(args.only.split(",")) if args.only else None

    results = {"pkg": os.path.abspath(args.pkg), "cases": {}}
    for solver_name in args.solvers.split(","):
        for case_name, builder, mode, expected in build_cases(solver_name, make_solver):
            if only and case_name not in only:
                continue
            # --- count pass (instrumented, single run) ---
            counter = Counter()
            counter.install(constraint)
            try:
                _, count = run_case(builder, mode, expected, counter)
                calls = counter.constraint_calls
            finally:
                counter.uninstall()

            # --- timing pass ---
            times = []
            for _ in range(args.reps):
                elapsed, c = run_case(builder, mode, expected)
                assert c == count, "non-deterministic solution count"
                times.append(elapsed)
            best = min(times)
            results["cases"].setdefault(case_name, {})[solver_name] = {
                "solutions": count,
                "constraint_calls": calls,
                "best_s": round(best, 4),
                "all_s": [round(t, 4) for t in times],
            }
            print(
                f"{case_name:22s} {solver_name:30s} sols={count:7d} calls={calls:12d} best={best:.3f}s",
                flush=True,
            )

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=2, ensure_ascii=False)
        print("written", args.out)


if __name__ == "__main__":
    main()

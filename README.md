# python-constraint — optimized solver build

This is a modified copy of **[python-constraint](https://github.com/python-constraint/python-constraint) 2.7.3**
(`main` @ `d91ba03d1fd6acc30d64fd9d513dc0523f697b5b`, BSD-2-Clause) in which the
backtracking search loop of the default solver was rewritten to remove three
concrete inefficiencies.

It is a drop-in replacement: same package name, same public API, same
constraints, same results.

![speed-up per benchmark case](docs/assets/speedup.png)

`20-queens` (first solution) goes from 2 628 ms to 3.1 ms, the classic hard
sudoku from 9 826 ms to 229 ms, and the enumeration-heavy official search spaces
(`dedispersion`, `microhh`, `hotspot`) improve by 13–32%. Method and caveats:
[`BENCHMARKS.md`](BENCHMARKS.md); the raw JSON is in `bench/results/`.

```python
from constraint import Problem

problem = Problem()                       # still OptimizedBacktrackingSolver by default
problem.addVariables("abc", range(1, 4))
problem.addConstraint("a < b")            # b < c
problem.addConstraint("b < c")
print(problem.getSolutions())             # [{'a': 1, 'b': 2, 'c': 3}]
```

## What changed

`constraint/solvers.py` holds the three algorithmic changes; `constraint/constraints.py`
additionally gets three empty-domain guards for a crash found on the way.

| # | Change | Effect |
|---|--------|--------|
| 1 | `SearchPlan` builds the variable order, degrees and constraint-neighbour table **once per solve** | removes an O(V log V) sort + V tuple allocations **per search node** |
| 2 | Minimum-Remaining-Values is evaluated **at every node against the live, forward-checked domain sizes**, using a single allocation-free scan | the search takes forced variables immediately instead of walking into a dead branch |
| 3 | Forward checking saves/restores **only the domains that share a constraint** with the variable being assigned | removes O(V) wasted `pushState`/`popState` calls per assignment on sparse problems |
| 4 | `ExactSumConstraint` / `MinSumConstraint` / `MaxSumConstraint` no longer call `min()`/`max()` on a domain that an earlier solve already emptied | solving the same `Problem` twice used to raise `ValueError` instead of returning the (empty) result |

Items 1–3 are the optimisation; item 4 is a crash fix that came out of testing it
(see `IMPROVEMENT_REPORT.md` §6).

Both optimizations can be turned off individually:

```python
OptimizedBacktrackingSolver(dynamic_mrv=False, restricted_pushdomains=False)  # upstream behaviour
```

The two changes are not equivalent, and the ablation below shows it: dynamic MRV
is what produces the orders-of-magnitude wins (and is a small **loss** on pure
enumeration), while the restricted push list is what pays on the enumeration-heavy
spaces. They are therefore exposed as two independent switches rather than being
hard-wired.

![ablation](docs/assets/ablation.png)

Read `IMPROVEMENT_REPORT.md` for the source analysis, and `BENCHMARKS.md` for the
measurement method and the actual numbers (including the cases where the gain is
small).

## Install

Nothing to install if you run from this directory — the package is pure Python
and is imported straight from the checkout.

```bash
# Python >= 3.11 is required (same as upstream)
python -c "import constraint; print(constraint.__version__ if hasattr(constraint,'__version__') else 'ok')"
```

To use it as a normal installed package instead:

```bash
pip install .
```

Upstream also offers Cython-compiled wheels (`pip install python-constraint2`).
This build is the **pure-Python** variant; the Cython `.c` sources were removed
from the archive because they are generated artifacts and would no longer match
the modified Python sources. See "Limitations" in `BENCHMARKS.md`.

Runtime dependencies: **none**. Test dependencies: `pytest` (and `pytest-cov`
if you keep the coverage settings in `pyproject.toml`).

## Run the tests

```bash
pip install pytest
python -m pytest tests -q
```

Expected in this environment: `76 passed, 1 skipped, 2 failed`. The two failures
are pre-existing on the untouched upstream checkout and are unrelated to the
patch:

* `tests/test_compilation.py::test_if_compiled` — asserts the package was built
  with Cython (it is not, in a pure-Python checkout);
* `tests/test_toml_file.py::test_versioning` — imports `poetry`, which is not
  installed here.

Only the new tests, if you want the short version:

```bash
python -m pytest tests/test_solver_optimizations.py -q      # 29 passed
python -m pytest tests/test_solvers.py tests/test_problem.py -q
```

## Run the benchmark

The benchmark harness lives in `bench/` and compares this build against any other
checkout of the package.

```bash
# A/B, interleaved, one process per sample (this is the number to trust)
python bench/ab_bench.py --a /path/to/upstream --b . --rounds 7 --out bench/results/ab.json

# single case, quick look
python bench/ab_bench.py --a /path/to/upstream --b . --cases sudoku-hard-all --rounds 3

# deterministic metrics only (constraint invocations, no timing noise)
python bench/run_bench.py --pkg . --reps 1 --solvers OptimizedBacktrackingSolver

# regenerate the two figures in docs/assets/ from the raw JSON (needs matplotlib)
python bench/make_figures.py
```

`bench/run_bench.py` also doubles as a correctness harness: every case declares
its expected number of solutions (n-queens 6..12, the official upstream
`dedispersion` 11130 and `hotspot` 349853 spaces, a unique-solution sudoku), and
the run aborts if a count changes.

## Usage examples

```python
from constraint import Problem, AllDifferentConstraint, ExactSumConstraint

# Sudoku-style: 9 cells per row/column/box, all different
problem = Problem()
cells = [f"c{r}{c}" for r in range(9) for c in range(9)]
problem.addVariables(cells, range(1, 10))
for r in range(9):
    problem.addConstraint(AllDifferentConstraint(), [f"c{r}{c}" for c in range(9)])
for c in range(9):
    problem.addConstraint(AllDifferentConstraint(), [f"c{r}{c}" for r in range(9)])
solution = problem.getSolution()

# Iterating instead of materialising every solution
for i, sol in enumerate(problem.getSolutionIter()):
    if i >= 10:
        break

# Turning the new heuristics off, e.g. to reproduce an old result exactly
from constraint import OptimizedBacktrackingSolver
legacy = Problem(OptimizedBacktrackingSolver(dynamic_mrv=False, restricted_pushdomains=False))
```

## Layout

```
constraint/            the package (only solvers.py differs from upstream)
tests/                 upstream test suite + test_solver_optimizations.py
bench/                 A/B harness, case catalogue, report generator, raw results
examples/, docs/       unchanged upstream material
IMPROVEMENT_REPORT.md  problem analysis, the patch, complexity, limitations
BENCHMARKS.md          how the numbers were produced, and the numbers
NOTICE.md              modification notice required by the BSD licence
LICENSE                upstream BSD-2-Clause licence, unmodified
```

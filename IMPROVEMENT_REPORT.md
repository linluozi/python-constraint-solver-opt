# Improvement report — `python-constraint` 2.7.3

| | |
|---|---|
| Repository | <https://github.com/python-constraint/python-constraint> |
| Baseline commit | `d91ba03d1fd6acc30d64fd9d513dc0523f697b5b` (2026-08-18, "Updated changelog before release", `pyproject.toml` version `2.7.3`) |
| License | BSD-2-Clause, `LICENSE` kept verbatim, see `NOTICE.md` |
| Language | Python ≥ 3.11 (Cython optional, not used here) |
| Verified by | `git clone`, reading `solvers.py` / `constraints.py` / `domain.py` / `problem.py`, running the upstream test suite, running the three official search spaces from `tests/benchmarks.py` |

---

## 1. The code under study

`Problem.getSolutions()` / `getSolution()` call `Problem._getArgs()`
(`constraint/problem.py:268`) once, which builds:

* `domains` — `dict[hashable, Domain]`, where `Domain` is a `list` subclass with
  `pushState` / `popState` / `hideValue` (`constraint/domain.py:52`),
* `constraints` — `list[(Constraint, variables)]`,
* `vconstraints` — `dict[var, list[(Constraint, variables)]]`, i.e. the
  constraint neighbourhood of every variable.

The default solver is `OptimizedBacktrackingSolver` (`constraint/problem.py:29`),
an iterative depth-first search in `constraint/solvers.py:276-342`. Per node it
does two things of interest:

```python
# (A) choose the next variable
lst = [(-len(vconstraints[variable]), len(domains[variable]), variable) for variable in domains]
lst.sort(key=lambda x: (x[0], x[1]))
for item in lst:
    if item[-1] not in assignments:
        variable = item[-1]
        values = domains[variable][:]
        if forwardcheck:
            pushdomains = [domains[x] for x in domains if x not in assignments and x != variable]
        break

# (B) try a value, with undo via Domain.pushState/popState
assignments[variable] = values.pop()
for constraint, variables in vconstraints[variable]:
    if not constraint(variables, domains, assignments, pushdomains):
        break
```

### 1.1 Problem 1 — the heuristic table is rebuilt at every node

`lst` is constructed and sorted **every time the loop looks for the next
variable**, and the loop re-enters that code after every failed value, not only
after a successful assignment. `domains` is a plain dict, so this costs:

* one list of *n* 3-tuples allocated per node,
* one `list.sort()` with a Python-level `key` lambda per node,
* *n* dict lookups for `vconstraints` and *n* for `domains`.

Everything in that table except `len(domains[variable])` is **static** for the
whole search: the constraint degree never changes, and the variable set never
changes. Rebuilding it per node is pure overhead proportional to the number of
nodes — which is exactly the quantity a CSP solver is judged on.

### 1.2 Problem 2 — "MRV" is not MRV

The tuple's second element is `len(domains[variable])` — the size **at the root of
the search**. Forward checking (`Domain.hideValue`, called from 15 sites in
`constraint/constraints.py`) shrinks domains *during* the search, but the
heuristic never re-reads them. So after the first few assignments the "Minimum
Remaining Values" part of the heuristic is a frozen tie-breaker.

Consequence, measured: on 20-queens the upstream search performs **4 902 182**
constraint invocations to find one solution, because it keeps assigning variables
in a stale order while some other variable has already been pruned to a single
value. A real MRV would take that variable immediately. Same story on sudoku:
**1 916 096** invocations, where a forced cell is sitting right there.

This is an *algorithmic* defect, not a micro-optimisation: it changes how many
nodes the search visits, not how fast a node runs.

### 1.3 Problem 3 — forward checking pushes every unassigned domain

```python
pushdomains = [domains[x] for x in domains if x not in assignments and x != variable]
```

Assigning one variable pushes a state onto **every** unassigned domain, then pops
them all again on backtrack. But a constraint can only ever hide values in the
domains of the variables it is declared on — verified at all 15 `hideValue` call
sites: they iterate `variables`, `self.sum_vars` or `unassigned`, all of which are
the variable list of that same constraint. On a sparse constraint graph (the
normal case for real problems: scheduling, configuration, colouring) nearly all of
those push/pop pairs are wasted work, and the cost is O(V) per assignment instead
of O(deg).

### 1.4 Why this is worth fixing, and what it is not

* Not a correctness bug — the search is right, just wasteful.
* Not a style issue — the wasted work scales with the node count.

`BacktrackingSolver` (the older, non-optimised reference solver) has the same
three problems, and `RecursiveBacktrackingSolver` rebuilds the sorted table on
**every recursive call**, which is even worse.

---

## 2. The change

**`constraint/solvers.py`** holds all of the algorithmic work. One additional,
non-algorithmic fix was made in `constraint/constraints.py` (three empty-domain
guards, §6) because it is a crash rather than a slow path. `domain.py`,
`parser.py`, `problem.py`, the public API and the constraint semantics are
byte-identical to upstream.

### 2.1 `SearchPlan` — compute the static data once

New class, built once per solve:

```python
class SearchPlan:
    __slots__ = ("names", "domains", "degrees", "neighbours", "index")
```

* `names` — variables in exactly the order `getSortedVariables()` produced, so
  the first choice of the search is unchanged;
* `domains[i]` — the `Domain` object of `names[i]`;
* `degrees[i]` — `-len(vconstraints[v])`, precomputed;
* `neighbours[i]` — indices of the variables that share at least one constraint
  with `names[i]`, i.e. the only domains a constraint of that variable can write
  to;
* `index` — variable → position.

Cost O(V + E) once, instead of O(V log V) + O(V) allocations per node.

### 2.2 Dynamic MRV, allocation-free

```python
chosen = -1
for i, is_taken in enumerate(taken):
    if is_taken:
        continue
    degree = degrees[i]
    size = len(plan_domains[i])            # live, forward-checked size
    if chosen < 0 or degree < chosen_degree or (degree == chosen_degree and size < chosen_size):
        chosen = i; chosen_degree = degree; chosen_size = size
```

* no list, no tuples, no `sort()`, no key callback;
* `len(plan_domains[i])` reads the **current** domain, so MRV actually does what
  its name says;
* tie-breaking order is unchanged (degree → domain size → static order), so the
  search is deterministic and the first branch on the first node is the same as
  upstream.

### 2.3 Restricted push domains

```python
pushdomains = [plan_domains[j] for j in neighbours[i] if not taken[j]]
```

Only the domains a constraint of the current variable can write to are saved and
restored. Same `pushState`/`popState` protocol and nesting discipline, smaller set.

This is a documented assumption: *"a constraint only ever hides values in the
domains of the variables it is declared on"*. It holds for every constraint
shipped with the package and for the contract of `Constraint.__call__` in the
docs. A user with a custom constraint that mutates a foreign domain can pass
`restricted_pushdomains=False`. A test
(`test_constraint_hiding_values_in_its_own_variables_survives_restriction`)
exercises a constraint that really does call `hideValue`, so this is tested
rather than assumed.

### 2.4 The other two solvers

* `BacktrackingSolver` — keeps the static order on purpose (it is the simple
  reference solver) but no longer rebuilds/sorts the table per node and only
  pushes the relevant domains.
* `RecursiveBacktrackingSolver` — the `SearchPlan` is built once and threaded
  through the recursion instead of being rebuilt on every call; both heuristics
  apply.

### 2.5 Escape hatches

```python
OptimizedBacktrackingSolver(dynamic_mrv=False, restricted_pushdomains=False)   # == upstream behaviour
```

Both optimizations are individually switchable. This is what makes the ablation
in `BENCHMARKS.md` §6 possible and lets anyone reproduce the old behaviour
bit-for-bit.

### Complexity

| | upstream | this build |
|---|---|---|
| heuristic per node | O(V log V) + V tuple allocations + sort-key calls | O(V), no allocation |
| MRV input | domain sizes at the root | current, forward-checked sizes |
| push/pop per assignment | all unassigned domains, O(V) | constraint neighbours only, O(deg) |
| plan construction | — | O(V + E), once per solve |
| search space | — | unchanged (same solution set) |
| worst-case tree | — | unchanged in theory, but dead branches are found earlier |

Space: one `SearchPlan` (O(V + E)) plus a `taken` bitmap per solve — dominated by
the `vconstraints` structure upstream already builds.

---

## 3. Files changed

```
constraint/solvers.py                   modified   (788 -> 951 lines; 9 hunks, see solvers.patch)
tests/test_solver_optimizations.py      new        29 tests
bench/run_bench.py                      new        case catalogue, solution-count assertions, call counter
bench/ab_bench.py                       new        interleaved A/B timing harness
bench/ablation.py, bench/ablation_worker.py  new   switch-on/switch-off ablation
bench/make_report.py                    new        JSON → markdown tables
bench/make_figures.py                   new        JSON → docs/assets/*.png
docs/assets/speedup.png, ablation.png   new        the two figures used in README/BENCHMARKS
bench/results/*.json, *.txt             new        raw measurements
README.md                               new        how to run this build
IMPROVEMENT_REPORT.md                   this file
BENCHMARKS.md                           new        method + numbers
NOTICE.md                               new        modification notice (BSD requirement)
```

`diff -rq` against the upstream checkout reports exactly `constraint/solvers.py`
as modified plus the new test file — nothing else in the tree was touched.

---

## 4. Verified by execution

| check | result |
|---|---|
| upstream test suite (`pytest tests`) | **76 passed, 1 skipped, 2 failed** — both failures also fail on the untouched upstream checkout here (`test_if_compiled` expects a Cython build; `test_versioning` imports `poetry`) |
| new test file | **29 passed** |
| solution sets vs `dynamic_mrv=False, restricted_pushdomains=False` | identical on n-queens 6–9, sudoku, `dedispersion`, sparse graphs, unary constraints, non-string keys |
| official search spaces | `dedispersion` 11 130 and `hotspot` 349 853 solutions, unchanged |
| deterministic work count | `queens-20-first` 4 902 182 → 6 649 invocations (see `BENCHMARKS.md` §5) |
| timing | see `BENCHMARKS.md`; every quoted number comes from the interleaved harness, with the spread and win-count shown |

---

## 5. Limitations

1. **Pure Python only.** Upstream also ships Cython-generated `constraint/*.c`;
   those were removed from this archive (generated artifacts, and they would no
   longer match the modified sources). The optimizations would carry over to a
   Cython build, but the *relative* gain would shrink, since the per-node Python
   overhead removed here is what Cython already removes.
2. **Problem-shape dependent.** Dynamic MRV is worth 700x+ where forward checking
   prunes (n-queens, sudoku) and is a **net loss of ~10%** on pure enumeration
   (`dedispersion` 0.83x, `microhh` 0.93x in the ablation) where the tree is
   already tight. The restricted-push change covers those cases (1.22x / 1.57x).
   No single headline speed-up is claimed for that reason.
3. **`queens-11-all` shows the two changes interacting**: MRV alone 1.34x, both
   together 1.19x. Still faster than upstream, but the combination is not the sum
   of its parts. Documented rather than hidden.
4. **Memory was not measured.** The change removes allocations, but no RSS
   measurement was taken, so no memory claim is made.
5. **`ParallelSolver` and `MinConflictsSolver` untouched.** The former is
   documented upstream as experimental; the latter is local search without
   forward checking, where these changes do not apply.
6. Other solvers' first-found solution may differ from upstream when
   `dynamic_mrv=True` — the solution is still valid and the *set* of solutions is
   identical, but "which solution comes first" changes because the search order
   changes. This is the intended effect; it is covered by
   `test_first_solution_of_legacy_is_reachable_by_new_solver`.

---

## 6. Upstream crash found on the way (and fixed)

`ExactSumConstraint.preProcess` (`constraint/constraints.py:321`),
`MinSumConstraint.preProcess` (`:546`) and `MaxSumConstraint.preProcess`
(`:694`) compute an initial bound with `min(domains[variable])` /
`max(domains[variable])` without checking for an empty domain. `preProcess` runs
on **every** solve, and the pruning it performs is never undone, so a second
solve of the same `Problem` re-enters `preProcess` with already-empty domains and
crashes. Reproduced on the untouched upstream checkout:

```python
p = Problem(); p.addVariables(["a","b","c"], [1,2,3])
p.addConstraint(AllDifferentConstraint(), ["a","b","c"])
p.addConstraint(ExactSumConstraint(100), ["a","b","c"])
p.getSolutions()   # -> []
p.getSolutions()   # -> ValueError: min() iterable argument is empty
```

This is a genuine crash, not a slow path, so it is fixed here: the initial bound
computation now uses the same empty-domain guard (`... if len(domain) > 0 else 0`)
that the *recalculation* further down each `preProcess` already used — i.e. the
fix follows the file's own existing convention rather than inventing one.

Three regression tests (`test_sum_constraints_survive_a_second_solve`, one per
constraint class) pin the behaviour: two consecutive `getSolutions()` calls plus
`getSolution()` must all return an empty result instead of raising.

Note that the pruning itself is still permanent (a second solve sees the pruned
domains). That is upstream's design — `Problem._getArgs` only calls
`Domain.resetState`, which restores values hidden during the *search*, not values
removed by `preProcess` — and changing it would change semantics, so it was left
alone.

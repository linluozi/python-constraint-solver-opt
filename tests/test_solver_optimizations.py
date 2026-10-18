"""Tests for the solver optimizations added on top of python-constraint 2.7.3.

The optimizations are:

* :py:class:`constraint.solvers.SearchPlan` - the heuristic variable order and the
  constraint-neighbour table are built once per solve instead of at every node.
* *dynamic MRV* - the Minimum Remaining Values heuristic is re-evaluated at every
  node using the current (forward-checked) domain sizes, with a single
  allocation-free scan instead of "build a list of tuples and sort it".
* *restricted push domains* - only the domains a variable shares a constraint with
  are pushed/popped, instead of every unassigned domain.

``OptimizedBacktrackingSolver(dynamic_mrv=False, restricted_pushdomains=False)``
restores the previous behaviour exactly, which is what makes the equivalence
tests below possible.
"""

import pytest

from constraint import (
    AllDifferentConstraint,
    BacktrackingSolver,
    ExactSumConstraint,
    FunctionConstraint,
    MaxSumConstraint,
    MinSumConstraint,
    OptimizedBacktrackingSolver,
    Problem,
    RecursiveBacktrackingSolver,
)
from constraint.constraints import Constraint
from constraint.solvers import SearchPlan


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


SOLVERS = [
    BacktrackingSolver,
    OptimizedBacktrackingSolver,
    RecursiveBacktrackingSolver,
]
SOLVER_IDS = [solver.__name__ for solver in SOLVERS]


def legacy():
    """A solver configured to behave exactly like the unoptimized implementation."""
    return OptimizedBacktrackingSolver(dynamic_mrv=False, restricted_pushdomains=False)


def queens(n, solver=None):
    problem = Problem(solver)
    rows = [f"q{i}" for i in range(n)]
    problem.addVariables(rows, list(range(n)))
    for i in range(n):
        for j in range(i + 1, n):
            problem.addConstraint(
                lambda a, b, d=j - i: a != b and abs(a - b) != d, (rows[i], rows[j])
            )
    return problem


def dedispersion(solver=None):
    """Upstream benchmark, expected 11130 solutions."""
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


SUDOKU = (
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


def sudoku(grid=SUDOKU, solver=None):
    problem = Problem(solver)
    cells = [f"c{r}{c}" for r in range(9) for c in range(9)]
    for cell in cells:
        problem.addVariable(cell, list(range(1, 10)))
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


def as_set(solutions):
    return {tuple(sorted(solution.items())) for solution in solutions}


class CallCounter:
    """Counts constraint invocations by wrapping every Constraint subclass."""

    def __init__(self):
        self.count = 0
        self._installed = []

    def __enter__(self):
        import constraint.constraints as constraints_module

        for obj in list(vars(constraints_module).values()):
            if isinstance(obj, type) and issubclass(obj, Constraint) and "__call__" in obj.__dict__:
                original = obj.__dict__["__call__"]
                counter = self

                def wrapper(instance, *args, _orig=original, **kwargs):
                    counter.count += 1
                    return _orig(instance, *args, **kwargs)

                obj.__call__ = wrapper
                self._installed.append((obj, original))
        return self

    def __exit__(self, *exc):
        for obj, original in self._installed:
            obj.__call__ = original
        self._installed.clear()
        return False


# --------------------------------------------------------------------------
# SearchPlan
# --------------------------------------------------------------------------


def test_search_plan_order_matches_get_sorted_variables():
    problem = queens(8)
    domains, constraints, vconstraints = problem._getArgs()
    solver = OptimizedBacktrackingSolver()
    plan = SearchPlan(domains, vconstraints)
    assert plan.names == solver.getSortedVariables(domains, vconstraints)
    assert [domains[name] for name in plan.names] == plan.domains


def test_search_plan_neighbours_are_symmetric_and_self_free():
    problem = queens(8)
    domains, constraints, vconstraints = problem._getArgs()
    plan = SearchPlan(domains, vconstraints)
    index = plan.index
    for i, neighbours in enumerate(plan.neighbours):
        assert i not in neighbours
        for j in neighbours:
            assert i in plan.neighbours[j]
    # queens is a complete graph: every variable neighbours every other one
    assert all(len(neighbours) == len(plan.names) - 1 for neighbours in plan.neighbours)
    assert len(index) == len(plan.names)


def test_search_plan_neighbours_of_sparse_problem():
    problem = Problem()
    problem.addVariables(["a", "b", "c", "d"], [1, 2])
    problem.addConstraint(AllDifferentConstraint(), ["a", "b"])  # only edge
    domains, constraints, vconstraints = problem._getArgs()
    plan = SearchPlan(domains, vconstraints)
    index = plan.index
    assert set(plan.neighbours[index["a"]]) == {index["b"]}
    assert set(plan.neighbours[index["b"]]) == {index["a"]}
    # c and d are unconstrained: they have no neighbours at all
    assert plan.neighbours[index["c"]] == ()
    assert plan.neighbours[index["d"]] == ()


# --------------------------------------------------------------------------
# equivalence with the previous behaviour
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size,expected", [(6, 4), (7, 40), (8, 92), (9, 352)])
def test_queens_solution_count_unchanged(size, expected):
    assert len(queens(size).getSolutions()) == expected
    assert len(queens(size, legacy()).getSolutions()) == expected


def test_queens_solution_set_identical_to_legacy():
    assert as_set(queens(8).getSolutions()) == as_set(queens(8, legacy()).getSolutions())


def test_dedispersion_solution_count_unchanged():
    assert len(dedispersion().getSolutions()) == 11130
    assert len(dedispersion(legacy()).getSolutions()) == 11130


def test_sudoku_solution_identical_to_legacy():
    solutions = sudoku().getSolutions()
    assert len(solutions) == 1
    assert as_set(solutions) == as_set(sudoku(solver=legacy()).getSolutions())


def test_all_solvers_agree_on_solution_set():
    reference = as_set(queens(8, legacy()).getSolutions())
    for solver in SOLVERS:
        assert as_set(queens(8, solver()).getSolutions()) == reference


def test_solution_is_valid_for_every_solver():
    problem = sudoku()
    expected = problem.getSolutions()[0]
    for solver in SOLVERS:
        solution = sudoku(solver=solver()).getSolution()
        assert solution == expected


def test_first_solution_of_legacy_is_reachable_by_new_solver():
    """The new default may return a different (but still valid) first solution."""
    first_legacy = queens(10, legacy()).getSolution()
    all_new = as_set(queens(10).getSolutions())
    assert tuple(sorted(first_legacy.items())) in all_new


# --------------------------------------------------------------------------
# the optimizations actually do something
# --------------------------------------------------------------------------


def test_dynamic_mrv_reduces_constraint_calls_on_queens():
    with CallCounter() as legacy_counter:
        legacy_solutions = queens(10, legacy()).getSolutions()
    with CallCounter() as new_counter:
        new_solutions = queens(10).getSolutions()
    assert as_set(legacy_solutions) == as_set(new_solutions)
    assert new_counter.count < legacy_counter.count


def test_dynamic_mrv_reduces_constraint_calls_on_sudoku():
    with CallCounter() as legacy_counter:
        legacy_solutions = sudoku(solver=legacy()).getSolutions()
    with CallCounter() as new_counter:
        new_solutions = sudoku().getSolutions()
    assert as_set(legacy_solutions) == as_set(new_solutions)
    assert new_counter.count < legacy_counter.count


def test_restricted_pushdomains_does_not_change_results():
    """Turning the push-domain restriction off must not change any result."""
    unrestricted = OptimizedBacktrackingSolver(restricted_pushdomains=False)
    for builder in (lambda s: queens(8, s), lambda s: sudoku(SUDOKU, s), lambda s: dedispersion(s)):
        assert as_set(builder(None).getSolutions()) == as_set(builder(unrestricted).getSolutions())


def test_restricted_pushdomains_pushes_fewer_domains():
    """Directly check the size of the push list on a sparse problem."""
    captured_legacy = []
    captured_new = []

    class SpyConstraint(Constraint):
        """Records how many domains were saved alongside it."""

        def __init__(self, sink):
            self.sink = sink

        def __call__(self, variables, domains, assignments, forwardcheck=False):
            if forwardcheck:
                self.sink.append(len(forwardcheck))
            return True

    def build(sink, solver):
        problem = Problem(solver)
        problem.addVariables(["a", "b", "c", "d", "e", "f"], [1, 2, 3])
        # only a-b are constrained, so only those domains can be touched
        problem.addConstraint(SpyConstraint(sink), ["a", "b"])
        return problem

    build(captured_legacy, OptimizedBacktrackingSolver(restricted_pushdomains=False)).getSolutions()
    build(captured_new, OptimizedBacktrackingSolver(restricted_pushdomains=True)).getSolutions()
    assert captured_legacy and captured_new
    assert max(captured_new) < max(captured_legacy)


# --------------------------------------------------------------------------
# custom constraint that hides values (push/pop correctness)
# --------------------------------------------------------------------------


class ParityNeighbourConstraint(Constraint):
    """Unusual but legal: hides a value in the domain of its other variable."""

    def __call__(self, variables, domains, assignments, forwardcheck=False):
        a, b = variables
        if a in assignments and forwardcheck and b not in assignments:
            domain = domains[b]
            forbidden = assignments[a] + 1
            if forbidden in domain:
                domain.hideValue(forbidden)
                if not domain:
                    return False
        if a in assignments and b in assignments and assignments[b] == assignments[a] + 1:
            return False
        return True


def test_constraint_hiding_values_in_its_own_variables_survives_restriction():
    def build(solver):
        problem = Problem(solver)
        problem.addVariable("a", [1, 2])
        problem.addVariable("b", [1, 2, 3])
        problem.addVariable("c", [1, 2, 3])
        problem.addConstraint(ParityNeighbourConstraint(), ["a", "b"])
        return problem

    restricted = build(OptimizedBacktrackingSolver())
    unrestricted = build(OptimizedBacktrackingSolver(restricted_pushdomains=False))
    legacy_solver = build(legacy())
    reference = as_set(legacy_solver.getSolutions())
    assert as_set(unrestricted.getSolutions()) == reference
    assert as_set(restricted.getSolutions()) == reference


# --------------------------------------------------------------------------
# edge cases
# --------------------------------------------------------------------------


def test_empty_problem():
    assert Problem().getSolutions() == []
    assert Problem(legacy()).getSolutions() == []
    assert Problem().getSolution() is None


def test_single_variable_single_value():
    problem = Problem()
    problem.addVariable("only", [42])
    assert problem.getSolutions() == [{"only": 42}]
    assert problem.getSolution() == {"only": 42}


def test_unsatisfiable_problem_and_domain_restoration():
    problem = Problem()
    problem.addVariables(["a", "b"], [1, 2])
    problem.addConstraint(AllDifferentConstraint(), ["a", "b"])
    problem.addConstraint(lambda a, b: a == b, ["a", "b"])
    assert problem.getSolutions() == []
    # every hidden value must have been restored - otherwise a second run would differ
    assert all(len(domain) == 2 for domain in problem._variables.values())
    assert problem.getSolutions() == []


def test_domains_restored_after_complete_search():
    problem = queens(8)
    sizes_before = {name: len(domain) for name, domain in problem._variables.items()}
    problem.getSolutions()
    sizes_after = {name: len(domain) for name, domain in problem._variables.items()}
    assert sizes_before == sizes_after


def test_repeated_search_after_unsatisfiable_is_stable():
    """A failed search must not poison the next one.

    ``_getArgs`` calls ``resetState`` on every domain before each solve, so the
    pruning done by the search itself is undone. Pruning done inside
    ``Constraint.preProcess`` is *not* undone (same as upstream), which used to
    crash the second solve on an empty domain - see the regression tests below.
    """
    problem = Problem()
    problem.addVariables(["a", "b", "c"], [1, 2, 3])
    problem.addConstraint(AllDifferentConstraint(), ["a", "b", "c"])
    problem.addConstraint(lambda a, b, c: a + b + c == 100, ["a", "b", "c"])
    assert problem.getSolutions() == []
    assert problem.getSolutions() == []
    assert problem.getSolution() is None
    assert problem.getSolutions() == []


@pytest.mark.parametrize(
    "constraint_factory",
    [
        lambda: ExactSumConstraint(100),
        lambda: MinSumConstraint(100),
        lambda: MaxSumConstraint(0),
    ],
    ids=["ExactSumConstraint", "MinSumConstraint", "MaxSumConstraint"],
)
def test_sum_constraints_survive_a_second_solve(constraint_factory):
    """Regression: ``preProcess`` used to call min()/max() on an emptied domain.

    The first solve prunes every value away (the sum is unreachable), and the
    second solve re-runs ``preProcess`` on the now-empty domains. Upstream 2.7.3
    raises ``ValueError: min() iterable argument is empty`` there; this build
    guards the initial bound computation the same way the recalculation further
    down already was.
    """
    problem = Problem()
    problem.addVariables(["a", "b", "c"], [1, 2, 3])
    problem.addConstraint(constraint_factory(), ["a", "b", "c"])
    assert problem.getSolutions() == []
    assert problem.getSolutions() == []
    assert problem.getSolution() is None


def build_unary(solver):
    problem = Problem(solver)
    problem.addVariables(["a", "b"], [1, 2, 3])
    problem.addConstraint(lambda v: v > 1, ("a",))
    problem.addConstraint(lambda v: v < 3, ("b",))
    return problem


def test_unary_constraints_only():
    problem = build_unary(None)
    assert len(problem.getSolutions()) == 4
    assert as_set(problem.getSolutions()) == as_set(build_unary(legacy()).getSolutions())


def test_non_string_variable_keys():
    problem = Problem()
    problem.addVariable(0, [1, 2])
    problem.addVariable((1, "x"), [1, 2])
    problem.addConstraint(AllDifferentConstraint(), [0, (1, "x")])
    assert len(problem.getSolutions()) == 2


def test_forwardcheck_disabled_path():
    solver = OptimizedBacktrackingSolver(forwardcheck=False)
    problem = queens(8, solver)
    assert len(problem.getSolutions()) == 92


def test_deterministic_repeated_runs():
    first = [tuple(sorted(s.items())) for s in queens(9).getSolutions()]
    second = [tuple(sorted(s.items())) for s in queens(9).getSolutions()]
    assert first == second


def test_get_solution_iter_partial_consumption():
    """Stopping the generator early must not corrupt the problem for later runs.

    The upstream implementation does not unwind the search state when the
    generator is closed, so the domains may stay pruned. The guarantee this
    test protects is that a subsequent full solve still returns the complete,
    correct solution set.
    """
    problem = queens(8)
    iterator = problem.getSolutionIter()
    for _ in range(5):
        next(iterator)
    iterator.close()
    assert len(problem.getSolutions()) == 92


def test_function_constraint_and_string_constraint_mixed():
    problem = build_mixed(None)
    solutions = problem.getSolutions()
    assert len(solutions) == 4
    assert as_set(solutions) == as_set(build_mixed(legacy()).getSolutions())


def build_mixed(solver):
    problem = Problem(solver)
    problem.addVariables(["x", "y"], [1, 2, 3, 4])
    problem.addConstraint("x < y")
    problem.addConstraint(FunctionConstraint(lambda x, y: (x + y) % 2 == 1), ["x", "y"])
    return problem

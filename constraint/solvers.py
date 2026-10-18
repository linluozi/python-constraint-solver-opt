"""Module containing the code for the problem solvers."""

import random
from types import FunctionType
from constraint.domain import Domain
from constraint.constraints import Constraint, FunctionConstraint, CompilableFunctionConstraint
from collections.abc import Hashable

# for parallel solver
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor


def getArcs(domains: dict, constraints: list[tuple]) -> dict:
    """Return a dictionary mapping pairs (arcs) of constrained variables.

    @attention: Currently unused.
    """
    arcs = {}
    for x in constraints:
        constraint, variables = x
        if len(variables) == 2:
            variable1, variable2 = variables
            arcs.setdefault(variable1, {}).setdefault(variable2, []).append(x)
            arcs.setdefault(variable2, {}).setdefault(variable1, []).append(x)
    return arcs


def doArc8(arcs: dict, domains: dict, assignments: dict) -> bool:
    """Perform the ARC-8 arc checking algorithm and prune domains.

    @attention: Currently unused.
    """
    check = dict.fromkeys(domains, True)
    while check:
        variable, _ = check.popitem()
        if variable not in arcs or variable in assignments:
            continue
        domain = domains[variable]
        arcsvariable = arcs[variable]
        for othervariable in arcsvariable:
            arcconstraints = arcsvariable[othervariable]
            if othervariable in assignments:
                otherdomain = [assignments[othervariable]]
            else:
                otherdomain = domains[othervariable]
            if domain:
                # changed = False
                for value in domain[:]:
                    assignments[variable] = value
                    if otherdomain:
                        for othervalue in otherdomain:
                            assignments[othervariable] = othervalue
                            for constraint, variables in arcconstraints:
                                if not constraint(variables, domains, assignments, True):
                                    break
                            else:
                                # All constraints passed. Value is safe.
                                break
                        else:
                            # All othervalues failed. Kill value.
                            domain.hideValue(value)
                            # changed = True
                        del assignments[othervariable]
                del assignments[variable]
                # if changed:
                #     check.update(dict.fromkeys(arcsvariable))
            if not domain:
                return False
    return True


class SearchPlan:
    """Index-based view of the search variables, built once per solve.

    The backtracking solvers repeatedly need (a) a tie-breaking order over the
    variables and (b) the set of variables a given variable shares a constraint
    with.  Both are static for the whole search, so they are precomputed here
    instead of being rebuilt (and re-sorted) at every node of the search tree.

    Attributes:
        names: variables in heuristic order (see :py:meth:`OptimizedBacktrackingSolver.getSortedVariables`)
        domains: the :py:class:`~constraint.domain.Domain` of ``names[i]``
        degrees: ``-len(vconstraints[v])`` for every variable, i.e. the number of
            constraints a variable participates in, negated so that "more
            constrained" sorts first
        neighbours: for every variable, the indices of the other variables that
            appear together with it in at least one constraint
        index: mapping from variable to its position in ``names``
    """

    __slots__ = ("names", "domains", "degrees", "neighbours", "index")

    def __init__(self, domains: dict, vconstraints: dict):
        """Build the static order, the degree table and the constraint-neighbour table."""
        order = [(-len(vconstraints[variable]), len(domains[variable]), variable) for variable in domains]
        order.sort(key=lambda item: (item[0], item[1]))
        self.names = [item[2] for item in order]
        self.degrees = [item[0] for item in order]
        self.domains = [domains[variable] for variable in self.names]
        self.index = {variable: i for i, variable in enumerate(self.names)}
        self.neighbours = []
        for variable in self.names:
            related = set()
            for _constraint, variables in vconstraints[variable]:
                for other in variables:
                    if other != variable and other in self.index:
                        related.add(other)
            self.neighbours.append(tuple(sorted(self.index[other] for other in related)))


class Solver:
    """Abstract base class for solvers."""

    requires_pickling = False

    def getSolution(self, domains: dict, constraints: list[tuple], vconstraints: dict):
        """Return one solution for the given problem.

        Args:
            domains (dict): Dictionary mapping variables to their domains
            constraints (list): List of pairs of (constraint, variables)
            vconstraints (dict): Dictionary mapping variables to a list
                of constraints affecting the given variables.
        """
        msg = f"{self.__class__.__name__} is an abstract class"
        raise NotImplementedError(msg)

    def getSolutions(self, domains: dict, constraints: list[tuple], vconstraints: dict):
        """Return all solutions for the given problem.

        Args:
            domains (dict): Dictionary mapping variables to domains
            constraints (list): List of pairs of (constraint, variables)
            vconstraints (dict): Dictionary mapping variables to a list
                of constraints affecting the given variables.
        """
        msg = f"{self.__class__.__name__} provides only a single solution"
        raise NotImplementedError(msg)

    def getSolutionIter(self, domains: dict, constraints: list[tuple], vconstraints: dict):
        """Return an iterator for the solutions of the given problem.

        Args:
            domains (dict): Dictionary mapping variables to domains
            constraints (list): List of pairs of (constraint, variables)
            vconstraints (dict): Dictionary mapping variables to a list
                of constraints affecting the given variables.
        """
        msg = f"{self.__class__.__name__} doesn't provide iteration"
        raise NotImplementedError(msg)


class BacktrackingSolver(Solver):
    """Problem solver with backtracking capabilities.

    Examples:
        >>> result = [[('a', 1), ('b', 2)],
        ...           [('a', 1), ('b', 3)],
        ...           [('a', 2), ('b', 3)]]

        >>> problem = Problem(BacktrackingSolver())
        >>> problem.addVariables(["a", "b"], [1, 2, 3])
        >>> problem.addConstraint(lambda a, b: b > a, ["a", "b"])

        >>> solution = problem.getSolution()
        >>> sorted(solution.items()) in result
        True

        >>> for solution in problem.getSolutionIter():
        ...     sorted(solution.items()) in result
        True
        True
        True

        >>> for solution in problem.getSolutions():
        ...     sorted(solution.items()) in result
        True
        True
        True
    """

    def __init__(self, forwardcheck=True):
        """Initialization method.

        Args:
            forwardcheck (bool): If false forward checking will not be
                requested to constraints while looking for solutions
                (default is true)
        """
        self._forwardcheck = forwardcheck

    def getSolutionIter(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        forwardcheck = self._forwardcheck
        assignments = {}

        # OPTIMIZATION: the heuristic order and the constraint neighbourhood of every
        # variable are static, so they are computed once (was: rebuilt and re-sorted
        # at every single node of the search tree by the original implementation).
        plan = SearchPlan(domains, vconstraints)
        names = plan.names
        plan_domains = plan.domains
        degrees = plan.degrees
        neighbours = plan.neighbours
        taken = [False] * len(names)

        queue = []

        while True:
            # Mix the Degree and Minimum Remaing Values (MRV) heuristics.
            # OPTIMIZATION: a single allocation-free scan picks the same variable the
            # "build a list of tuples + sort it" version picked, but in O(n) with no
            # tuple/list allocation and no Python-level sort key callback.
            chosen = -1
            chosen_degree = 0
            chosen_size = 0
            for i, is_taken in enumerate(taken):
                if is_taken:
                    continue
                degree = degrees[i]
                size = len(plan_domains[i])
                if chosen < 0 or degree < chosen_degree or (degree == chosen_degree and size < chosen_size):
                    chosen = i
                    chosen_degree = degree
                    chosen_size = size

            if chosen < 0:
                # No unassigned variables. We've got a solution. Go back
                # to last variable, if there's one.
                yield assignments.copy()
                if not queue:
                    return
                i, values, pushdomains = queue.pop()
                variable = names[i]
                if pushdomains:
                    for domain in pushdomains:
                        domain.popState()
            else:
                i = chosen
                variable = names[i]
                values = plan_domains[i][:]
                if forwardcheck:
                    # OPTIMIZATION: only the domains this variable can actually write to
                    # are pushed/popped.  Every constraint of `variable` only hides values
                    # in the domains of the variables it is declared on, so pushing the
                    # whole (unassigned) domain list - as the original did - is wasted work.
                    pushdomains = [plan_domains[j] for j in neighbours[i] if not taken[j]]
                else:
                    pushdomains = None
                taken[i] = True

            while True:
                # We have a variable. Do we have any values left?
                if not values:
                    # No. Go back to last variable, if there's one.
                    del assignments[variable]
                    taken[i] = False
                    while queue:
                        i, values, pushdomains = queue.pop()
                        variable = names[i]
                        if pushdomains:
                            for domain in pushdomains:
                                domain.popState()
                        if values:
                            break
                        del assignments[variable]
                        taken[i] = False
                    else:
                        return

                # Got a value. Check it.
                assignments[variable] = values.pop()

                if pushdomains:
                    for domain in pushdomains:
                        domain.pushState()

                for constraint, variables in vconstraints[variable]:
                    if not constraint(variables, domains, assignments, pushdomains):
                        # Value is not good.
                        break
                else:
                    break

                if pushdomains:
                    for domain in pushdomains:
                        domain.popState()

            # Push state before looking for next variable.
            queue.append((i, values, pushdomains))

        raise RuntimeError("Can't happen")

    def getSolution(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        iter = self.getSolutionIter(domains, constraints, vconstraints)
        try:
            return next(iter)
        except StopIteration:
            return None

    def getSolutions(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        return list(self.getSolutionIter(domains, constraints, vconstraints))


class OptimizedBacktrackingSolver(Solver):
    """Problem solver with backtracking capabilities, implementing several optimizations for increased performance.

    Optimizations are especially in obtaining all solutions.
    View https://github.com/python-constraint/python-constraint/pull/76 for more details.

    Examples:
        >>> result = [[('a', 1), ('b', 2)],
        ...           [('a', 1), ('b', 3)],
        ...           [('a', 2), ('b', 3)]]

        >>> problem = Problem(OptimizedBacktrackingSolver())
        >>> problem.addVariables(["a", "b"], [1, 2, 3])
        >>> problem.addConstraint(lambda a, b: b > a, ["a", "b"])

        >>> solution = problem.getSolution()
        >>> sorted(solution.items()) in result
        True

        >>> for solution in problem.getSolutionIter():
        ...     sorted(solution.items()) in result
        True
        True
        True

        >>> for solution in problem.getSolutions():
        ...     sorted(solution.items()) in result
        True
        True
        True
    """

    def __init__(self, forwardcheck=True, dynamic_mrv=True, restricted_pushdomains=True):
        """Initialization method.

        Args:
            forwardcheck (bool): If false forward checking will not be
                requested to constraints while looking for solutions
                (default is true)
            dynamic_mrv (bool): Re-evaluate the Minimum Remaining Values
                heuristic at every node using the *current* (forward-checked)
                domain sizes instead of only once at the start of the search
                (default is true).  Set to false to restore the previous static
                ordering.
            restricted_pushdomains (bool): Only save/restore the domains of the
                variables that share a constraint with the variable being
                assigned, instead of every unassigned domain (default is true).
                This is valid for every constraint shipped with this package
                (a constraint only ever hides values in the domains of the
                variables it is declared on); set to false if you use a custom
                :py:class:`~constraint.constraints.Constraint` that hides values
                in the domain of a variable it is not declared on.
        """
        self._forwardcheck = forwardcheck
        self._dynamic_mrv = dynamic_mrv
        self._restricted_pushdomains = restricted_pushdomains

    def getSolutionIter(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        forwardcheck = self._forwardcheck
        assignments = {}

        # OPTIMIZATION: build the static tie-breaking order and the constraint
        # neighbourhood table once instead of re-scanning the domain dict per node.
        plan = SearchPlan(domains, vconstraints)
        names = plan.names
        plan_domains = plan.domains
        degrees = plan.degrees
        neighbours = plan.neighbours
        taken = [False] * len(names)
        dynamic_mrv = self._dynamic_mrv
        restricted = self._restricted_pushdomains

        queue = []

        while True:
            # Mix the Degree and Minimum Remaing Values (MRV) heuristics.
            if dynamic_mrv:
                # OPTIMIZATION: true ("dynamic") MRV - the domain sizes used by the
                # heuristic are the *current* ones, so the search keeps adapting to the
                # values forward checking has hidden.  The cost is a single O(#unassigned)
                # scan with no allocation and no sort, which is cheaper than the static
                # scan it replaces once the saved nodes are taken into account.
                chosen = -1
                chosen_degree = 0
                chosen_size = 0
                for i, is_taken in enumerate(taken):
                    if is_taken:
                        continue
                    degree = degrees[i]
                    size = len(plan_domains[i])
                    if chosen < 0 or degree < chosen_degree or (degree == chosen_degree and size < chosen_size):
                        chosen = i
                        chosen_degree = degree
                        chosen_size = size
            else:
                # Legacy behaviour: always take the first unassigned variable of the
                # order computed once at the start of the search.
                chosen = -1
                for i, is_taken in enumerate(taken):
                    if not is_taken:
                        chosen = i
                        break

            if chosen < 0:
                # No unassigned variables. We've got a solution. Go back
                # to last variable, if there's one.
                yield assignments.copy()
                if not queue:
                    return
                i, values, pushdomains = queue.pop()
                variable = names[i]
                if pushdomains:
                    for domain in pushdomains:
                        domain.popState()
            else:
                i = chosen
                variable = names[i]
                values = plan_domains[i][:]
                if forwardcheck:
                    if restricted:
                        # OPTIMIZATION: only push/pop the domains that the constraints of
                        # this variable can hide values in (its constraint neighbours),
                        # instead of every unassigned domain.
                        pushdomains = [plan_domains[j] for j in neighbours[i] if not taken[j]]
                    else:
                        pushdomains = [plan_domains[j] for j in range(len(names)) if not taken[j] and j != i]
                else:
                    pushdomains = None
                taken[i] = True

            while True:
                # We have a variable. Do we have any values left?
                if not values:
                    # No. Go back to last variable, if there's one.
                    del assignments[variable]
                    taken[i] = False
                    while queue:
                        i, values, pushdomains = queue.pop()
                        variable = names[i]
                        if pushdomains:
                            for domain in pushdomains:
                                domain.popState()
                        if values:
                            break
                        del assignments[variable]
                        taken[i] = False
                    else:
                        return

                # Got a value. Check it.
                assignments[variable] = values.pop()

                if pushdomains:
                    for domain in pushdomains:
                        domain.pushState()

                for constraint, variables in vconstraints[variable]:
                    if not constraint(variables, domains, assignments, pushdomains):
                        # Value is not good.
                        break
                else:
                    break

                if pushdomains:
                    for domain in pushdomains:
                        domain.popState()

            # Push state before looking for next variable.
            queue.append((i, values, pushdomains))

        raise RuntimeError("Can't happen")

    def getSolutionsList(self, domains: dict[Hashable, Domain], vconstraints: dict[Hashable, list[tuple[Constraint, Hashable]]]) -> list[dict[Hashable, any]]:  # noqa: D102, E501
        """Optimized all-solutions finder that skips forwardchecking and returns the solutions in a list.

        Args:
            domains: Dictionary mapping variables to domains
            vconstraints: Dictionary mapping variables to a list of constraints affecting the given variables.

        Returns:
            the list of solutions as a dictionary.
        """
        # Does not do forwardcheck for simplicity

        assignments: dict = {}
        queue: list[tuple] = []
        solutions: list[dict] = list()
        sorted_variables = self.getSortedVariables(domains, vconstraints)

        while True:
            # Mix the Degree and Minimum Remaing Values (MRV) heuristics
            for variable in sorted_variables:
                if variable not in assignments:
                    # Found unassigned variable
                    values = domains[variable][:]
                    break
            else:
                # No unassigned variables. We've got a solution. Go back
                # to last variable, if there's one.
                solutions.append(assignments.copy())
                if not queue:
                    return solutions
                variable, values = queue.pop()

            while True:
                # We have a variable. Do we have any values left?
                if not values:
                    # No. Go back to last variable, if there's one.
                    del assignments[variable]
                    while queue:
                        variable, values = queue.pop()
                        if values:
                            break
                        del assignments[variable]
                    else:
                        return solutions

                # Got a value. Check it.
                assignments[variable] = values.pop()
                for constraint, variables in vconstraints[variable]:
                    if not constraint(variables, domains, assignments, None):
                        # Value is not good.
                        break
                else:
                    break

            # Push state before looking for next variable.
            queue.append((variable, values))

    def getSolutions(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        if self._forwardcheck:
            return list(self.getSolutionIter(domains, constraints, vconstraints))
        return self.getSolutionsList(domains, vconstraints)

    def getSolution(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        iter = self.getSolutionIter(domains, constraints, vconstraints)
        try:
            return next(iter)
        except StopIteration:
            return None

    def getSortedVariables(self, domains: dict, vconstraints: dict) -> list:
        """Sorts the list of variables on number of vconstraints to find unassigned variables quicker.

        Args:
            domains: Dictionary mapping variables to their domains
            vconstraints: Dictionary mapping variables to a list
                of constraints affecting the given variables.

        Returns:
            the list of variables, sorted from highest number of vconstraints to lowest.
        """
        lst = [(-len(vconstraints[variable]), len(domains[variable]), variable) for variable in domains]
        lst.sort(key=lambda x: (x[0], x[1]))
        return [c for _, _, c in lst]

class RecursiveBacktrackingSolver(Solver):
    """Recursive problem solver with backtracking capabilities.

    Examples:
        >>> result = [[('a', 1), ('b', 2)],
        ...           [('a', 1), ('b', 3)],
        ...           [('a', 2), ('b', 3)]]

        >>> problem = Problem(RecursiveBacktrackingSolver())
        >>> problem.addVariables(["a", "b"], [1, 2, 3])
        >>> problem.addConstraint(lambda a, b: b > a, ["a", "b"])

        >>> solution = problem.getSolution()
        >>> sorted(solution.items()) in result
        True

        >>> for solution in problem.getSolutions():
        ...     sorted(solution.items()) in result
        True
        True
        True

        >>> problem.getSolutionIter()
        Traceback (most recent call last):
        ...
        NotImplementedError: RecursiveBacktrackingSolver doesn't provide iteration
    """

    def __init__(self, forwardcheck=True, restricted_pushdomains=True):
        """Initialization method.

        Args:
            forwardcheck (bool): If false forward checking will not be
                requested to constraints while looking for solutions
                (default is true)
            restricted_pushdomains (bool): Only save/restore the domains of the
                variables that share a constraint with the variable being
                assigned (default is true).  See
                :py:class:`OptimizedBacktrackingSolver` for the exact assumption.
        """
        self._forwardcheck = forwardcheck
        self._restricted_pushdomains = restricted_pushdomains

    def recursiveBacktracking(self, solutions, domains, vconstraints, assignments, single, plan=None):
        """Mix the Degree and Minimum Remaing Values (MRV) heuristics.

        Args:
            solutions: _description_
            domains: _description_
            vconstraints: _description_
            assignments: _description_
            single: _description_
            plan: optional pre-built :py:class:`SearchPlan` (built on the first call
                and reused by the recursive calls)

        Returns:
            _description_
        """
        # OPTIMIZATION: the heuristic order and the constraint neighbourhood table are
        # static, so they are built once per solve instead of being rebuilt and
        # re-sorted at every node.
        if plan is None:
            plan = SearchPlan(domains, vconstraints)
        names = plan.names
        plan_domains = plan.domains
        degrees = plan.degrees
        neighbours = plan.neighbours

        # OPTIMIZATION: single allocation-free scan instead of "build tuples + sort".
        chosen = -1
        chosen_degree = 0
        chosen_size = 0
        for i, name in enumerate(names):
            if name in assignments:
                continue
            degree = degrees[i]
            size = len(plan_domains[i])
            if chosen < 0 or degree < chosen_degree or (degree == chosen_degree and size < chosen_size):
                chosen = i
                chosen_degree = degree
                chosen_size = size

        if chosen < 0:
            # No unassigned variables. We've got a solution.
            solutions.append(assignments.copy())
            return solutions

        variable = names[chosen]
        assignments[variable] = None

        forwardcheck = self._forwardcheck
        if forwardcheck:
            if self._restricted_pushdomains:
                # OPTIMIZATION: only the domains this variable shares a constraint with.
                pushdomains = [plan_domains[j] for j in neighbours[chosen] if names[j] not in assignments]
            else:
                pushdomains = [plan_domains[j] for j in range(len(names)) if names[j] not in assignments]
        else:
            pushdomains = None

        for value in plan_domains[chosen]:
            assignments[variable] = value
            if pushdomains:
                for domain in pushdomains:
                    domain.pushState()
            for constraint, variables in vconstraints[variable]:
                if not constraint(variables, domains, assignments, pushdomains):
                    # Value is not good.
                    break
            else:
                # Value is good. Recurse and get next variable.
                self.recursiveBacktracking(solutions, domains, vconstraints, assignments, single, plan)
                if solutions and single:
                    return solutions
            if pushdomains:
                for domain in pushdomains:
                    domain.popState()
        del assignments[variable]
        return solutions

    def getSolution(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        plan = SearchPlan(domains, vconstraints)
        solutions = self.recursiveBacktracking([], domains, vconstraints, {}, True, plan)
        return solutions and solutions[0] or None

    def getSolutions(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        plan = SearchPlan(domains, vconstraints)
        return self.recursiveBacktracking([], domains, vconstraints, {}, False, plan)


class MinConflictsSolver(Solver):
    """Problem solver based on the minimum conflicts theory.

    Examples:
        >>> result = [[('a', 1), ('b', 2)],
        ...           [('a', 1), ('b', 3)],
        ...           [('a', 2), ('b', 3)]]

        >>> problem = Problem(MinConflictsSolver())
        >>> problem.addVariables(["a", "b"], [1, 2, 3])
        >>> problem.addConstraint(lambda a, b: b > a, ["a", "b"])

        >>> solution = problem.getSolution()
        >>> sorted(solution.items()) in result
        True

        >>> problem.getSolutions()
        Traceback (most recent call last):
        ...
        NotImplementedError: MinConflictsSolver provides only a single solution

        >>> problem.getSolutionIter()
        Traceback (most recent call last):
        ...
        NotImplementedError: MinConflictsSolver doesn't provide iteration
    """

    def __init__(self, steps=1000, rand=None):
        """Initialization method.

        Args:
            steps (int): Maximum number of steps to perform before
                giving up when looking for a solution (default is 1000)
            rand (Random): Optional random.Random instance to use for
                repeatability.
        """
        self._steps = steps
        self._rand = rand

    def getSolution(self, domains: dict, constraints: list[tuple], vconstraints: dict):   # noqa: D102
        choice = self._rand.choice if self._rand is not None else random.choice
        shuffle = self._rand.shuffle if self._rand is not None else random.shuffle
        assignments = {}
        # Initial assignment
        for variable in domains:
            assignments[variable] = choice(domains[variable])
        for _ in range(self._steps):
            conflicted = False
            lst = list(domains.keys())
            shuffle(lst)
            for variable in lst:
                # Check if variable is not in conflict
                for constraint, variables in vconstraints[variable]:
                    if not constraint(variables, domains, assignments):
                        break
                else:
                    continue
                # Variable has conflicts. Find values with less conflicts.
                mincount = len(vconstraints[variable])
                minvalues = []
                for value in domains[variable]:
                    assignments[variable] = value
                    count = 0
                    for constraint, variables in vconstraints[variable]:
                        if not constraint(variables, domains, assignments):
                            count += 1
                    if count == mincount:
                        minvalues.append(value)
                    elif count < mincount:
                        mincount = count
                        del minvalues[:]
                        minvalues.append(value)
                # Pick a random one from these values.
                assignments[variable] = choice(minvalues)
                conflicted = True
            if not conflicted:
                return assignments
        return None
    

class ParallelSolver(Solver):
    """Problem solver that executes all-solution solve in parallel (ProcessPool or ThreadPool mode).

        Sorts the domains on size, creating jobs for each value in the domain with the most variables.
        Each leaf job is solved locally with either optimized backtracking or recursion.
        Whether this is actually faster than non-parallel solving depends on your problem, and hardware and software environment. 

        Uses ThreadPool by default. Instantiate with process_mode=True to use ProcessPool. 
        In ProcessPool mode, the jobs do not share memory.
        In ProcessPool mode, precompiled FunctionConstraints are not allowed due to pickling, use string constraints instead.

    Examples:
        >>> result = [[('a', 1), ('b', 2)],
        ...           [('a', 1), ('b', 3)],
        ...           [('a', 2), ('b', 3)]]

        >>> problem = Problem(ParallelSolver())
        >>> problem.addVariables(["a", "b"], [1, 2, 3])
        >>> problem.addConstraint("b > a", ["a", "b"])

        >>> for solution in problem.getSolutions():
        ...     sorted(solution.items()) in result
        True
        True
        True

        >>> problem.getSolution()
        Traceback (most recent call last):
        ...
        NotImplementedError: ParallelSolver only provides all solutions

        >>> problem.getSolutionIter()
        Traceback (most recent call last):
        ...
        NotImplementedError: ParallelSolver doesn't provide iteration
    """     # noqa E501

    def __init__(self, process_mode=False):
        """Initialization method. Set `process_mode` to True for using ProcessPool, otherwise uses ThreadPool."""
        super().__init__()
        self._process_mode = process_mode
        self.requires_pickling = process_mode

    def getSolution(self, domains: dict, constraints: list[tuple], vconstraints: dict):
        """Return one solution for the given problem.

        Args:
            domains (dict): Dictionary mapping variables to their domains
            constraints (list): List of pairs of (constraint, variables)
            vconstraints (dict): Dictionary mapping variables to a list
                of constraints affecting the given variables.
        """
        msg = f"{self.__class__.__name__} only provides all solutions"
        raise NotImplementedError(msg)

    def getSolutionsList(self, domains: dict[Hashable, Domain], vconstraints: dict[Hashable, list[tuple[Constraint, Hashable]]]) -> list[dict[Hashable, any]]:  # noqa: D102, E501
        """Parallelized all-solutions finder using ProcessPoolExecutor for work-stealing."""
        # Precompute constraints lookup per variable
        constraint_lookup: dict[Hashable, list[tuple[Constraint, Hashable]]] = {var: vconstraints.get(var, []) for var in domains}  # noqa: E501

        # Sort variables by domain size (heuristic)
        sorted_vars: list[Hashable] = sorted(domains.keys(), key=lambda v: len(domains[v]))

        # Split parallel and sequential parts
        first_var = sorted_vars[0]
        remaining_vars = sorted_vars[1:]

        # Create the parallel function arguments and solutions lists
        args = ((self.requires_pickling, domains, constraint_lookup, first_var, val, remaining_vars.copy()) for val in domains[first_var])  # noqa: E501
        solutions: list[dict[Hashable, any]] = []

        # execute in parallel
        parallel_pool = ProcessPoolExecutor if self._process_mode else ThreadPoolExecutor
        with parallel_pool() as executor:
            # results = map(parallel_worker, args)  # sequential
            results = executor.map(parallel_worker, args, chunksize=1)   # parallel
            for result in results:
                solutions.extend(result)

        return solutions
    
    def getSolutions(self, domains: dict, constraints: list[tuple], vconstraints: dict):  # noqa: D102
        return self.getSolutionsList(domains, vconstraints)

### Helper functions for parallel solver

def is_valid(assignment: dict[Hashable, any], constraints_lookup: list[tuple[Constraint, Hashable]], domains: dict[Hashable, Domain]) -> bool:      # noqa E501
    """Check if all constraints are satisfied given the current assignment."""
    return all(
        constraint(vars_involved, domains, assignment, None)
        for constraint, vars_involved in constraints_lookup
        if all(v in assignment for v in vars_involved)
    )

def compile_to_function(constraint: CompilableFunctionConstraint) -> FunctionConstraint:
    """Compile a CompilableFunctionConstraint to a function, wrapped by a FunctionConstraint."""
    func_string = constraint._func
    code_object = compile(func_string, "<string>", "exec")
    func = FunctionType(code_object.co_consts[0], globals())
    return FunctionConstraint(func)
    
def sequential_recursive_backtrack(assignment: dict[Hashable, any], unassigned_vars: list[Hashable], domains: dict[Hashable, Domain], constraint_lookup: dict[Hashable, list[tuple[Constraint, Hashable]]]) -> list[dict[Hashable, any]]:     # noqa E501
    """Sequential recursive backtracking function for subproblems."""
    if not unassigned_vars:
        return [assignment.copy()]

    var = unassigned_vars[-1]
    remaining_vars = unassigned_vars[:-1]

    solutions: list[dict[Hashable, any]] = []
    for value in domains[var]:
        assignment[var] = value
        if is_valid(assignment, constraint_lookup[var], domains):
            solutions.extend(sequential_recursive_backtrack(assignment, remaining_vars, domains, constraint_lookup))
        del assignment[var]
    return solutions

def sequential_optimized_backtrack(assignment: dict[Hashable, any], unassigned_vars: list[Hashable], domains: dict[Hashable, Domain], constraint_lookup: dict[Hashable, list[tuple[Constraint, Hashable]]]) -> list[dict[Hashable, any]]:     # noqa E501
    """Sequential optimized backtracking (as in OptimizedBacktrackingSolver) function for subproblems."""
    # Does not do forwardcheck for simplicity

    assignments = assignment
    sorted_variables = unassigned_vars
    queue: list[tuple] = []
    solutions: list[dict] = list()

    while True:
        # Mix the Degree and Minimum Remaing Values (MRV) heuristics
        for variable in sorted_variables:
            if variable not in assignments:
                # Found unassigned variable
                values = domains[variable][:]
                break
        else:
            # No unassigned variables. We've got a solution. Go back
            # to last variable, if there's one.
            solutions.append(assignments.copy())
            if not queue:
                return solutions
            variable, values = queue.pop()

        while True:
            # We have a variable. Do we have any values left?
            if not values:
                # No. Go back to last variable, if there's one.
                del assignments[variable]
                while queue:
                    variable, values = queue.pop()
                    if values:
                        break
                    del assignments[variable]
                else:
                    return solutions

            # Got a value. Check it.
            assignments[variable] = values.pop()
            for constraint, variables in constraint_lookup[variable]:
                if not constraint(variables, domains, assignments, None):
                    # Value is not good.
                    break
            else:
                break

        # Push state before looking for next variable.
        queue.append((variable, values))


def parallel_worker(args: tuple[bool, dict[Hashable, Domain], dict[Hashable, list[tuple[Constraint, Hashable]]], Hashable, any, list[Hashable]]) -> list[dict[Hashable, any]]:    # noqa E501
    """Worker function for parallel execution on first variable."""
    process_mode, domains, constraint_lookup, first_var, first_value, remaining_vars = args
    local_assignment = {first_var: first_value}

    if process_mode:
        # if there are any CompilableFunctionConstraint, they must be compiled locally first
        for var, constraints in constraint_lookup.items():
            constraint_lookup[var] = [tuple([compile_to_function(constraint) if isinstance(constraint, CompilableFunctionConstraint) else constraint, vals]) for constraint, vals in constraints]        # noqa E501

    # continue solving sequentially on this process
    if is_valid(local_assignment, constraint_lookup[first_var], domains):
        return sequential_optimized_backtrack(local_assignment, remaining_vars, domains, constraint_lookup)
    return []
    
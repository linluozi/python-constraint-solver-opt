# NOTICE — modifications to python-constraint

This archive is a **modified** copy of
[python-constraint](https://github.com/python-constraint/python-constraint),
version 2.7.3, commit `d91ba03d1fd6acc30d64fd9d513dc0523f697b5b`.

Original copyright notice (retained in `LICENSE`, unmodified):

```
Copyright (c) 2005-2014 - Gustavo Niemeyer <gustavo@niemeyer.net>
```

Additional copyright holders and contributors are listed in `CONTRIBUTORS.md`
and `pyproject.toml`, both reproduced unchanged from upstream.

The original project is licensed under the **BSD 2-Clause License**. Redistribution
of this modified version is permitted under the same terms, provided the
copyright notice, the list of conditions and the disclaimer are retained (they
are — `LICENSE` is byte-identical to upstream) and provided that neither the name
of the copyright holder nor the names of its contributors are used to endorse or
promote this modified version (they are not).

## Summary of modifications

All modifications are in `constraint/solvers.py`, plus one added test file and the
`bench/` directory. Files added or changed relative to upstream 2.7.3:

| path | status |
|---|---|
| `constraint/solvers.py` | **modified** — solver search loop (`SearchPlan`, dynamic MRV, restricted push domains) |
| `constraint/constraints.py` | **modified** — three empty-domain guards in the sum constraints (crash fix, see below) |
| `tests/test_solver_optimizations.py` | added |
| `bench/` | added (benchmark harness, raw results, figure and page generators) |
| `index.html` | added — single-file reading page served by GitHub Pages |
| `.github/workflows/publish-documentation.yml` | **modified** — automatic Sphinx deployment disabled, because GitHub Pages serves this report instead |
| `.github/workflows/build-test-python-package.yml` | **modified** — `bench/**` added to the path filter, `workflow_dispatch` enabled |
| `README.md` | added (this build's README; the upstream `README.rst` is kept) |
| `IMPROVEMENT_REPORT.md`, `BENCHMARKS.md`, `NOTICE.md` | added |
| `constraint/*.c` | **removed** — Cython-generated artifacts (`constraints.c`, `domain.c`, `parser.c`, `problem.c`, `solvers.c`), ~6.5 MB of generated code that no longer matches the modified Python sources |
| everything else | unchanged |

The removed `.c` files are build outputs of `cythonize_build.py`, not source; the
pure-Python package does not need them (see `check_if_compiled()` in
`constraint/domain.py`, which reports `False` and the code is written to work in
that case). Anyone who wants the Cython build can regenerate them from the
modified sources with `python cythonize_build.py`.

The package version string is left at `2.7.3` on purpose, so that it is obvious
which upstream release this is derived from. Do not report bugs in this modified
build to the upstream maintainers without first checking against a clean 2.7.3
checkout.

## What was NOT modified

* `constraint/domain.py`, `constraint/parser.py`, `constraint/problem.py`,
  `constraint/__init__.py` — byte-identical.
* `examples/`, `docs/`, `tests/` (except the added file) — byte-identical.

## What else was modified

* `constraint/constraints.py` — **three empty-domain guards** in
  `ExactSumConstraint.preProcess`, `MinSumConstraint.preProcess` and
  `MaxSumConstraint.preProcess`. Upstream calls `min()`/`max()` on a domain that
  can already be empty when the same `Problem` is solved twice, which raises
  `ValueError`; the guards follow the convention the file already used a few
  lines below each site. Nothing else in this file changed. See
  `IMPROVEMENT_REPORT.md` §6.

Modification date: 2026-10-18.

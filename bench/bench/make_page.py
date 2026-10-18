"""Build a single-file HTML reading page for the report.

Everything except the two PNGs is inlined (no external CSS/JS/fonts), and the
figures are referenced relatively so they keep working on GitHub Pages.

    python bench/make_page.py

Output: index.html
"""

from __future__ import annotations

import html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "index.html")

INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"
RULE = "#e2d8c8"


def load(name):
    """Load one raw measurement file from bench/results/."""
    with open(os.path.join(HERE, "results", name), encoding="utf-8") as fh:
        return json.load(fh)


def md_table(header, rows, align=None):  # noqa: D103
    """Render a small markdown-style table as HTML."""
    align = align or ["left"] + ["right"] * (len(header) - 1)
    out = ['<div class="tw"><table>', "<thead><tr>"]
    for cell, a in zip(header, align):
        out.append(f'<th class="{a}">{html.escape(str(cell))}</th>')
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            out.append(f'<td class="{align[i]}">{cell}</td>')
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def build_tables():  # noqa: D103
    ab = load("ab_default.json")["cases"]
    order = ["queens-20-first", "queens-16-first", "sudoku-hard-all", "microhh-small-all",
             "queens-10-all", "dedispersion-all", "queens-8-all", "hotspot-all"]

    rows = []
    for case in order:
        e = ab[case]
        a_ms = e["a_median_s"] / e["repeats"] * 1000
        b_ms = e["b_median_s"] / e["repeats"] * 1000
        ratio = e["ratio_median"]
        hot = ratio >= 10
        ratio_html = f'<b class="hot">{ratio:,.0f}&times;</b>' if hot else f'<b>{ratio:.2f}&times;</b>'
        rows.append([
            f"<code>{case}</code>",
            f"{a_ms:,.1f} ms",
            f"{b_ms:,.1f} ms",
            ratio_html,
            f"{e['ratio_min']:.2f}&ndash;{e['ratio_max']:.2f}&times;",
            f"{e['b_faster_rounds']}/{e['rounds']}",
        ])
    time_table = md_table(["case", "upstream", "this build", "speed-up", "range over rounds", "B faster in"], rows)

    # deterministic constraint invocations
    def read_counts(path):
        out = {}
        with open(os.path.join(HERE, "results", path), encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"(\S+)\s+sols=\s*(\d+)\s+calls=\s*(\d+)", line)
                if m:
                    out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        return out

    base = read_counts("deterministic_upstream.txt")
    opt = read_counts("deterministic_opt.txt")
    rows = []
    for case in order:
        if case not in base or case not in opt:
            continue
        sols, b_calls = base[case]
        _, o_calls = opt[case]
        red = b_calls / o_calls
        red_html = f'<b class="hot">{red:,.0f}&times;</b>' if red >= 10 else f"<b>{red:.2f}&times;</b>"
        rows.append([f"<code>{case}</code>", f"{sols:,}", f"{b_calls:,}", f"{o_calls:,}", red_html])
    calls_table = md_table(["case", "solutions", "invocations upstream", "invocations this build", "reduction"], rows)

    # ablation
    abl = load("ablation.json")["cases"]
    aorder = ["sudoku-hard-all", "queens-20-first", "queens-11-all",
              "hotspot-all", "microhh-small-all", "dedispersion-all"]
    rows = []
    for case in aorder:
        arms = abl[case]["arms"]
        cells = [f"<code>{case}</code>"]
        for arm in ("legacy", "mrv", "scope", "both"):
            v = arms[arm]["speedup_median"]
            if arm == "legacy":
                cells.append('<span class="dim">1.00&times;</span>')
            elif v < 1.0:
                cells.append(f'<b class="slow">{v:.2f}&times;</b>')
            elif v >= 10:
                cells.append(f'<b class="hot">{v:,.0f}&times;</b>')
            else:
                cells.append(f"<b>{v:.2f}&times;</b>")
        rows.append(cells)
    abl_table = md_table(
        ["case", "both off (upstream)", "dynamic MRV only",
         "restricted push only", "both (new default)"],
        rows,
    )
    return time_table, calls_table, abl_table


CSS = f"""
:root {{
  --ink: {INK}; --paper: {PAPER}; --amber: {AMBER}; --terra: {TERRACOTTA};
  --olive: {OLIVE}; --muted: {MUTED}; --rule: {RULE};
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; background: var(--paper); color: var(--ink);
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Songti SC", serif;
  font-size: 17px; line-height: 1.68;
  -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 900px; margin: 0 auto; padding: 0 26px 120px; }}
header.hero {{ padding: 74px 0 40px; border-bottom: 2px solid var(--ink); }}
.kicker {{
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 11.5px; letter-spacing: .18em; text-transform: uppercase;
  color: var(--terra); margin-bottom: 18px;
}}
h1 {{ font-size: clamp(30px, 4.6vw, 46px); line-height: 1.14; margin: 0 0 18px; letter-spacing: -.015em; }}
.sub {{ font-size: 19px; color: #5c4d3e; margin: 0 0 26px; max-width: 46ch; }}
.metaline {{
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px;
  color: var(--muted); display: flex; flex-wrap: wrap; gap: 8px 22px;
}}
.metaline a {{ color: var(--terra); text-decoration: none; border-bottom: 1px solid rgba(180,85,47,.35); }}
.hstats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 1px; background: var(--rule); margin: 38px 0 0; }}
.hstat {{ background: var(--paper); padding: 16px 14px; }}
.hstat .n {{ font-size: 27px; font-weight: 700; letter-spacing: -.02em; display: block; line-height: 1.1; }}
.hstat .l {{ font-size: 12px; color: var(--muted); font-family: ui-monospace, Menlo, monospace; }}
h2 {{
  font-size: 24px; margin: 62px 0 6px; letter-spacing: -.01em;
  padding-top: 20px; border-top: 1px solid var(--rule);
}}
h2 .num {{ color: var(--amber); font-family: ui-monospace, Menlo, monospace; font-size: 15px; margin-right: 10px; }}
h3 {{ font-size: 17.5px; margin: 34px 0 4px; }}
p {{ margin: 12px 0; }}
p, li, td, th {{ overflow-wrap: anywhere; }}
.sub {{ max-width: 52ch; }}
.lead {{ font-size: 18.5px; }}
strong {{ font-weight: 650; }}
code {{
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: .855em; background: #f0e8da; padding: 1.5px 5px; border-radius: 3px;
}}
pre {{
  background: #241c15; color: #ede3d2; padding: 18px 20px; border-radius: 4px;
  overflow-x: auto; font-size: 13px; line-height: 1.55;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}}
pre code {{ background: none; padding: 0; color: inherit; font-size: inherit; }}
figure {{ margin: 30px 0 10px; }}
figure img {{ width: 100%; height: auto; display: block; border: 1px solid var(--rule); background: #fff; }}
figcaption {{ font-size: 13px; color: var(--muted); margin-top: 9px; line-height: 1.5; }}
.tw {{ overflow-x: auto; margin: 22px 0 6px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ padding: 8px 11px; border-bottom: 1px solid var(--rule); }}
th {{ font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted);
      font-family: ui-monospace, Menlo, monospace; font-weight: 600; border-bottom: 1.5px solid var(--ink); }}
td.right, th.right {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.left, th.left {{ text-align: left; }}
tbody tr:hover {{ background: #f4ecdf; }}
.hot {{ color: var(--terra); }}
.slow {{ color: var(--olive); }}
.dim {{ color: var(--muted); }}
.note {{
  border-left: 3px solid var(--amber); padding: 4px 0 4px 18px; margin: 26px 0;
  color: #54463a; font-size: 15.5px;
}}
.note.warn {{ border-color: var(--terra); }}
.note b {{ color: var(--ink); }}
ul {{ padding-left: 22px; }} li {{ margin: 7px 0; }}
.split {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
         gap: 18px; margin: 24px 0; align-items: stretch; }}
.card {{ border: 1px solid var(--rule); padding: 16px 18px; background: #fdf9f3; }}
.card h4 {{ margin: 0 0 8px; font-size: 14px; font-family: ui-monospace, Menlo, monospace;
            letter-spacing: .06em; text-transform: uppercase; color: var(--terra); }}
footer {{ margin-top: 70px; padding-top: 22px; border-top: 2px solid var(--ink);
          font-size: 13px; color: var(--muted); }}
@media (max-width: 720px) {{
  .hstats {{ grid-template-columns: repeat(2, 1fr); }}
  .split {{ grid-template-columns: 1fr; }}
  body {{ font-size: 16px; }}
}}
"""


def main():
    """Write index.html."""
    time_table, calls_table, abl_table = build_tables()

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>python-constraint — solver speed-up report</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <div class="kicker">Algorithm improvement &middot; CSP backtracking</div>
  <h1>python-constraint: an index-based search plan, real MRV, and scoped forward checking</h1>
  <p class="sub">Three inefficiencies in the default solver&rsquo;s search loop, measured against
  upstream 2.7.3 with an interleaved A/B harness. Same API, same solution sets.</p>
  <div class="metaline">
    <span>upstream
      <a href="https://github.com/python-constraint/python-constraint">python-constraint 2.7.3</a>
      @ <code>d91ba03</code></span>
    <span>BSD-2-Clause</span>
    <span>pure Python &ge; 3.11</span>
    <span><a href="https://github.com/linluozi/python-constraint-solver-opt">source</a></span>
  </div>
  <div class="hstats">
    <div class="hstat"><span class="n">857&times;</span><span class="l">20-queens, first solution</span></div>
    <div class="hstat"><span class="n">43&times;</span><span class="l">hard sudoku</span></div>
    <div class="hstat"><span class="n">737&times;</span><span class="l">fewer constraint calls</span></div>
    <div class="hstat"><span class="n">1.00&times;</span><span class="l">solution sets unchanged</span></div>
  </div>
</header>

<h2><span class="num">01</span>The problem in the original loop</h2>

<p class="lead">The default solver, <code>OptimizedBacktrackingSolver</code>, is an iterative
depth-first search. Every node runs this:</p>

<pre><code># pick the next variable
lst = [(-len(vconstraints[v]), len(domains[v]), v) for v in domains]
lst.sort(key=lambda x: (x[0], x[1]))
for item in lst:
    if item[-1] not in assignments:   # first unassigned in that order
        variable = item[-1]
        values = domains[variable][:]
        if forwardcheck:
            pushdomains = [domains[x] for x in domains
                           if x not in assignments and x != variable]
        break</code></pre>

<p>Three things are wrong with those nine lines, and none of them is a style issue.</p>

<div class="split">
  <div class="card">
    <h4>1 &middot; rebuilt every node</h4>
    <p style="margin:6px 0">The list of <i>n</i> tuples is rebuilt and re-sorted on <b>every</b>
    node &mdash; after each failed value, not just after each assignment. Everything in it except
    the domain sizes is static for the whole search.</p>
  </div>
  <div class="card">
    <h4>2 &middot; MRV is frozen</h4>
    <p style="margin:6px 0"><code>len(domains[v])</code> is the size <b>at the root</b>.
    Forward checking shrinks domains as the search descends, but the heuristic never
    reads them again &mdash; so &ldquo;minimum remaining values&rdquo; degrades into a
    static tie-breaker.</p>
  </div>
  <div class="card">
    <h4>3 &middot; pushing every domain</h4>
    <p style="margin:6px 0">Assigning one variable pushes a state onto <b>every</b> unassigned
    domain, although a constraint can only hide values in the domains of its own variables.
    On a sparse constraint graph that is O(V) wasted work per assignment.</p>
  </div>
</div>

<p>The consequence is measurable rather than theoretical: on 20-queens the upstream search
performs <b>4,902,182</b> constraint invocations to find one solution, because it keeps
walking a stale order while some other variable has already been pruned to a single value.
On the classic hard sudoku it is <b>1,916,096</b>.</p>

<h2><span class="num">02</span>What was changed</h2>

<p>All of the algorithmic work is in <code>constraint/solvers.py</code>. A
<code>SearchPlan</code> is built once per solve (variable order, degrees,
constraint-neighbour table, index map); the per-node heuristic becomes a single
allocation-free scan over a <code>taken</code> bitmap that reads the <i>live</i> domain
sizes; and forward checking only pushes the domains of the current variable&rsquo;s
constraint neighbours.</p>

<p>Both switches are on the constructor, so the old behaviour can be restored exactly:</p>

<pre><code>OptimizedBacktrackingSolver(
    dynamic_mrv=False,
    restricted_pushdomains=False,
)  # == upstream 2.7.3</code></pre>

<div class="note"><b>Why they stay separate.</b> The ablation below shows the two changes are
not interchangeable: dynamic MRV produces the orders of magnitude but is a <i>net loss</i> on
pure enumeration, while the restricted push list is what pays exactly there. Wiring either one
in unconditionally would have made some workloads slower.</div>

<h2><span class="num">03</span>Measured result</h2>

<figure>
  <img src="docs/assets/speedup.png" alt="Speed-up per benchmark case">
  <figcaption>Orange = the win comes from visiting fewer nodes; amber = the search tree is
  already tight, so the win is only cheaper nodes. (The measurement footnote is printed inside
  the figure itself.)</figcaption>
</figure>

{time_table}

<p style="font-size:14px;color:#8a7a68">The 1.1&ndash;1.3&times; cases are the honest per-node
cost of the old loop. The two-order-of-magnitude numbers are search-tree reduction, not
micro-optimisation.</p>

<h3>The same effect, without any timing noise</h3>

<p>Constraint invocations are exact and machine-independent &mdash; this is the table to quote
when the question is &ldquo;did the algorithm get better, or did the code just get
faster&rdquo;.</p>

{calls_table}

<p><code>dedispersion</code> does exactly the same amount of search work (it is a pure
enumeration where the tree is already tight) and only gets faster from the removed per-node
overhead. <code>queens-20-first</code> does <b>737&times; less search</b>.</p>

<h2><span class="num">04</span>Ablation: which change is responsible</h2>

<figure>
  <img src="docs/assets/ablation.png" alt="Ablation over the two switches">
  <figcaption>All four arms are the same patched package; only the two constructor switches
  differ. Bars to the left of the axis are slower than the same build with both switches off.</figcaption>
</figure>

{abl_table}

<div class="note warn"><b>Including the uncomfortable parts.</b> Dynamic MRV is 0.83&times; on
<code>dedispersion</code> and 0.93&times; on <code>microhh</code> &mdash; on pure enumeration it
only costs time. And on <code>queens-11-all</code> the two changes partly cancel: MRV alone is
1.34&times;, both together 1.19&times;. Both are still ahead of upstream, and sudoku and
20-queens gain far more than that case loses, but it is the reason the switches are exposed
individually instead of hard-wired.</div>

<h2><span class="num">05</span>Correctness</h2>

<ul>
  <li>Upstream test suite: <b>76 passed, 1 skipped, 2 failed</b> &mdash; and the same two fail on
  the untouched upstream checkout here (<code>test_if_compiled</code> expects a Cython build;
  <code>test_versioning</code> imports <code>poetry</code>).</li>
  <li>29 new tests: solution-set equality against the &ldquo;both switches off&rdquo; configuration
  on n-queens, sudoku, <code>dedispersion</code>, sparse graphs, unary constraints, non-string
  variable keys, unsatisfiable problems and repeated solves.</li>
  <li>Every benchmark case asserts its solution count and aborts on a change, so a timing run can
  never compare two different searches.</li>
  <li>The project&rsquo;s own <code>ruff</code> configuration passes on the whole tree, including
  <code>bench/</code>.</li>
</ul>

<h3>A crash found on the way</h3>

<p><code>ExactSumConstraint</code>, <code>MinSumConstraint</code> and
<code>MaxSumConstraint</code> computed their initial bounds with
<code>min(domains[v])</code> without checking for an empty domain. <code>preProcess</code> runs on
every solve and its pruning is never undone, so solving the same <code>Problem</code> twice
raised <code>ValueError: min() iterable argument is empty</code> on the second call. Fixed with
the same guard the recalculation a few lines below each site already used, plus three regression
tests.</p>

<h2><span class="num">06</span>Limitations</h2>

<ul>
  <li>Pure Python only. The Cython <code>.c</code> artifacts were removed (generated, and no longer
  matching the modified sources); the relative gain would shrink in a compiled build, since the
  Python-level overhead removed here is what Cython already removes.</li>
  <li>No memory measurement was taken, so no memory claim is made.</li>
  <li><code>ParallelSolver</code> and <code>MinConflictsSolver</code> are untouched &mdash; the
  first is documented upstream as experimental, the second is local search without forward
  checking, where these changes do not apply.</li>
  <li>The first solution found may differ from upstream when dynamic MRV is on. The solution is
  still valid and the solution <i>set</i> is identical.</li>
</ul>

<footer>
  Baseline: python-constraint <code>d91ba03</code> (v2.7.3), BSD-2-Clause, original copyright
  retained. Modified build &copy; 2026, same licence. Full method, raw JSON and the patch are in
  the repository; <code>bench/make_figures.py</code> regenerates both figures from the data.
</footer>

</div>
</body>
</html>
"""

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()

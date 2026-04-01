# Math Lab v30 — Implementation TODO

Compiled from strategy session 2026-03-30.

---

## 1. GCT (Geometric Complexity Theory) Prompts
- Add Mulmuley's GCT framework to conjecture engine prompt set
- Different attack vector from current proof complexity focus
- Source: Grok comparison analysis

## 2. Heuristic Search Mode — SAT Ordering Strategies
New mode: `MODE = "heuristic_search"` — generate small SAT instances, test variable ordering strategies, measure backtrack rates, look for zero-backtrack classes.

### 2a. Backbone-First Ordering
- Identify backbone variables (fixed across all solutions) on small instances
- Set them first, measure if remaining formula becomes trivially solvable
- Empirical: count backtracks vs random ordering vs VSIDS

### 2b. Least-Frequent-First Ordering
- Order variables by minimum clause occurrence (opposite of VSIDS)
- Measure backtrack count on structured vs random instances
- Key question: does this produce ZERO backtracks on any identifiable class?
- If yes, that class is provably in P

### 2c. Endpoint Testing (Binary Search on Assignment Space)
- Check all-true and all-false assignments first
- Measure what structural info this gives about which variables to fix
- Explore binary-search-style narrowing on the assignment space

### Core Hypothesis ("Coffinhead Conjecture")
There exists a polynomial-time-computable variable ordering for any satisfiable SAT formula such that unit propagation from that ordering produces a satisfying assignment WITHOUT backtracking. If true → P=NP. If provably false → meaningful complexity result formalizing what makes SAT harder than sorting.

---

## 3. Coffinhead Conjecture — Full Research Summary

### Phase 1-3: Conjecture Testing
- Strong conjecture ("every satisfiable SAT has a zero-BT ordering"): FALSIFIED at n=6
- Refined conjecture (backbone<0.7, solutions>=4): FALSIFIED (~0.9% failure rate)
- Structured instances (pigeonhole, graph coloring): ALL have zero-BT orderings
- LFF "99% success rate" was artifact of planted/easy instances; true rate ~39% on random SAT

### Phase 4: LFF Failure Analysis
- Static LFF fails 61% on truly random SAT at realistic ratios
- Backtracks NEVER happen on the first decision — LFF gets the first pick right
- Failures concentrate at positions 2-3 in the ordering (71% of all backtracks)
- Root cause: LFF is STATIC — computes ordering once, but formula changes after each decision

### Phase 5: Adaptive Heuristics (KEY BREAKTHROUGH)
- Adaptive polarity: 91.2% zero-BT (vs 40.6% static LFF) — pick variable with most biased polarity, set to dominant value
- Jeroslow-Wang (1990): 80.3% zero-BT, scales best — barely degrades with problem size
  - n=6: 86%, avg 0.22 bt | n=10: 80%, avg 0.34 bt | n=20: 61%, avg 1.02 bt
  - vs static LFF at n=20: 12%, avg 17.73 bt (17x worse)
- Adaptive LFF is actually WORSE than static LFF — least-frequent is wrong after first decision
- The winning insight: not "which variable is least constrained" but "which variable has the most obvious correct value"

### Phase 6: The Hard Core (P≠NP EVIDENCE)

THE HARD CORE GROWS WITH N (ratio 4.0, near phase transition):
  n=6: 4% | n=10: 6% | n=15: 14.5% | n=20: 25% | n=25: 30% | n=30: 38%

At easy ratios (3.0), hard core stays ~1-3% and vanishes at n=25+.
Hard core peaks at ratio 4.4-4.7 — exactly the SAT phase transition.

THE HARD CORE HAS TWO LAYERS (brute-forced at n=7):
- 76%: zero-BT ordering EXISTS but no heuristic finds it (SEARCH problem)
- 24%: NO zero-BT ordering exists at all (STRUCTURAL barrier — backtracking unavoidable)

STRUCTURAL PROFILE of hard core:
- Backbone fraction 0.90 vs 0.46 easy (variables almost all forced)
- 1.4 solutions vs 5.6 easy (nearly unique solution)
- LOW polarity bias (no variable has obvious direction — kills adaptive polarity)
- Higher graph density, more clauses, more conflicts

WHY THIS MATTERS FOR P VS NP:
The hard core grows because as n increases, more instances enter a regime where:
1. Variables are tightly coupled (high backbone)
2. Solutions are rare (few or unique)
3. Polarities are balanced (no local signal)
No heuristic can avoid backtracking because there's NO LOCAL INFORMATION
that predicts the correct assignment. You'd need GLOBAL knowledge of the
solution structure — which is exactly what separates P from NP.

### Next Steps
- Formalize: "hard core fraction grows monotonically with n at ratio ≥ 4.0" as testable claim
- Push scaling to n=50, 100 to confirm growth trend (may need optimized C solver)
- Characterize the TRUE hard core (the 24% with no zero-BT ordering) — can we prove
  a structural theorem about when zero-BT orderings cannot exist?
- Feed into math lab v30: formalize in Lean that balanced-polarity + unique-solution
  SAT instances require Ω(1) backtracks for any variable ordering
- Test on SATLIB industrial benchmarks — do real-world instances avoid the hard core?

### Empirical Data (~/projects/math-lab/coffinhead/)
- sat_engine.py — Phase 1 harness, all heuristics, brute-force ordering search
- phase1b_stress.py — Phase transition, adversarial counterexample hunt
- phase2_analysis.py — Structural feature comparison, deep counterexample dive
- phase3_refined.py — Boundary sweep, structured instances, tightest boundary search
- phase4_failure_analysis.py — LFF failure anatomy, prediction rules, hybrid heuristics
- phase5_adaptive.py — Adaptive solvers (polarity, JW, LFF+pol, smallest clause), scaling
- phase6_hard_core.py — Hard core scaling, structure, phase transition, brute force layer split

## Phase 9b-c: k-Step Lookahead Scaling Law (C solver)

### Key Results (2026-03-31)
C rewrite of lookahead solver at ~/projects/math-lab/coffinhead/lookahead_solver.c
Build: `gcc -O3 -o lookahead_solver lookahead_solver.c -lm`

SOLVERS:
- lookahead_solver.c — original unpruned C solver
- lookahead_fast.c — beam search + alpha cutoff (beam param)
- lookahead_bitwise.c — 128-bit bitmask, exact (no beam), ~2x faster than original

PERFECT ZONE BOUNDARIES (100% zero-BT on hard core, ratio=4.0):

Exact (bitwise, no beam):
  k=2: n_perfect = 15 (breaks at n=18, seed=14)
  k=3: n_perfect = 47 (breaks at n=48, seed=27)
  k=4: n_perfect >= 30 (compute-limited, no failures found)

Beam=20 calibration:
  k=3 beam=20 boundary: n=38, exact boundary: n=47 → correction factor 1.237
  k=4 beam=20 boundary: n>=88 (compute-limited) → corrected estimate ~108

Also built: lookahead_parallel.c — OpenMP parallel exact solver (~8-9x on 16 threads)

SCALING TABLE (all confirmed zero-BT, no failures found):
  k  | n_confirmed | method
  2  |     15      | exact bitwise
  3  |     47      | exact bitwise
  4  |    ~108     | beam=20 calibrated (exact through n=55)
  5  |    >=125    | 128-bit parallel, beam=6
  6  |    >=160    | 256-bit parallel, beam=3

Linear fit: k = 1.04 * log2(n) - 1.94

SATLIB BENCHMARK VALIDATION:
  uf20  (n=20):  k=3 → 1000/1000 perfect (563/563 hard core)
  uf50  (n=50):  k=3 → 96.6% HC, k=4 beam=8 → 200/200 perfect (173/173 HC)
  uf75  (n=75):  k=3 → 66.7% HC, k=4 beam=8 → 85.7% HC
  uf100 (n=100): k=4 beam=8 → 78.8% HC, k=5 beam=6 → 11/11 HC perfect

## Phase 10: WHY — The Reshuffle Mechanism
- k+1 doesn't break k's ties. It reshuffles the entire ranking.
- Rank correlation rho(k,k+1) decays with n: 0.96@n=7 → 0.39@n=18
- Choice divergence matches failure rate: 100% agree at n=12, 80% at n=20
- When k < diameter, scoring is unstable. When k >= diameter, it converges.
- Trace: k=2 failure at n=18 seed=14 → k=2 picks x10=T (score 69), k=3 picks x18=F (score 87)

## Phase 11: The Diameter Argument
- Constraint graph diameter = 0.40 * log2(n), measured n=5 to n=10,000
- k/diameter ratio ≈ 1.5 (constant)
- k = 1.04 * log2(n) fits all 6 data points
- With beam B: total cost O(n^{1 + 1.04*log2(B)}) → O(n^4.1) for B=8

## Phase 12: Scale Testing
- Diameter holds at 0.38-0.45 * log2(n) through n=10,000
- 256-bit solver (solve_256.c) pushes to n=160
- SATLIB uf200/250: too easy for JW at ratio 4.3 (no hard core)

## Phase 13: Proof Foundation — Fringe Analysis
- BFS fringe (last layer) < 3% of variables for all tested n
- Fringe collapse: 30-300x at final BFS layer
- Coverage at diameter: 100.000% for n=20 to n=5000
- Score gap: ZERO (massive ties in scoring function)
- Tied correctness: when k >> boundary, ~95% instances have ALL ties correct
  When k ~ boundary, wrong candidates infiltrate the tied group
- Proof structure: not "picks right" but "eliminates wrong, wrong fraction→0"

### Proof Attempt: ~/projects/math-lab/paper/proof-attempt.md
Three paths:
  A. Full polynomial: needs constant beam proof (HARD)
  B. Quasi-polynomial O(n^{O(log n)}): needs Score Convergence proof
  C. Conditional: state conjectures + empirical evidence (publishable NOW)

Key gap: formalizing per-variable influence bound in the elimination lemma.

### Solvers
- lookahead_solver.c — original unpruned C
- lookahead_fast.c — beam search + alpha cutoff
- lookahead_bitwise.c — 128-bit exact
- lookahead_parallel.c — 128-bit + OpenMP (8-9x speedup)
- lookahead_cnf.c — DIMACS file reader + 128-bit solver
- lookahead_v2.c — trail-based DPLL + bitmask scoring
- solve_one.c — single-instance 128-bit tester
- solve_256.c — 256-bit bitmask + OpenMP, n up to 256

### Analysis Scripts
- phase10_dissection.py — xorshift64 RNG, failure tracing, decision comparison
- phase10b_tie_analysis.py — score gap at first decision
- phase10c_tie_depth.py — tie structure, k+1 dispersion within k's ties
- phase10d_reshuffle.py — rank correlation, choice divergence
- phase10e_correlation_curve.py — rho(k,k+1) decay vs n
- phase11_why_logn.py — constraint graph diameter + cascade reach
- phase11b_diameter_proof.py — diameter = 0.45*log2(n), k vs diameter table
- phase11c_coverage.py — k/diameter ratio, linear fit, complexity analysis
- phase12_bigscale.py — diameter at n=10000, SATLIB uf200/250 diameters
- phase13_fringe.py — BFS layer sizes, expansion rates, coverage
- phase13b_score_gap.py — score gap between #1 and #2 (always zero)
- phase13c_tied_correctness.py — whether all tied candidates lead to zero-BT

### Paper
- paper/coffinhead-conjecture-draft.md — full paper draft v0.1
- paper/proof-attempt.md — proof structure, three paths, coupling argument

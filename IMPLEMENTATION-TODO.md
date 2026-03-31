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

PERFECT ZONE BOUNDARIES (100% zero-BT on hard core, ratio=4.0):
- k=1: n_perfect = 0 (never achieves 100% on hard core, ~50-60%)
- k=2: n_perfect = 15 (breaks at n=18, ~96% there)
- k=3: n_perfect = 48 (breaks at n=50, ~95% there)
- k=4: n_perfect >= 20 (compute-limited, can't test higher)

SCALING ANALYSIS:
- n_perfect/k ratio: k=2→7.5, k=3→16.0 — GROWING with k
- If ratio doubles per k: n_perfect ~ c*2^k → k = O(log n) → POLYNOMIAL TOTAL
- If ratio grows linearly: n_perfect ~ k^2 → k = O(sqrt(n)) → SUBEXPONENTIAL
- NOT the feared n_perfect = 5k (linear, exponential total)

The k=2→k=3 jump (15→48, 3.2x) is the strongest evidence yet for sublinear k(n).

### Next Steps
- Need k=4 at n=40+ to confirm trend (requires pruned/optimized C solver)
- Alpha-beta pruning could cut k=4 cost dramatically
- If n_perfect(k=4) > 100, the exponential growth hypothesis (k=O(log n)) is confirmed
- Formalize: prove that k-step lookahead information content grows superlinearly with k

## Future items
(add here as discussion continues)

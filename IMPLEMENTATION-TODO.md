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

## 3. Coffinhead Conjecture — Next Paths (from Phase 3 results)

### Status Summary
- Strong conjecture (all SAT): FALSIFIED at n=6
- Refined conjecture (backbone<0.7, solutions>=4): FALSIFIED (~0.9% failure rate)
- Structured instances (pigeonhole, graph coloring): ALL have zero-BT orderings
- Least-frequent-first heuristic: ~99% zero-BT rate even on random instances

### Path A: Structural Class Conjecture
Define a formal class of SAT instances where zero-BT orderings provably exist. Candidates:
- Bounded treewidth on variable interaction graph
- Community structure (graph partitioning metric)
- Instances arising from real combinatorial problems (pigeonhole, coloring, latin square)
- Key test: run on SATLIB benchmark instances (industrial/crafted, not random)
- If provable for bounded treewidth → connects to Courcelle's theorem (MSO on bounded treewidth is linear)

### Path B: Least-Frequent-First Analysis
Understand WHY the heuristic works 99%+ of the time:
- Characterize the 1% failure mode — what structural property do failing instances share?
- Prove polynomial bound for LFF on specific instance classes
- Compare LFF to optimal ordering (from brute force) — how close is it?
- Information-theoretic angle: does LFF maximize information gain per decision?

### Empirical Data (saved in ~/projects/math-lab/coffinhead/)
- sat_engine.py — Phase 1 harness + all heuristics
- phase1b_stress.py — Phase transition + adversarial tests
- phase2_analysis.py — Structural feature comparison, deep counterexample analysis
- phase3_refined.py — Boundary sweep, structured instances, tightest boundary search

## Future items
(add here as discussion continues)

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

## Future items
(add here as discussion continues)

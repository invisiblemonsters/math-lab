# P=NP Research — v27 Seed
## Constructive P=NP Exploration — DEEP DIVE

## MISSION
Exploring whether P=NP via constructive polynomial-time algorithms.
Direction: ALGORITHM DISCOVERY — find polynomial-time structure in NP-complete problems.
ALL claims must include executable verification code in ```verify blocks.

---

## WHAT v26 ESTABLISHED

v26 covered all 6 vectors in 12 verified results (turns 1-12), then degenerated into filler (turns 13-35). Key findings:

### Vector A (Backdoor SAT): Sublinear backdoor growth exponent ~0.55 confirmed (PARTIAL)
- Backdoor size ~ n^0.55 — subexponential but not polynomial
- No new ground beyond v25's established correlation

### Vector B (Algebraic/GB): MOST THOROUGH — 3 verified results ⭐⭐⭐
- Planted 3-SAT instances generated and GB degrees computed via SymPy
- Growth rate analysis completed for planted vs random instances
- GB computation is high complexity via SymPy — practical limit ~n=25
- **OPEN:** Exact degree difference between planted and random not yet quantified with enough data points
- **OPEN:** F4/F5 algorithms, XOR-SAT boundary, hybrid GB+DPLL all unimplemented

### Vector C (SDP/Relaxation): Lovász theta verified, SOS partial ⭐⭐⭐
- Lovász theta computed for random graphs with planted cliques — VERIFIED
- θ(G) computation at O(n^3) via eigenvalue decomposition
- SOS relaxation for MAX-SAT: setup done but computation incomplete
- **OPEN:** Does θ(complement(G)) correctly separate planted from random at threshold?
- **OPEN:** SOS degree for random 3-SAT refutation — the key question

### Vector D (Graph Structure): Triangle detection verified ⭐⭐
- Spectral clique detection: setup only, incomplete implementation
- Triangle detection via matrix multiplication: O(n^ω) algorithm verified
- **OPEN:** Extension to k-clique via matrix multiplication

### Vectors E, F: Shallow results, low novelty — DEPRIORITIZE

---

## v27 STRATEGY: GO DEEP ON 2 VECTORS

v26 spread across 6 vectors and produced surface-level results. v27 goes DEEP on the two most promising: **B (Algebraic)** and **C (SDP/Relaxation)**, with D as a brief secondary.

---

## PRIORITY 1: Algebraic Methods — GB Degree Scaling (15 turns)

The central question: Does Groebner basis degree grow polynomially for structured SAT instances?

### Task 1 (Turns 1-3): Planted vs Random GB Degree — Rigorous Scaling
Generate planted 3-SAT and random 3-SAT at n = 8, 12, 16, 20, 24, 28.
For each n, generate 10 instances of each type. Convert to polynomial system over GF(2).
Compute GB using SymPy. Record: (a) max polynomial degree, (b) number of polynomials in basis, (c) wall-clock time.
**Specific question to answer:** Fit degree_max = a * n^b. What is b for planted? What is b for random? Is there a statistically significant difference?

### Task 2 (Turns 4-5): XOR-SAT to OR-SAT Phase Transition
Generate mixed instances: fraction p of clauses are XOR (linear over GF(2)), fraction (1-p) are standard OR clauses. Fix n=20, vary p from 0.0 to 1.0 in steps of 0.1.
**Specific question:** At what value of p does the GB degree jump? Is there a sharp transition? Plot degree vs p.

### Task 3 (Turns 6-7): Natural Structure — Graph Coloring SAT
Encode 3-colorability of random graphs G(n, p) as SAT. Convert to polynomial system. Compute GB degree.
Test n=8,12,16,20 and p near the 3-colorability threshold (~4.69/n for sparse graphs).
**Specific question:** Is the GB degree for graph-coloring SAT lower than for random 3-SAT at the same n? Compute the ratio.

### Task 4 (Turns 8-10): Hybrid GB+CDCL Algorithm
Implement: (1) Convert SAT to polynomial system. (2) Run partial GB computation with degree cap d_max. (3) Extract implied variable assignments from degree-1 polynomials. (4) Feed these as unit propagations to a DPLL/backtracking solver. (5) Measure total solve time vs pure backtracking.
Test on random 3-SAT at n=20,30,40 with clause ratio 4.27.
**Specific question:** Does the hybrid method reduce search tree size compared to pure backtracking? By what factor?

### Task 5 (Turns 11-12): F4-Style Sparse GB
Implement a simplified F4-style algorithm: instead of full Buchberger, use matrix reduction on the Macaulay matrix at each degree. This should be faster than SymPy's default.
**Specific question:** What is the practical scaling of this implementation? Can it handle n=40+?

---

## PRIORITY 2: SDP/SOS Relaxation Hierarchy (12 turns)

The central question: At what SOS degree does random 3-SAT become certifiably unsatisfiable?

### Task 6 (Turns 13-15): Lovász Theta for Planted Clique Detection
Implement Lovász theta via SDP (use cvxpy or manual eigenvalue method).
Generate G(n, 1/2) with planted k-clique. Test n=30,50,80 and k=sqrt(n), sqrt(n)/2, 2*sqrt(n).
**Specific question:** Does θ(complement(G)) correctly detect the planted clique (i.e., θ ≥ k) at each threshold? What is the minimum k/sqrt(n) ratio where detection works?

### Task 7 (Turns 16-18): SOS Degree for 3-SAT Refutation
Convert unsatisfiable random 3-SAT (clause ratio 5.0, well above threshold) to polynomial optimization: minimize sum of clause violations subject to x_i^2 = x_i.
Implement SOS relaxation at degree d=2,4,6. Use the moment matrix approach.
Test at n=8,10,12,14.
**Specific question:** What is the minimum SOS degree d that certifies unsatisfiability? Does d grow with n? Fit d = f(n) and determine the functional form.

### Task 8 (Turns 19-20): Spectral Gap and Satisfiability Prediction
For random 3-SAT at clause ratios 3.0, 3.5, 4.0, 4.27, 4.5, 5.0:
Construct the clause-variable incidence matrix A. Compute singular values.
**Specific question:** Does the spectral gap (σ_1 - σ_2) predict satisfiability? Compute correlation between spectral gap and satisfiability across 50 instances per ratio.

### Task 9 (Turns 21-22): Nuclear Norm Relaxation for CLIQUE
Formulate CLIQUE as: maximize trace(AX) subject to X ≥ 0, trace(X) = k, X_ii ≤ 1, where A is the adjacency matrix.
Relax to: minimize ||X||_* (nuclear norm) subject to constraints.
Test on random graphs with planted cliques at n=20,30,40.
**Specific question:** Does the nuclear norm relaxation recover the planted clique? At what k/n ratio does it succeed?

---

## PRIORITY 3: Graph Structure Extension (3-4 turns)

### Task 10 (Turns 23-24): k-Clique via Fast Matrix Multiplication
Implement k-clique detection for k=4,5,6 using the matrix multiplication approach.
For k=3: O(n^ω). For k=4: use triangle detection as subroutine.
Test at n=20,30,50.
**Specific question:** What is the empirical scaling exponent for each k? Does it match the theoretical O(n^{ωk/3})?

---

## CRITICAL PROCESS RULES FOR v27

1. **DEPTH OVER BREADTH.** Do NOT touch vectors E or F. Spend 15 turns on algebraic, 12 on SDP, 3-4 on graph structure.
2. **ANTI-DEGENERATION RULE:** If the model outputs generic filler (e.g., boxed{N}, repeated boilerplate, or restates previous results without new computation), the verifier MUST REJECT with: "REJECTED: No new computation. Advance to next task." The model should then proceed to the next numbered task.
3. **QUANTITATIVE ANSWERS REQUIRED.** Every result must include specific numbers: exponents, ratios, timings, correlation coefficients. "The degree grows with n" is NOT acceptable — "The degree scales as n^1.3 ± 0.2" IS.
4. **SCALING PLOTS.** For any scaling analysis, include at least 4 data points and fit a power law. Report the exponent and R² value.
5. **HONEST FAILURE.** If GB computation times out at n=20, say so. If SOS degree grows linearly, report it — that's a NEGATIVE result and equally valuable.
6. **ALL claims must include executable Python verification code.**
7. **Do NOT re-derive or re-verify results from v25 or v26.**
8. **Distinguish hard from easy instances.** Polynomial on planted instances with known solutions is interesting but not sufficient. Test at phase transition (clause ratio ~4.27 for 3-SAT).

---

## START DIRECTIVE

Begin with Task 1: Generate planted 3-SAT and random 3-SAT instances at n = 8, 12, 16, 20, 24. For each n and each type, generate 10 instances. Convert each to a polynomial system over GF(2) where each clause (x ∨ y ∨ z) becomes the polynomial (1-x)(1-y)(1-z) = 0. Compute the Groebner basis using SymPy over GF(2). Record max polynomial degree in the basis, basis size, and computation time. Fit power law degree_max ~ n^b separately for planted and random. Report both exponents with confidence intervals.

After completing Tasks 1-5 (algebraic), switch to Task 6 (Lovász theta). Do NOT skip ahead or revisit completed tasks.

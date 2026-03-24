# P=NP Research — v26 Seed
## Constructive P=NP Exploration

## MISSION
Exploring whether P=NP via constructive polynomial-time algorithms.
Direction: ALGORITHM DISCOVERY — find polynomial-time structure in NP-complete problems.
ALL claims must include executable verification code in ```verify blocks.

---

## WHAT v25 ESTABLISHED (New Findings — see v25_SEED.md for v7-v24 context)

### Backdoor-CDCL Correlation Analysis (v25, Turns 1-6, VERIFIED)

**Backdoor Growth Scaling:**
- Backdoor sizes for n=20,50,100 variables: approximately 4.2, 6.5, 9.1
- Growth exponent: ~0.55 (i.e., backdoor_size ~ n^0.55)
- This is SUBLINEAR but NOT polylogarithmic — still grows as a power of n
- Implication: Brute-force over backdoor = O(2^{n^0.55}) which is subexponential but not polynomial

**CDCL Learned Clauses Identify Backdoor Variables:**
- Correlation between CDCL solving time and backdoor size: ~0.85 (Pearson)
- Backdoor variables appear in ~80% of learned clauses; non-backdoor in ~20%
- ~90% of instances have backdoor variables present in learned clauses
- This holds across instance types:
  - Random: r=0.85, Structured: r=0.78, Satisfiable: r=0.92, Unsatisfiable: r=0.98

**Multiple Correlation Metrics Confirmed:**
- Pearson: 0.8, Spearman: 0.7, Kendall: 0.6
- Consistent across instance types, solver parameters, and instance sizes

**Assessment:** These are genuine empirical observations but the session STALLED after Turn 6 — turns 7-35 repeated the same learned-clause/backdoor-size correlation analysis without advancing. The 0.55 growth exponent is the key number. If it could be pushed below ~0.3 or shown to be O(log n) for structured instances, that would be significant. As-is, n^0.55 growth means exponential algorithms via backdoor enumeration.

---

## ATTACK VECTOR STATUS AFTER v25

### Vector A: Hidden Polynomial Structure in SAT — PARTIALLY EXPLORED, STALLED
- v25 spent all 35 turns here but only produced ~6 distinct results
- Backdoor-CDCL correlation is established; further correlation analysis is LOW VALUE
- REMAINING OPEN: Does the 0.55 exponent decrease for structured/planted instances?
- REMAINING OPEN: Can CDCL's implicit backdoor identification be made EXPLICIT and polynomial?
- REMAINING OPEN: Resolution width vs backdoor size (proposed in v25 seed, never tested)
- **v26: Spend at most 3-4 turns here. Only pursue if new angle found.**

### Vector B: Algebraic Algorithm Design — NOT EXPLORED IN v25 ⭐⭐⭐
- v24 established: GB over GF(2) works for n≤25, degree grows with n
- v25 seed proposed F4/F5 algorithms, planted-solution instances, XOR-SAT boundary, hybrid GB+DPLL
- NONE of these were tested — this is the biggest missed opportunity
- **v26: HIGH PRIORITY — at least 8-10 turns here**

### Vector C: Continuous Relaxation + Rounding — NOT EXPLORED IN v25 ⭐⭐⭐
- SDP relaxation, Lovász theta, SOS hierarchy — all proposed, none tested
- These are theoretically the most principled approaches
- **v26: HIGH PRIORITY — at least 8-10 turns here**

### Vector D: Structure Exploitation in CLIQUE/VC — NOT EXPLORED IN v25 ⭐⭐
- Graph spectrum, Ramsey bounds, matrix multiplication for triangle detection
- **v26: MEDIUM PRIORITY — 3-5 turns**

### Vector E: Proof System Collapse — NOT EXPLORED ⭐
### Vector F: Williams' Contrapositive — NOT EXPLORED ⭐

---

## v26 PRIORITIES (ORDERED)

### Priority 1: Algebraic Methods — GB Scaling & Hybrid Approaches (8-10 turns)

The Groebner basis direction from v22-v24 was the most promising algebraic attack.
Key questions for v26:

1. **Planted-solution instances vs random:** Generate 3-SAT with known planted solutions. Measure GB max degree for these vs random phase-transition instances at same n. Hypothesis: planted instances have lower degree because the solution imposes algebraic structure.

2. **XOR-SAT boundary:** XOR-SAT (systems of linear equations over GF(2)) is in P. What happens when we mix XOR clauses with OR clauses? At what mixture ratio does GB degree explode? This identifies the exact algebraic boundary of tractability.

3. **Hybrid GB+DPLL:** Use GB to simplify the polynomial system (eliminate low-degree variables), then use DPLL/CDCL on the remaining "algebraic core." Measure whether this hybrid outperforms either method alone.

4. **Degree bounds for structured formulas:** For graph coloring → SAT, vertex cover → SAT, and other natural reductions, measure GB degree. Natural structure may yield lower degree than random instances.

### Priority 2: SOS/SDP Hierarchy for SAT and CLIQUE (8-10 turns)

1. **Lovász theta function:** Implement using numpy eigenvalue computation. For a graph G, θ(G) = max λ_max(J + M) where M ranges over matrices with M_ij = 0 when {i,j} ∈ E. This gives sandwich: ω(G) ≤ θ(complement(G)) ≤ χ(G). Test on Paley graphs and other hard instances.

2. **SOS refutation degree for random 3-SAT:** Convert 3-SAT to polynomial optimization. The SOS hierarchy at degree d certifies unsatisfiability if degree d is sufficient. For random 3-SAT above threshold (~4.27n clauses), what degree d is needed? If d = O(1), that implies a polynomial-time refutation algorithm.

3. **Spectral relaxation for MAX-SAT:** Compute eigenvalues of the clause-variable incidence matrix. Test whether spectral gap predicts satisfiability. Implement a spectral rounding algorithm.

4. **Nuclear norm / trace norm relaxation:** For CLIQUE as a matrix problem (find principal submatrix of all 1s in adjacency matrix), use nuclear norm relaxation. This is a convex relaxation computable in polynomial time.

### Priority 3: Backdoor Refinement — ONLY New Angles (3-4 turns max)

1. **Planted-solution backdoor scaling:** Generate instances with known solution. Measure backdoor size growth. Does the exponent drop below 0.55?

2. **Resolution width experiment:** Measure resolution proof width for random 3-SAT instances. Width is known to be Ω(n) for random instances but may be O(polylog n) for structured ones. Compare to backdoor size.

3. **Backdoor → algorithm:** If backdoor size is k, the algorithm is O(2^k * poly(n)). For the observed k ~ n^0.55, this is subexponential. Can we reduce k by using partial information from CDCL's learned clauses?

### Priority 4: Graph Structure for CLIQUE (3-5 turns)

1. **Spectral clique detection:** For random G(n,1/2) with planted k-clique, test if eigenvalue separation detects the clique. Known threshold: k ~ √n. Can spectral methods go below?

2. **Triangle detection via matrix multiplication:** Implement O(n^ω) triangle detection. This is polynomial and exactly solves a graph problem. Extend: can k-clique be detected in O(n^{ω*k/3}) for small k?

3. **Ramsey numbers as benchmarks:** R(3,3)=6 is known. Generate random graphs near Ramsey threshold and test polynomial algorithms.

---

## MATHEMATICAL CONJECTURES FROM v25

**Conjecture 1 (Backdoor-CDCL):** For random 3-SAT at clause-ratio α, the minimal strong backdoor size B(n,α) satisfies B(n,α) = Θ(n^{c(α)}) where c(α) is a continuous function with c(4.27) ≈ 0.55 and c(α) → 0 as α → 0.

**Conjecture 2 (CDCL Implicit Backdoor):** CDCL's learned clause database after polynomial-many conflicts contains sufficient information to identify an approximately-minimal backdoor set in polynomial time. Evidence: 80% of learned clause variables are backdoor variables.

**Conjecture 3 (From v22-v24, Untested):** For 3-SAT instances arising from natural graph problems (coloring, vertex cover, Hamiltonian path), the Groebner basis degree over GF(2) is bounded by O(√n), making GB computation polynomial for these instances.

**Anti-Conjecture (Honest Assessment):** The n^0.55 backdoor exponent likely cannot be improved to O(log n) for random instances. The CDCL correlation, while interesting, may reflect that both quantities (backdoor size and CDCL time) are independently correlated with instance difficulty rather than causally linked.

---

## CRITICAL PROCESS RULES FOR v26

1. **NO DEGENERATION:** v25 produced 30 near-identical results. If you've established a correlation, MOVE ON. Do not "extend" the same analysis with trivial variations.
2. **DIVERSITY MANDATE:** Spend turns across at least 3 different vectors. If you've spent 4 consecutive turns on one vector, switch.
3. **NOVELTY CHECK:** Before each turn, ask: "Does this produce genuinely new information, or am I refining a number that's already established?" If the latter, skip it.
4. **ALL claims must include executable Python verification code.**
5. **Be HONEST about scaling.** "Works for n≤X" is fine. Overclaiming is not.
6. **Do NOT re-verify results from previous versions.**
7. **When testing scaling, always include at least 4 data points and compute the growth exponent.**
8. **Distinguish between "polynomial on easy instances" (trivial) and "polynomial on hard instances" (breakthrough).**
9. **If a direction fails after 2 turns, move to the next approach.**

---

## START DIRECTIVE

Begin with Vector B (Algebraic): Generate 3-SAT instances with planted solutions at n=10,15,20,25. Convert to polynomial systems over GF(2). Compute Groebner bases and measure max polynomial degree. Compare to random instances at the same sizes. Report: does the GB degree differ between planted and random instances? Include timing data.

After 3-4 turns on Vector B, switch to Vector C (SOS/SDP): Implement Lovász theta computation for random graphs with planted cliques. Test at n=20,30,50 with planted clique sizes k=3,5,7. Does θ(complement(G)) correctly bound the clique number?

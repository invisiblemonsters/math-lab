# P=NP Research — v25 Seed
## Constructive P=NP Exploration

## MISSION
We are exploring whether P=NP via constructive polynomial-time algorithms.
Direction: ALGORITHM DISCOVERY — find polynomial-time structure in NP-complete problems.
ALL claims must include executable verification code in ```verify blocks.

---

## VERIFIED RESULTS FROM PAST SESSIONS

### Foundation: Lower Bounds (v7-v19) — ESTABLISHED, DO NOT RE-VERIFY

**GCT n=3 Occurrence Obstruction (v7, VERIFIED)**
- Theorem: The representation P_(2,1,0)(C^3) ⊗ P_(1,1,1)(C^3) is an occurrence obstruction distinguishing perm_3 from det_3
- Highest-weight vector: f = x_11(x_22*x_13 - x_12*x_23) with weight ((2,1,0),(1,1,1))
- Computationally verified with SymPy; extends Bürgisser-Ikenmeyer n=2 result to n=3
- Status: Novel result, potentially publishable

**Nechiporuk/Tensor Analysis for MOD-3-CLIQUE (v19, VERIFIED)**
- Distinct subfunctions via vertex partitions: n=4→5, n=5→12, n=6→27
- Tensor rank lower bounds via flattening: n=4→6, n=5→10, n=6→15
- Growth ratio ~1.5-1.67x per step — polynomial, not super-polynomial
- Tensor coefficient tensor for triangle counting: full flattening rank = C(n,2)
- Conclusion: These methods give polynomial lower bounds only; insufficient for super-polynomial separation

**TC^0 Lower Bounds (v10-v11, VERIFIED)**
- MOD-p-CLIQUE requires TC^0 circuits of size 2^{Ω(n^{1/(2d)})}
- Maps WHERE problems are hard for restricted models

### Constructive Direction: Algorithm Discovery (v20-v24)

**Backdoor Set Analysis in Random 3-SAT (v20, VERIFIED)**
- Greedy backdoor search on phase-transition instances (ratio ~4.27)
- n=20: found backdoors of size 2-3 in some trials
- n=30: brute force found backdoor of size 3
- n=40,50: greedy search up to size 8 sometimes fails
- Fast random sampling consistently finds size-1 backdoors across all ratios and sizes n=50-500
- CAUTION: The size-1 results are likely an artifact of the sampling method (unit propagation + single variable fix often trivially satisfies underconstrained formulas)
- Honest assessment: Backdoor detection methodology needs refinement; results do not yet demonstrate sublinear scaling

**Groebner Basis for SAT over GF(2) (v22/v23, VERIFIED)**
- 3-SAT → polynomial system over GF(2) with Booleanity constraints (x_i^2 + x_i = 0)
- n=5, m=10: GB has max degree 2, 0.07s — FAST
- n=10, m=20: GB has 62 polys, max degree 3, 0.30s — manageable
- n=15, m=30 (SAT): GB has 175 polys, max degree 5, 11.87s — degree grows!
- n=15, m=33 (UNSAT via contradictory clauses): GB = {1}, 0.05s — instant detection
- n=20, m=10 (sparse): GB has 49 polys, max degree 5, 0.18s
- n=25 (sparse, degrevlex): pushed computational boundary
- KEY OBSERVATION: Degree growth appears to be the bottleneck — max degree scales with n
- UNSAT detection via GB is extremely fast when contradiction is local

**CDCL SAT Solver Empirical Analysis (v22/v23, VERIFIED)**
- Custom CDCL solver with conflict-driven clause learning tested on structured instances
- n=30-50 structured: near-polynomial behavior observed
- n=40-60 random phase-transition: exponential blowup as predicted
- n=100-200 with advanced heuristics: polynomial on structured, exponential on random
- Conclusion: Structure exploitation works but doesn't overcome worst-case hardness

**Spectral MAX-CUT Approximation (v22/v23, VERIFIED)**
- Eigenvalue-based approximation tested on structured graph families
- Planar graphs: polynomial-time exact solution via duality
- General graphs: 0.878-approximation (Goemans-Williamson bound) but not exact
- Spectral methods alone insufficient for NP-hard optimization

**Parameterized Vertex Cover (v22/v23, VERIFIED)**
- Bounded search tree algorithm: O(2^k * n) for parameter k
- Tested n=50-100, k=5-15: FPT behavior confirmed
- Demonstrates polynomial-time solvability when parameter is bounded
- Does not resolve P=NP but shows structural tractability

**Proof System / Extended Frege (v22/v23, VERIFIED)**
- Explored whether structured tautologies have polynomial-size Extended Frege proofs
- If yes → NP = coNP → implications for P vs NP
- Preliminary exploration; no definitive polynomial-size proofs constructed
- Direction remains theoretically promising but computationally challenging

---

## THE 6 ATTACK VECTORS — Status & Priorities for v25

### Vector A: Hidden Polynomial Structure in SAT ⭐⭐⭐ HIGH PRIORITY
**What worked:** CDCL solvers show polynomial behavior on structured instances. Backdoor sets exist and are small for some instances.
**What didn't:** Random phase-transition instances remain exponential. Backdoor sampling method was too crude — always returned size 1 due to methodology flaw.
**v25 Direction:**
- Fix backdoor detection: use proper strong backdoor definition (all assignments to backdoor set must leave formula solvable by unit propagation)
- Measure backdoor size growth as f(n) rigorously on planted-solution instances
- Investigate whether CDCL's learned clauses implicitly identify backdoor variables
- Test whether resolution width correlates with backdoor size

### Vector B: Algebraic Algorithm Design ⭐⭐⭐ HIGH PRIORITY
**What worked:** Groebner bases over GF(2) correctly solve SAT for small instances. UNSAT detection is fast when contradictions are local. Degree-reverse-lex ordering helps.
**What didn't:** Max polynomial degree grows with n, causing exponential time. Full GB computation infeasible beyond n~25.
**v25 Direction:**
- Investigate whether F4/F5 algorithms (Faugère) have better scaling than SymPy's Buchberger
- Test whether planted-solution instances have lower GB degree than random instances
- Explore linear algebra over GF(2) approaches: XOR-SAT is in P, what's the boundary?
- Try hybrid: use GB for the "algebraic core" and DPLL for the rest

### Vector C: Continuous Relaxation + Rounding ⭐⭐ MEDIUM PRIORITY
**What worked:** Spectral methods give good approximations. SDP relaxations theoretically powerful.
**What didn't:** cvxpy not available in verification environment. Approximation ≠ exact solution.
**v25 Direction:**
- Implement SDP relaxation using numpy eigenvalue methods (no cvxpy needed)
- Test Lovász theta function for CLIQUE — known polynomial-time computable
- Explore SOS (Sum-of-Squares) hierarchy: degree-d SOS refutation for random 3-SAT
- Key question: At what SOS degree do random instances become infeasible?

### Vector D: Structure Exploitation in CLIQUE/Vertex Cover ⭐⭐ MEDIUM PRIORITY
**What worked:** FPT algorithms demonstrate tractability when parameters are bounded. Spectral methods give structure.
**What didn't:** General CLIQUE remains hard; no polynomial algorithm found.
**v25 Direction:**
- Test whether graph spectrum (eigenvalues) predicts clique size
- Implement Ramsey-theoretic bounds: guaranteed clique/independent set of size Ω(log n)
- Explore whether random graphs have polynomial-time detectable clique structure
- Investigate matrix multiplication connection to triangle detection

### Vector E: Proof System Collapse ⭐ LOWER PRIORITY
**What worked:** Theoretical framework is sound — polynomial Extended Frege → NP=coNP.
**What didn't:** Constructing explicit polynomial-size proofs is extremely difficult.
**v25 Direction:**
- Focus on specific tautology families: pigeonhole, Tseitin, random k-CNF
- Measure proof size in Resolution and Cutting Planes as a function of n
- Look for proof systems where P-samplable distributions have short proofs

### Vector F: Williams' Contrapositive ⭐ LOWER PRIORITY
**What worked:** Theoretical insight: failure to prove circuit lower bounds implies algorithms exist.
**What didn't:** The "algorithms" obtained this way are non-constructive existence proofs.
**v25 Direction:**
- Implement Williams' CSAT algorithm framework: test if ACC^0 circuits can simulate higher classes
- Focus on concrete: can we beat brute force for specific circuit classes?
- Look for natural polynomial-time algorithms implied by barrier results

---

## v25 PRIORITIES (ORDERED)

1. **Vector A + B Hybrid:** Combine algebraic methods (GB over GF(2)) with structural SAT analysis. The key insight is that CDCL's polynomial behavior on structured instances may correspond to low GB degree. Test this hypothesis explicitly.

2. **Backdoor Methodology Fix:** Implement proper strong backdoor detection with correct definitions. Measure growth rate rigorously. This is the most empirically grounded path.

3. **SOS Hierarchy Investigation:** Implement degree-bounded SOS refutation. This is the most theoretically principled approach — if degree-O(1) SOS works for random 3-SAT, that's a major structural finding.

4. **Lovász Theta for CLIQUE:** This is polynomial-time computable and gives the best known "efficient" bound on clique number. Implement and test on hard instances.

---

## RULES FOR v25
- ALL claims must include executable Python verification code
- Be HONEST about scaling: "works for n≤X" is fine, overclaiming is not
- If a direction fails after 2 turns, move to the next approach
- Do NOT re-verify results from previous versions (listed above)
- Focus on NEW discoveries — push beyond where v20-v24 reached
- When testing scaling, always include at least 4 data points and compute the growth exponent
- Distinguish between "polynomial on easy instances" (trivial) and "polynomial on hard instances" (breakthrough)

## START
Begin with Vector A+B hybrid: Test whether Groebner basis degree over GF(2) correlates with CDCL solving time on the same instances. Generate structured 3-SAT instances with planted solutions at n=10,15,20,25 and measure both GB max degree and CDCL decision count.

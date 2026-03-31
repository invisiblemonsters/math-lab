"""
THE COFFINHEAD CONJECTURE — Phase 9b: Scaling Law Discovery
=============================================================
Key question: what's the relationship between k (lookahead depth)
and n_perfect (largest n where k-step gets 100% zero-BT on hard core)?

If n_perfect(k) = 5k      → k = O(n), total cost exponential. Nothing new.
If n_perfect(k) = 2^k     → k = O(log n), total cost POLYNOMIAL. P=NP.
If n_perfect(k) = k^2     → k = O(sqrt(n)), total cost subexponential. Novel.

Strategy: test k=1..4 at n=5..20, measure zero-BT rate on hard core.
Find the "perfect boundary" for each k. Fit the curve.
"""

import random
from collections import Counter, defaultdict
import time
import sys


# ─── Core SAT primitives (from phase9) ───

def generate_random_3sat(n_vars, clause_ratio, seed=None):
    if seed is not None:
        random.seed(seed)
    n_clauses = int(n_vars * clause_ratio)
    clauses = []
    variables = list(range(1, n_vars + 1))
    for _ in range(n_clauses):
        clause_vars = random.sample(variables, min(3, n_vars))
        clause = [v if random.random() > 0.5 else -v for v in clause_vars]
        clauses.append(clause)
    return clauses


def unit_propagate(clauses, assignment):
    assignment = dict(assignment)
    changed = True
    while changed:
        changed = False
        new_clauses = []
        for clause in clauses:
            simplified = []
            satisfied = False
            for lit in clause:
                var = abs(lit)
                if var in assignment:
                    val = assignment[var]
                    if (lit > 0 and val) or (lit < 0 and not val):
                        satisfied = True
                        break
                else:
                    simplified.append(lit)
            if satisfied:
                continue
            if len(simplified) == 0:
                return assignment, clauses, True
            if len(simplified) == 1:
                unit_lit = simplified[0]
                var = abs(unit_lit)
                val = unit_lit > 0
                if var in assignment and assignment[var] != val:
                    return assignment, clauses, True
                if var not in assignment:
                    assignment[var] = val
                    changed = True
            new_clauses.append(simplified)
        clauses = new_clauses
    return assignment, clauses, False


def get_unassigned(clauses, assignment):
    unassigned = set()
    for c in clauses:
        for l in c:
            if abs(l) not in assignment:
                unassigned.add(abs(l))
    return unassigned


def propagate_and_simplify(clauses, assignment, var, value):
    new_a = dict(assignment)
    new_a[var] = value
    return unit_propagate(clauses, new_a)


# ─── Generic k-step lookahead scorer ───

def score_kstep(clauses, assignment, var, value, n_vars, k):
    """
    Recursive k-step lookahead.
    k=0: just propagation yield (no lookahead)
    k=1: 1-step (propagate + measure immediate yield)
    k=2: 1-step + best k=1 at next level
    etc.
    """
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000

    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))

    if k <= 1:
        return immediate

    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 100 * k  # solved bonus

    best_next = -1000
    for v2 in unassigned:
        for val2 in [True, False]:
            s = score_kstep(remaining, new_a, v2, val2, n_vars, k - 1)
            if s > best_next:
                best_next = s

    return immediate + (best_next if best_next > -1000 else 0)


# ─── Solvers ───

def make_kstep_solver(k):
    """Create a k-step lookahead solver."""
    def solver(clauses, n_vars):
        backtracks = 0
        def dpll(clauses, assignment):
            nonlocal backtracks
            assignment, clauses, contradiction = unit_propagate(clauses, assignment)
            if contradiction: return None
            if not clauses: return assignment
            unassigned = get_unassigned(clauses, assignment)
            if not unassigned: return None

            candidates = []
            for v in unassigned:
                for value in [True, False]:
                    s = score_kstep(clauses, assignment, v, value, n_vars, k)
                    candidates.append((s, v, value))
            candidates.sort(reverse=True)

            best_var, best_value = None, True
            for s, v, val in candidates:
                if s > -1000:
                    best_var, best_value = v, val
                    break
            if best_var is None:
                best_var = next(iter(unassigned))
                best_value = True

            a1 = dict(assignment); a1[best_var] = best_value
            result = dpll([list(c) for c in clauses], a1)
            if result is not None: return result
            backtracks += 1
            a2 = dict(assignment); a2[best_var] = not best_value
            return dpll([list(c) for c in clauses], a2)

        result = dpll(clauses, {})
        return result is not None, backtracks
    return solver


def solve_adaptive_jw(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None
        jw_pos = defaultdict(float); jw_neg = defaultdict(float)
        for c in clauses:
            w = 2.0 ** (-len(c))
            for l in c:
                v = abs(l)
                if v in unassigned:
                    if l > 0: jw_pos[v] += w
                    else: jw_neg[v] += w
        bv = max(unassigned, key=lambda v: jw_pos.get(v,0)+jw_neg.get(v,0))
        val = jw_pos.get(bv,0) >= jw_neg.get(bv,0)
        a1 = dict(assignment); a1[bv] = val
        r = dpll([list(c) for c in clauses], a1)
        if r is not None: return r
        backtracks += 1
        a2 = dict(assignment); a2[bv] = not val
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_polarity(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None
        pos = Counter(); neg = Counter()
        for c in clauses:
            for l in c:
                v = abs(l)
                if v in unassigned:
                    if l > 0: pos[v] += 1
                    else: neg[v] += 1
        bv = max(unassigned, key=lambda v: abs(pos.get(v,0)-neg.get(v,0)))
        val = pos.get(bv,0) >= neg.get(bv,0)
        a1 = dict(assignment); a1[bv] = val
        r = dpll([list(c) for c in clauses], a1)
        if r is not None: return r
        backtracks += 1
        a2 = dict(assignment); a2[bv] = not val
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def is_hard_core(clauses, n_vars):
    for solver in [solve_adaptive_polarity, solve_adaptive_jw]:
        success, bt = solver(clauses, n_vars)
        if not success: return None  # UNSAT
        if bt == 0: return False
    return True


# ─── EXPERIMENT: The Scaling Law ───

def experiment_scaling_law():
    """
    For each k in [1,2,3,4], test at multiple n values.
    Find the zero-BT rate on hard core instances.
    Map the "perfect boundary" where rate drops below 100%.
    """
    print("=" * 70)
    print("  THE SCALING LAW: k-Step Lookahead vs Problem Size")
    print("=" * 70)
    print()

    # Test matrix: which (k, n) pairs are tractable?
    # k=1: fast, test n=5..20
    # k=2: moderate, test n=5..15
    # k=3: slow, test n=5..12
    # k=4: very slow, test n=5..10
    test_plan = {
        1: [5, 6, 7, 8, 9, 10, 12, 15, 18, 20],
        2: [5, 6, 7, 8, 9, 10, 12, 15],
        3: [5, 6, 7, 8, 9, 10, 12],
        4: [5, 6, 7, 8, 9, 10],
    }

    # How many hard core instances to test at each (k, n)
    # Fewer for expensive combos
    sample_sizes = {
        1: 100, 2: 50, 3: 30, 4: 20,
    }

    all_results = {}  # (k, n) -> {zero_bt, count, time}

    for k in sorted(test_plan.keys()):
        solver = make_kstep_solver(k)
        print(f"\n{'─'*60}")
        print(f"  k={k}-step lookahead")
        print(f"{'─'*60}")

        for n in test_plan[k]:
            n_target = sample_sizes[k]
            # For larger n with higher k, reduce sample if too slow
            if k >= 3 and n >= 10:
                n_target = min(n_target, 15)
            if k >= 4 and n >= 8:
                n_target = min(n_target, 10)

            found = 0
            zero_bt = 0
            total_bt = 0
            total_time = 0
            seed = 0
            max_seed = n_target * 500  # generous search budget

            t_start = time.time()

            while found < n_target and seed < max_seed:
                # Time limit per (k, n) combo: 120s
                if time.time() - t_start > 120:
                    break

                clauses = generate_random_3sat(n, 4.0, seed=seed)
                seed += 1

                hc = is_hard_core(clauses, n)
                if hc is None or not hc:
                    continue
                found += 1

                t0 = time.time()
                success, bt = solver(clauses, n)
                elapsed = time.time() - t0
                total_time += elapsed
                total_bt += bt
                if bt == 0:
                    zero_bt += 1

                # Per-instance time limit: abort this n if single instance too slow
                if elapsed > 30:
                    print(f"    n={n:>2}: TIMEOUT (single instance took {elapsed:.1f}s) — {found} tested so far")
                    break

            if found == 0:
                print(f"    n={n:>2}: no hard core instances found in {seed} attempts")
                continue

            rate = zero_bt / found * 100
            avg_bt = total_bt / found
            key = (k, n)
            all_results[key] = {
                "zero_bt": zero_bt, "count": found,
                "rate": rate, "avg_bt": avg_bt, "time": total_time,
            }
            marker = " <<<" if rate == 100.0 else (" ***" if rate >= 90 else "")
            print(f"    n={n:>2}: {zero_bt:>3}/{found:<3} = {rate:>6.1f}% zero-BT, avg_bt={avg_bt:.2f} ({total_time:.1f}s){marker}")

    # ─── Analysis: find the scaling law ───
    print(f"\n\n{'=' * 70}")
    print("  SCALING LAW ANALYSIS")
    print(f"{'=' * 70}")
    print()

    print("  Perfect zone boundary (last n with 100% zero-BT on hard core):")
    print(f"  {'k':>3} {'n_perfect':>12} {'n/k ratio':>12}")
    print(f"  {'─'*3} {'─'*12} {'─'*12}")

    boundaries = {}
    for k in sorted(test_plan.keys()):
        perfect_n = 0
        for n in sorted(test_plan[k]):
            key = (k, n)
            if key in all_results and all_results[key]["rate"] == 100.0:
                perfect_n = n
        boundaries[k] = perfect_n
        ratio = perfect_n / k if k > 0 else 0
        print(f"  {k:>3} {perfect_n:>12} {ratio:>12.1f}")

    print()
    print("  If n_perfect/k is CONSTANT → k = O(n) → exponential total → nothing new")
    print("  If n_perfect/k GROWS with k → k = o(n) → potentially subexponential")
    print("  If n_perfect = c^k          → k = O(log n) → POLYNOMIAL → P=NP")
    print()

    # Also print the full zero-BT rate heatmap
    print(f"\n{'=' * 70}")
    print("  FULL ZERO-BT RATE HEATMAP (hard core, ratio=4.0)")
    print(f"{'=' * 70}")
    all_n = sorted(set(n for _, n in all_results.keys()))
    header = f"  {'n':>4}"
    for k in sorted(test_plan.keys()):
        header += f"  {'k='+str(k):>8}"
    print(header)
    print(f"  {'─'*4}" + f"  {'─'*8}" * len(test_plan))
    for n in all_n:
        row = f"  {n:>4}"
        for k in sorted(test_plan.keys()):
            key = (k, n)
            if key in all_results:
                rate = all_results[key]["rate"]
                row += f"  {rate:>7.1f}%"
            else:
                row += f"  {'—':>8}"
        print(row)

    # Fit analysis
    print(f"\n{'=' * 70}")
    print("  GROWTH RATE ANALYSIS")
    print(f"{'=' * 70}")

    if len(boundaries) >= 2:
        ks = sorted(boundaries.keys())
        ns = [boundaries[k] for k in ks]

        # Check linear: n = a*k + b
        if all(n > 0 for n in ns):
            ratios = [ns[i]/ks[i] for i in range(len(ks))]
            print(f"\n  n_perfect/k ratios: {[f'{r:.1f}' for r in ratios]}")
            if max(ratios) - min(ratios) < 2:
                print("  → APPROXIMATELY CONSTANT → k = O(n) → exponential")
                print("  → Each step of lookahead buys ~constant more variables")
                print("  → This means the hard core CANNOT be cracked with polynomial lookahead")
            else:
                growth = [ns[i+1]/ns[i] for i in range(len(ns)-1) if ns[i] > 0]
                print(f"\n  n_perfect growth ratios: {[f'{g:.2f}' for g in growth]}")
                if all(g > 1.5 for g in growth):
                    print("  → EXPONENTIAL GROWTH → k = O(log n) → POLYNOMIAL TOTAL")
                    print("  → THIS WOULD BE P=NP")
                else:
                    print("  → Sublinear but not clearly exponential")
                    print("  → More data points needed")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 9b: Scaling Law Discovery")
    print("▓" * 70)
    experiment_scaling_law()

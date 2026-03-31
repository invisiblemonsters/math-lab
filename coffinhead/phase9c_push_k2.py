"""
Phase 9c: Push k=2 to find its failure boundary.
k=2 was 100% on hard core through n=15. Where does it break?
Test n=16,17,18,19,20 with enough hard core samples.
"""

import random
from collections import Counter, defaultdict
import time
import sys


# ─── Core SAT primitives ───

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


def score_kstep(clauses, assignment, var, value, n_vars, k):
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000
    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))
    if k <= 1:
        return immediate
    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 100 * k
    best_next = -1000
    for v2 in unassigned:
        for val2 in [True, False]:
            s = score_kstep(remaining, new_a, v2, val2, n_vars, k - 1)
            if s > best_next:
                best_next = s
    return immediate + (best_next if best_next > -1000 else 0)


def make_kstep_solver(k):
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
        if not success: return None
        if bt == 0: return False
    return True


def push_k2():
    """Push k=2 to find where it breaks on hard core."""
    print("=" * 70)
    print("  PUSHING k=2 LOOKAHEAD TO FIND FAILURE BOUNDARY")
    print("=" * 70)

    solver_k2 = make_kstep_solver(2)
    solver_k1 = make_kstep_solver(1)

    for n in [10, 12, 15, 18, 20, 25]:
        n_target = 30 if n <= 20 else 15
        found = 0
        k1_zero = 0
        k2_zero = 0
        k2_total_bt = 0
        seed = 0
        max_seed = n_target * 1000

        t_start = time.time()
        timeout = 300 if n <= 20 else 180  # generous for smaller n

        print(f"\n  n={n}: searching for hard core instances...")

        while found < n_target and seed < max_seed:
            if time.time() - t_start > timeout:
                print(f"    (timeout after {timeout}s)")
                break

            clauses = generate_random_3sat(n, 4.0, seed=seed)
            seed += 1

            hc = is_hard_core(clauses, n)
            if hc is None or not hc:
                continue
            found += 1

            # k=1 for comparison
            _, bt1 = solver_k1(clauses, n)
            if bt1 == 0: k1_zero += 1

            # k=2 — the main event
            t0 = time.time()
            success, bt2 = solver_k2(clauses, n)
            elapsed = time.time() - t0
            k2_total_bt += bt2
            if bt2 == 0:
                k2_zero += 1
            else:
                # FOUND A FAILURE — this is gold
                print(f"    *** k=2 FAILED at instance #{found}, seed={seed-1}, bt={bt2}, took {elapsed:.1f}s")

            if elapsed > 60:
                print(f"    (single instance too slow: {elapsed:.1f}s, stopping)")
                break

            if found % 5 == 0:
                elapsed_total = time.time() - t_start
                rate = k2_zero / found * 100
                print(f"    progress: {found}/{n_target}, k2={k2_zero}/{found} ({rate:.0f}%), {elapsed_total:.0f}s elapsed")

        if found > 0:
            k1_rate = k1_zero / found * 100
            k2_rate = k2_zero / found * 100
            k2_avg = k2_total_bt / found
            print(f"\n  n={n} RESULT: {found} hard core instances")
            print(f"    k=1: {k1_zero}/{found} = {k1_rate:.1f}% zero-BT")
            print(f"    k=2: {k2_zero}/{found} = {k2_rate:.1f}% zero-BT, avg_bt={k2_avg:.2f}")
            if k2_rate < 100:
                print(f"    >>> k=2 BREAKS at n={n}! <<<")
            else:
                print(f"    >>> k=2 still PERFECT at n={n} <<<")
        else:
            print(f"  n={n}: no hard core instances found")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 9c: Push k=2")
    print("▓" * 70)
    push_k2()

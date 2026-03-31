"""
Optimized 2-step lookahead scaling test.
Reduce overhead: skip full 2-step on large n, use fast UP.
"""

import random
import time
from collections import Counter, defaultdict


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


def unit_propagate_fast(clauses, assignment):
    """Faster UP: work on list indices, less copying."""
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
                    if (lit > 0) == assignment[var]:
                        satisfied = True
                        break
                else:
                    simplified.append(lit)
            if satisfied:
                continue
            if not simplified:
                return assignment, clauses, True
            if len(simplified) == 1:
                var = abs(simplified[0])
                val = simplified[0] > 0
                if var in assignment:
                    if assignment[var] != val:
                        return assignment, clauses, True
                else:
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
    return unit_propagate_fast(clauses, new_a)


def score_1step_fast(clauses, assignment, var, value, n_clauses_orig):
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000, None, None
    n_forced = len(new_a) - len(assignment) - 1
    n_eliminated = len(clauses) - len(remaining)
    return n_forced + n_eliminated, new_a, remaining


def solve_2step_optimized(clauses, n_vars):
    """
    Optimized 2-step: limit 2nd-level candidates to top-K by 1-step score.
    """
    backtracks = 0
    TOP_K = 5  # only check top-K second-level candidates

    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate_fast(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None

        n_orig = len(clauses)

        # 1-step scores for all candidates
        candidates_1step = []
        for v in unassigned:
            for value in [True, False]:
                s, new_a, remaining = score_1step_fast(clauses, assignment, v, value, n_orig)
                if s > -1000:
                    candidates_1step.append((s, v, value, new_a, remaining))

        if not candidates_1step:
            # All contradict — pick any
            bv = next(iter(unassigned))
            a1 = dict(assignment); a1[bv] = True
            r = dpll([list(c) for c in clauses], a1)
            if r is not None: return r
            backtracks += 1
            a2 = dict(assignment); a2[bv] = False
            return dpll([list(c) for c in clauses], a2)

        # Sort by 1-step score, take top candidates for 2-step evaluation
        candidates_1step.sort(reverse=True)
        top_candidates = candidates_1step[:max(TOP_K, len(unassigned))]

        # 2-step: for each top candidate, measure best next yield
        best_score = -2000
        best_var = None
        best_value = True

        for s1, v, value, new_a, remaining in top_candidates:
            if not remaining:
                # Solved at this step
                best_score = s1 + 100
                best_var = v
                best_value = value
                break

            next_unassigned = get_unassigned(remaining, new_a)
            if not next_unassigned:
                best_score = s1 + 100
                best_var = v
                best_value = value
                break

            # Sample next-level: check all variables but limit to best value only
            best_next = -1000
            for v2 in next_unassigned:
                for val2 in [True, False]:
                    s2, _, _ = score_1step_fast(remaining, new_a, v2, val2, len(remaining))
                    if s2 > best_next:
                        best_next = s2

            total = s1 + (best_next if best_next > -1000 else 0)
            if total > best_score:
                best_score = total
                best_var = v
                best_value = value

        a1 = dict(assignment); a1[best_var] = best_value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None: return result
        backtracks += 1
        a2 = dict(assignment); a2[best_var] = not best_value
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_jw(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate_fast(clauses, assignment)
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


if __name__ == "__main__":
    import sys
    sys.setrecursionlimit(10000)

    print("=" * 60)
    print("  2-STEP LOOKAHEAD SCALING TEST")
    print("=" * 60)

    for n_vars in [15, 20, 25, 30, 35, 40, 50]:
        target = 50 if n_vars <= 30 else 30 if n_vars <= 40 else 20
        found = 0; seed = 0
        jw_zero = 0; jw_bt = 0
        ts_zero = 0; ts_bt = 0
        t_jw = 0; t_ts = 0

        while found < target and seed < 10000:
            clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
            seed += 1

            t0 = time.time()
            success, bt = solve_jw(clauses, n_vars)
            t_jw += time.time() - t0
            if not success:
                continue
            found += 1
            jw_bt += bt
            if bt == 0: jw_zero += 1

            t0 = time.time()
            _, bt2 = solve_2step_optimized(clauses, n_vars)
            t_ts += time.time() - t0
            ts_bt += bt2
            if bt2 == 0: ts_zero += 1

        jw_pct = jw_zero/found*100 if found else 0
        ts_pct = ts_zero/found*100 if found else 0
        jw_avg = jw_bt/found if found else 0
        ts_avg = ts_bt/found if found else 0
        print(f"  n={n_vars:>2}: JW {jw_zero:>3}/{found} ({jw_pct:>5.1f}% avg={jw_avg:>5.2f} {t_jw:>5.1f}s) | "
              f"2step {ts_zero:>3}/{found} ({ts_pct:>5.1f}% avg={ts_avg:>5.2f} {t_ts:>6.1f}s)")

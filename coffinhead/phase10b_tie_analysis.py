"""
Phase 10b: Tie-Breaking Hypothesis
====================================
Hypothesis: k fails because its scoring has NEAR-TIES at critical decisions.
k+1 succeeds because the extra depth BREAKS those ties.

Test: at the first decision point, measure the score gap between the
best candidate and the runner-up for each k. Do failures correlate
with small gaps?
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep, solve_traced
)
from collections import defaultdict
import time


def first_decision_gap(clauses, n_vars, k):
    """
    Score all candidates at the first decision with k-step lookahead.
    Return (gap between #1 and #2, chosen_var, chosen_val, backtracks).
    """
    assignment, clauses, contradiction = unit_propagate(clauses, {})
    if contradiction:
        return None
    if not clauses:
        return None

    unassigned = get_unassigned(clauses, assignment)
    if not unassigned:
        return None

    candidates = []
    for v in sorted(unassigned):
        for value in [True, False]:
            s = score_kstep(clauses, assignment, v, value, n_vars, k)
            candidates.append((s, v, value))
    candidates.sort(reverse=True)

    # Filter out contradictions
    safe = [(s, v, val) for s, v, val in candidates if s > -1000]
    if len(safe) < 2:
        return None

    gap = safe[0][0] - safe[1][0]
    best_s, best_v, best_val = safe[0]

    # Now solve to count backtracks
    clauses2 = [list(c) for c in clauses]  # deep copy for solver
    # Quick solve just to count backtracks
    bt = [0]
    def dpll(clauses, assignment):
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None
        cands = []
        for v in sorted(unassigned):
            for value in [True, False]:
                s = score_kstep(clauses, assignment, v, value, n_vars, k)
                cands.append((s, v, value))
        cands.sort(reverse=True)
        bv, bval = None, True
        for s, v, val in cands:
            if s > -1000: bv, bval = v, val; break
        if bv is None: bv = next(iter(unassigned)); bval = True
        a1 = dict(assignment); a1[bv] = bval
        r = dpll([list(c) for c in clauses], a1)
        if r: return r
        bt[0] += 1
        a2 = dict(assignment); a2[bv] = not bval
        return dpll([list(c) for c in clauses], a2)

    # Actually we already have the full solver — use it
    return {
        'gap': gap,
        'best_score': best_s,
        'second_score': safe[1][0],
        'best_var': best_v,
        'best_val': best_val,
        'n_safe': len(safe),
        'n_tied': sum(1 for s, _, _ in safe if abs(s - safe[0][0]) < 1),
    }


def score_gap_analysis(n_vars, k, n_target=50):
    """
    For a batch of hard core instances, measure the first-decision score gap
    and correlate with whether the solver backtracks.
    """
    from phase10_dissection import propagate_and_simplify

    print(f"\n{'='*70}")
    print(f"  SCORE GAP ANALYSIS: n={n_vars}, k={k}")
    print(f"{'='*70}")

    # We need to check if instances are hard core
    def is_hard_core_py(clauses, n_vars):
        """Quick hard core check using JW and polarity."""
        from collections import defaultdict
        # JW solver
        bt_jw = [0]
        def dpll_jw(clauses, assignment):
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
            r = dpll_jw([list(c) for c in clauses], a1)
            if r: return r
            bt_jw[0] += 1
            a2 = dict(assignment); a2[bv] = not val
            return dpll_jw([list(c) for c in clauses], a2)

        r = dpll_jw([list(c) for c in clauses], {})
        if r is None: return None  # UNSAT
        if bt_jw[0] == 0: return False  # easy
        return True  # hard core

    gap_bt0 = []  # gaps for zero-backtrack instances
    gap_bt_pos = []  # gaps for positive-backtrack instances

    found = 0
    seed = 0
    t0 = time.time()

    while found < n_target and seed < n_target * 500:
        if time.time() - t0 > 120:
            print(f"  (timeout)")
            break

        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1
        if not is_hard_core_py(clauses, n_vars):
            continue
        found += 1

        # Get first decision gap for k
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed - 1)
        gap_info = first_decision_gap(clauses, n_vars, k)
        if gap_info is None:
            continue

        # Solve to get backtrack count
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed - 1)
        _, bt, _ = solve_traced(clauses, n_vars, k, verbose=False)

        if bt == 0:
            gap_bt0.append(gap_info)
        else:
            gap_bt_pos.append(gap_info)

        if found % 10 == 0:
            print(f"  progress: {found}/{n_target}")

    print(f"\n  Results: {len(gap_bt0)} zero-BT, {len(gap_bt_pos)} positive-BT")

    if gap_bt0:
        avg_gap_0 = sum(g['gap'] for g in gap_bt0) / len(gap_bt0)
        avg_tied_0 = sum(g['n_tied'] for g in gap_bt0) / len(gap_bt0)
        print(f"\n  ZERO-BACKTRACK instances:")
        print(f"    avg first-decision gap: {avg_gap_0:.1f}")
        print(f"    avg tied-for-first:     {avg_tied_0:.1f}")
        print(f"    gap distribution: {sorted([g['gap'] for g in gap_bt0])}")

    if gap_bt_pos:
        avg_gap_pos = sum(g['gap'] for g in gap_bt_pos) / len(gap_bt_pos)
        avg_tied_pos = sum(g['n_tied'] for g in gap_bt_pos) / len(gap_bt_pos)
        print(f"\n  POSITIVE-BACKTRACK instances:")
        print(f"    avg first-decision gap: {avg_gap_pos:.1f}")
        print(f"    avg tied-for-first:     {avg_tied_pos:.1f}")
        print(f"    gap distribution: {sorted([g['gap'] for g in gap_bt_pos])}")

    if gap_bt0 and gap_bt_pos:
        print(f"\n  GAP RATIO (zero_bt / pos_bt): {avg_gap_0:.1f} / {avg_gap_pos:.1f} = {avg_gap_0/avg_gap_pos:.2f}")
        print(f"  TIE RATIO (pos_bt / zero_bt): {avg_tied_pos:.1f} / {avg_tied_0:.1f} = {avg_tied_pos/avg_tied_0:.2f}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 10b: TIE-BREAKING HYPOTHESIS")
    print("▓" * 70)

    # k=2 at n=18 (where it starts breaking)
    score_gap_analysis(18, k=2, n_target=40)

    # k=2 at n=15 (where it's perfect) for comparison
    score_gap_analysis(15, k=2, n_target=40)

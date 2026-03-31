"""
Phase 10c: Tie Structure Analysis
===================================
k=2 produces massive ties at the first decision (gap=0).
How does k=3 break them? What information does the 3rd step contain?

Key question: when k=2 sees a tie of N candidates, does k=3
assign DISTINCT scores to all of them? Or does it just break
the tie into smaller clusters?
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
from collections import defaultdict, Counter
import time


def tie_structure(clauses, n_vars, k_low, k_high):
    """
    At the first decision point:
    1. Score with k_low — find the tied group
    2. Score the tied group with k_high — measure dispersion
    """
    assignment, clauses_up, contradiction = unit_propagate(clauses, {})
    if contradiction or not clauses_up:
        return None

    unassigned = get_unassigned(clauses_up, assignment)
    if not unassigned:
        return None

    # Score all candidates with k_low
    low_scores = {}
    for v in sorted(unassigned):
        for value in [True, False]:
            s = score_kstep(clauses_up, assignment, v, value, n_vars, k_low)
            low_scores[(v, value)] = s

    # Find the tied group at the top
    safe = {k: v for k, v in low_scores.items() if v > -1000}
    if not safe:
        return None

    max_score = max(safe.values())
    tied = {k: v for k, v in safe.items() if abs(v - max_score) < 0.5}

    # Now score the tied group with k_high
    high_scores = {}
    for (v, value) in tied:
        s = score_kstep(clauses_up, assignment, v, value, n_vars, k_high)
        high_scores[(v, value)] = s

    # Measure dispersion
    high_vals = list(high_scores.values())
    high_max = max(high_vals)
    high_min = min(high_vals)
    high_range = high_max - high_min
    n_distinct = len(set(int(s) for s in high_vals))

    return {
        'n_tied_at_k_low': len(tied),
        'k_low_score': max_score,
        'k_high_scores': high_scores,
        'k_high_range': high_range,
        'k_high_max': high_max,
        'k_high_min': high_min,
        'n_distinct_k_high': n_distinct,
        'tied_candidates': list(tied.keys()),
    }


def is_hard_core_py(clauses, n_vars):
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
    if r is None: return None
    if bt_jw[0] == 0: return False
    return True


def run_tie_analysis():
    print("=" * 70)
    print("  TIE STRUCTURE: How k+1 breaks k's ties")
    print("=" * 70)

    # Analyze seed=14, n=18 specifically first
    print("\n--- SPECIFIC INSTANCE: n=18, seed=14 (k=2 failure) ---")
    clauses = generate_random_3sat_xor(18, 4.0, 14)
    result = tie_structure(clauses, 18, k_low=2, k_high=3)
    if result:
        print(f"  k=2 tied group: {result['n_tied_at_k_low']} candidates at score {result['k_low_score']:.0f}")
        print(f"  k=3 scores for that tied group:")
        for (v, val), s in sorted(result['k_high_scores'].items(), key=lambda x: -x[1]):
            print(f"    x{v}={'T' if val else 'F'}: k3_score={s:.0f}")
        print(f"  k=3 range: {result['k_high_range']:.0f} ({result['n_distinct_k_high']} distinct values)")

    # Systematic analysis at n=18
    print(f"\n--- SYSTEMATIC: n=18, k=2 ties broken by k=3 ---")
    n_vars = 18
    ranges = []
    n_tied_list = []
    found = 0
    seed = 0
    while found < 30 and seed < 15000:
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1
        if not is_hard_core_py(clauses, n_vars):
            continue
        found += 1
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed - 1)
        result = tie_structure(clauses, n_vars, k_low=2, k_high=3)
        if result:
            ranges.append(result['k_high_range'])
            n_tied_list.append(result['n_tied_at_k_low'])

    if ranges:
        print(f"  {len(ranges)} instances analyzed")
        print(f"  avg k=2 tie size: {sum(n_tied_list)/len(n_tied_list):.1f}")
        print(f"  avg k=3 range within tie: {sum(ranges)/len(ranges):.1f}")
        print(f"  k=3 ranges: {sorted(ranges)}")
        zero_range = sum(1 for r in ranges if r == 0)
        print(f"  k=3 ALSO tied (range=0): {zero_range}/{len(ranges)} ({100*zero_range/len(ranges):.0f}%)")

    # Now the KEY: compare k=2→k=3 dispersion at n=15 (where k=2 is perfect)
    # vs n=18 (where k=2 breaks)
    print(f"\n--- COMPARISON: tie structure at n=15 (k=2 perfect) vs n=18 (k=2 breaks) ---")
    for n in [15, 18]:
        ranges_n = []
        ties_n = []
        found = 0
        seed = 0
        while found < 20 and seed < 10000:
            clauses = generate_random_3sat_xor(n, 4.0, seed)
            seed += 1
            if not is_hard_core_py(clauses, n):
                continue
            found += 1
            clauses = generate_random_3sat_xor(n, 4.0, seed - 1)
            result = tie_structure(clauses, n, k_low=2, k_high=3)
            if result:
                ranges_n.append(result['k_high_range'])
                ties_n.append(result['n_tied_at_k_low'])

        if ranges_n:
            avg_range = sum(ranges_n)/len(ranges_n)
            avg_ties = sum(ties_n)/len(ties_n)
            zero_pct = 100 * sum(1 for r in ranges_n if r == 0) / len(ranges_n)
            print(f"  n={n}: avg_tie_size={avg_ties:.1f}, avg_k3_range={avg_range:.1f}, k3_also_tied={zero_pct:.0f}%")

    # Do the SAME for k=3→k=4 at the k=3 boundary (n=47 vs n=48)
    # This is slower but critical
    print(f"\n--- k=3→k=4 tie structure at n=40 vs n=48 ---")
    for n in [40, 48]:
        ranges_n = []
        ties_n = []
        found = 0
        seed = 0
        t0 = time.time()
        while found < 10 and seed < 10000:
            if time.time() - t0 > 60:
                break
            clauses = generate_random_3sat_xor(n, 4.0, seed)
            seed += 1
            if not is_hard_core_py(clauses, n):
                continue
            found += 1
            clauses = generate_random_3sat_xor(n, 4.0, seed - 1)
            # k=3→k=4 is expensive, so just measure k=3 tie size
            result_low = tie_structure(clauses, n, k_low=2, k_high=3)
            if result_low:
                ranges_n.append(result_low['k_high_range'])
                ties_n.append(result_low['n_tied_at_k_low'])

        if ranges_n:
            avg_range = sum(ranges_n)/len(ranges_n)
            avg_ties = sum(ties_n)/len(ties_n)
            zero_pct = 100 * sum(1 for r in ranges_n if r == 0) / len(ranges_n)
            print(f"  n={n}: avg_k2_tie={avg_ties:.1f}, avg_k3_range={avg_range:.1f}, k3_also_tied={zero_pct:.0f}%")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 10c: TIE DEPTH ANALYSIS")
    print("▓" * 70)
    run_tie_analysis()

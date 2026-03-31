"""
Phase 10d: Ranking Reshuffle Analysis
=======================================
The tie-breaking hypothesis is WRONG. k+1 doesn't break k's ties —
it completely reshuffles the candidate ranking. Candidates that were
mediocre at depth k become top-ranked at depth k+1.

Measure: rank correlation between k and k+1 scoring.
If highly correlated: k+1 is just a refinement (tie-breaking).
If weakly correlated: k+1 sees fundamentally different information.
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
from collections import defaultdict
import time


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


def rank_correlation(scores1, scores2, candidates):
    """Spearman rank correlation between two scoring functions."""
    # Rank each
    sorted1 = sorted(candidates, key=lambda c: -scores1[c])
    sorted2 = sorted(candidates, key=lambda c: -scores2[c])
    rank1 = {c: i for i, c in enumerate(sorted1)}
    rank2 = {c: i for i, c in enumerate(sorted2)}
    n = len(candidates)
    if n < 3:
        return None
    # Spearman: 1 - 6*sum(d^2) / (n*(n^2-1))
    d_sq_sum = sum((rank1[c] - rank2[c])**2 for c in candidates)
    rho = 1 - 6 * d_sq_sum / (n * (n**2 - 1))
    return rho


def scoring_landscape(clauses, n_vars, k_values):
    """Score all candidates at first decision with multiple k values."""
    assignment, clauses_up, contradiction = unit_propagate(clauses, {})
    if contradiction or not clauses_up:
        return None

    unassigned = get_unassigned(clauses_up, assignment)
    if not unassigned:
        return None

    candidates = []
    for v in sorted(unassigned):
        for value in [True, False]:
            candidates.append((v, value))

    all_scores = {}
    for k in k_values:
        scores = {}
        for (v, value) in candidates:
            s = score_kstep(clauses_up, assignment, v, value, n_vars, k)
            scores[(v, value)] = s
        all_scores[k] = scores

    # Filter out candidates that contradict under any k
    safe = [c for c in candidates
            if all(all_scores[k][c] > -1000 for k in k_values)]

    return {
        'candidates': safe,
        'scores': all_scores,
        'n_total': len(candidates),
        'n_safe': len(safe),
    }


def reshuffle_analysis():
    print("=" * 70)
    print("  RANKING RESHUFFLE: Correlation between k and k+1")
    print("=" * 70)

    # Specific instance first
    print("\n--- INSTANCE: n=18, seed=14 ---")
    clauses = generate_random_3sat_xor(18, 4.0, 14)
    result = scoring_landscape(clauses, 18, [1, 2, 3])
    if result:
        safe = result['candidates']
        scores = result['scores']

        # Show top 10 for each k
        for k in [1, 2, 3]:
            ranked = sorted(safe, key=lambda c: -scores[k][c])
            print(f"\n  k={k} top 10:")
            for i, (v, val) in enumerate(ranked[:10]):
                val_str = "T" if val else "F"
                # What rank does this have under other k values?
                other_ranks = {}
                for kk in [1, 2, 3]:
                    if kk != k:
                        r = sorted(safe, key=lambda c: -scores[kk][c])
                        other_ranks[kk] = r.index((v, val)) + 1
                other_str = ", ".join(f"k{kk}:#{r}" for kk, r in sorted(other_ranks.items()))
                print(f"    #{i+1}: x{v}={val_str} score={scores[k][(v,val)]:.0f}  ({other_str})")

        # Rank correlations
        print(f"\n  Rank correlations:")
        for k1, k2 in [(1,2), (2,3), (1,3)]:
            rho = rank_correlation(scores[k1], scores[k2], safe)
            if rho is not None:
                print(f"    k={k1} vs k={k2}: rho = {rho:.3f}")

    # Systematic over many instances
    print(f"\n{'='*70}")
    print(f"  SYSTEMATIC RANK CORRELATION")
    print(f"{'='*70}")

    for n in [12, 15, 18]:
        correlations_12 = []
        correlations_23 = []
        found = 0
        seed = 0
        t0 = time.time()
        while found < 20 and seed < 10000:
            if time.time() - t0 > 60:
                break
            clauses = generate_random_3sat_xor(n, 4.0, seed)
            seed += 1
            if not is_hard_core_py(clauses, n):
                continue
            found += 1
            clauses = generate_random_3sat_xor(n, 4.0, seed - 1)
            result = scoring_landscape(clauses, n, [1, 2, 3])
            if result and len(result['candidates']) >= 5:
                rho12 = rank_correlation(result['scores'][1], result['scores'][2],
                                         result['candidates'])
                rho23 = rank_correlation(result['scores'][2], result['scores'][3],
                                         result['candidates'])
                if rho12 is not None:
                    correlations_12.append(rho12)
                if rho23 is not None:
                    correlations_23.append(rho23)

        if correlations_12:
            avg12 = sum(correlations_12)/len(correlations_12)
            avg23 = sum(correlations_23)/len(correlations_23)
            print(f"\n  n={n} ({found} hard core instances):")
            print(f"    k=1 vs k=2 rank correlation: {avg12:.3f} (avg of {len(correlations_12)})")
            print(f"    k=2 vs k=3 rank correlation: {avg23:.3f} (avg of {len(correlations_23)})")
            print(f"    k=1→2 reshuffle: {1-avg12:.3f}")
            print(f"    k=2→3 reshuffle: {1-avg23:.3f}")

    # The critical question: does k→k+1 CHOOSE DIFFERENTLY?
    print(f"\n{'='*70}")
    print(f"  CHOICE DIVERGENCE: How often does k+1 pick a different candidate?")
    print(f"{'='*70}")

    for n in [12, 15, 18]:
        same_12 = 0
        same_23 = 0
        total = 0
        seed = 0
        found = 0
        t0 = time.time()
        while found < 30 and seed < 10000:
            if time.time() - t0 > 60:
                break
            clauses = generate_random_3sat_xor(n, 4.0, seed)
            seed += 1
            if not is_hard_core_py(clauses, n):
                continue
            found += 1
            clauses = generate_random_3sat_xor(n, 4.0, seed - 1)
            result = scoring_landscape(clauses, n, [1, 2, 3])
            if not result or not result['candidates']:
                continue
            total += 1
            safe = result['candidates']
            scores = result['scores']

            best_1 = max(safe, key=lambda c: scores[1][c])
            best_2 = max(safe, key=lambda c: scores[2][c])
            best_3 = max(safe, key=lambda c: scores[3][c])

            if best_1 == best_2:
                same_12 += 1
            if best_2 == best_3:
                same_23 += 1

        if total > 0:
            print(f"  n={n}: k1→k2 same choice: {same_12}/{total} ({100*same_12/total:.0f}%)")
            print(f"         k2→k3 same choice: {same_23}/{total} ({100*same_23/total:.0f}%)")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 10d: RANKING RESHUFFLE ANALYSIS")
    print("▓" * 70)
    reshuffle_analysis()

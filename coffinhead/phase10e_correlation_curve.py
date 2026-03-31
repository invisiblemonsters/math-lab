"""
Phase 10e: Correlation Decay Curve
====================================
Measure rho(k, k+1, n) across many n values.
This is the fundamental curve. Its shape determines everything.

If rho decays as ~1/n: each step adds O(1) bits, need k=O(n) — exponential
If rho decays as ~1/sqrt(n): each step adds O(sqrt(n)) bits, need k=O(sqrt(n)) — subexp  
If rho decays as ~1/log(n): each step adds O(n/log(n)) bits, need k=O(log(n)) — polynomial
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
from collections import defaultdict
import time
import math


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
    sorted1 = sorted(candidates, key=lambda c: -scores1[c])
    sorted2 = sorted(candidates, key=lambda c: -scores2[c])
    rank1 = {c: i for i, c in enumerate(sorted1)}
    rank2 = {c: i for i, c in enumerate(sorted2)}
    n = len(candidates)
    if n < 3: return None
    d_sq_sum = sum((rank1[c] - rank2[c])**2 for c in candidates)
    rho = 1 - 6 * d_sq_sum / (n * (n**2 - 1))
    return rho


def measure_rho(n_vars, k1, k2, n_target=15):
    """Measure average rank correlation between k1 and k2 scoring on hard core."""
    correlations = []
    found = 0
    seed = 0
    t0 = time.time()

    while found < n_target and seed < n_target * 500:
        if time.time() - t0 > 90:
            break
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1
        if not is_hard_core_py(clauses, n_vars):
            continue
        found += 1

        clauses = generate_random_3sat_xor(n_vars, 4.0, seed - 1)
        assignment, clauses_up, contradiction = unit_propagate(clauses, {})
        if contradiction or not clauses_up:
            continue
        unassigned = get_unassigned(clauses_up, assignment)
        if len(unassigned) < 5:
            continue

        candidates = [(v, val) for v in sorted(unassigned) for val in [True, False]]
        
        scores_k1 = {}
        scores_k2 = {}
        for (v, val) in candidates:
            scores_k1[(v, val)] = score_kstep(clauses_up, assignment, v, val, n_vars, k1)
            scores_k2[(v, val)] = score_kstep(clauses_up, assignment, v, val, n_vars, k2)

        safe = [c for c in candidates if scores_k1[c] > -1000 and scores_k2[c] > -1000]
        if len(safe) < 5:
            continue

        rho = rank_correlation(scores_k1, scores_k2, safe)
        if rho is not None:
            correlations.append(rho)

    return correlations


def main():
    print("=" * 70)
    print("  CORRELATION DECAY CURVE: rho(k, k+1) vs n")
    print("=" * 70)

    # k=1 vs k=2 correlation across n
    print("\n  rho(1,2) — how much k=2 reshuffles k=1's ranking:")
    print(f"  {'n':>4} {'rho':>8} {'samples':>8}")
    print(f"  {'─'*4} {'─'*8} {'─'*8}")
    rho_12 = {}
    for n in [7, 8, 9, 10, 12, 15, 18, 20, 25]:
        corrs = measure_rho(n, 1, 2, n_target=15)
        if corrs:
            avg = sum(corrs) / len(corrs)
            rho_12[n] = avg
            print(f"  {n:>4} {avg:>8.3f} {len(corrs):>8}")

    # k=2 vs k=3 — this is the critical one
    print(f"\n  rho(2,3) — how much k=3 reshuffles k=2's ranking:")
    print(f"  {'n':>4} {'rho':>8} {'samples':>8}")
    print(f"  {'─'*4} {'─'*8} {'─'*8}")
    rho_23 = {}
    for n in [7, 8, 9, 10, 12, 15, 18, 20, 25]:
        corrs = measure_rho(n, 2, 3, n_target=12)
        if corrs:
            avg = sum(corrs) / len(corrs)
            rho_23[n] = avg
            print(f"  {n:>4} {avg:>8.3f} {len(corrs):>8}")

    # Fit the decay
    print(f"\n{'='*70}")
    print(f"  DECAY MODEL FITTING")
    print(f"{'='*70}")

    if len(rho_23) >= 3:
        ns = sorted(rho_23.keys())
        rhos = [rho_23[n] for n in ns]

        # Model 1: rho = a/n + b (linear decay → k=O(n))
        # Model 2: rho = a/sqrt(n) + b (sqrt decay → k=O(sqrt(n)))
        # Model 3: rho = a/log(n) + b (log decay → k=O(log(n)))

        # Simple: check if rho * n is constant (model 1)
        #         or rho * sqrt(n) is constant (model 2)
        #         or rho * log(n) is constant (model 3)

        print(f"\n  Checking decay models for rho(2,3):")
        print(f"  {'n':>4} {'rho':>8} {'rho*n':>8} {'rho*sqrt(n)':>12} {'rho*log(n)':>11}")
        for n, r in zip(ns, rhos):
            print(f"  {n:>4} {r:>8.3f} {r*n:>8.2f} {r*math.sqrt(n):>12.2f} {r*math.log(n):>11.2f}")

        print(f"\n  If rho*n is constant: decay is ~1/n → k=O(n) → exponential (bad)")
        print(f"  If rho*sqrt(n) is constant: decay is ~1/sqrt(n) → k=O(sqrt(n)) → subexp")
        print(f"  If rho*log(n) is constant: decay is ~1/log(n) → k=O(log(n)) → polynomial!")
        print(f"\n  Look at which product is most constant across n values.")

    # Also measure choice agreement (same top pick)
    print(f"\n{'='*70}")
    print(f"  CHOICE AGREEMENT: k=2 vs k=3 same top pick")
    print(f"{'='*70}")
    for n in [7, 9, 12, 15, 18, 20]:
        same = 0
        total = 0
        seed = 0
        found = 0
        t0 = time.time()
        while found < 20 and seed < 10000:
            if time.time() - t0 > 60: break
            clauses = generate_random_3sat_xor(n, 4.0, seed)
            seed += 1
            if not is_hard_core_py(clauses, n): continue
            found += 1
            clauses = generate_random_3sat_xor(n, 4.0, seed-1)
            assignment, cl, contradiction = unit_propagate(clauses, {})
            if contradiction or not cl: continue
            unassigned = get_unassigned(cl, assignment)
            if not unassigned: continue
            cands = [(v, val) for v in sorted(unassigned) for val in [True, False]]
            s2 = {c: score_kstep(cl, assignment, c[0], c[1], n, 2) for c in cands}
            s3 = {c: score_kstep(cl, assignment, c[0], c[1], n, 3) for c in cands}
            safe = [c for c in cands if s2[c] > -1000 and s3[c] > -1000]
            if not safe: continue
            total += 1
            b2 = max(safe, key=lambda c: s2[c])
            b3 = max(safe, key=lambda c: s3[c])
            if b2 == b3: same += 1
        if total > 0:
            print(f"  n={n:>2}: same pick {same:>2}/{total} ({100*same/total:>5.1f}%)")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 10e: CORRELATION DECAY CURVE")
    print("▓" * 70)
    main()

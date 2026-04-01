"""
Phase 14b: Is Fringe Influence Symmetric?
==========================================
Key insight from Phase 14: per-variable influence is large (O(n)),
BUT if it shifts all candidates equally, the ranking doesn't change.

Measure: when a fringe variable is set, does it change all candidates'
scores by the same amount (symmetric), or different amounts (asymmetric)?

If symmetric: ties preserved, proof works via symmetry argument.
If asymmetric: ties broken, proof needs different approach.
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
from collections import defaultdict, deque
import time
import math


def build_graph(clauses, n_vars):
    adj = defaultdict(set)
    for clause in clauses:
        vs = [abs(l) for l in clause]
        for i in range(len(vs)):
            for j in range(i + 1, len(vs)):
                adj[vs[i]].add(vs[j])
                adj[vs[j]].add(vs[i])
    return adj


def bfs_layers(adj, start):
    dist = {start: 0}
    queue = deque([start])
    layers = defaultdict(set)
    layers[0].add(start)
    while queue:
        v = queue.popleft()
        for u in adj[v]:
            if u not in dist:
                dist[u] = dist[v] + 1
                layers[dist[u]].add(u)
                queue.append(u)
    return dict(layers), dist


def measure_symmetry(n_vars, k, n_samples=10):
    """
    For each instance + fringe variable:
    1. Score ALL candidates without fringe set
    2. Score ALL candidates with fringe set to T
    3. Measure the VARIANCE of (score_with - score_without) across candidates
    
    Low variance = symmetric (all shifted equally) → ranking preserved
    High variance = asymmetric → ranking may change
    """
    results = []
    seed = 0
    found = 0
    t0 = time.time()

    while found < n_samples and seed < n_samples * 50:
        if time.time() - t0 > 120:
            break

        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1

        adj = build_graph(clauses, n_vars)
        source = 1
        layers, dists = bfs_layers(adj, source)
        max_d = max(layers.keys()) if layers else 0
        if max_d < 2:
            continue
        fringe = list(layers[max_d])[:3]
        if not fringe:
            continue

        assignment_base, clauses_up, contradiction = unit_propagate(clauses, {})
        if contradiction or not clauses_up:
            continue
        unassigned = get_unassigned(clauses_up, assignment_base)
        if len(unassigned) < 5:
            continue

        found += 1

        # Score all candidates baseline
        candidates = [(v, val) for v in sorted(unassigned) for val in [True, False]]
        base_scores = {}
        for v, val in candidates:
            base_scores[(v, val)] = score_kstep(clauses_up, assignment_base, v, val, n_vars, k)

        # For each fringe variable
        for u in fringe:
            if u not in unassigned:
                continue

            assign_u = dict(assignment_base)
            assign_u[u] = True
            new_a, new_clauses, contradiction = unit_propagate(
                [list(c) for c in clauses_up], assign_u)
            if contradiction:
                continue

            # Score all candidates with u=T
            new_unassigned = get_unassigned(new_clauses, new_a)
            shifted_scores = {}
            for v, val in candidates:
                if v == u:
                    continue  # skip the fringe variable itself
                if v not in new_unassigned:
                    continue  # got forced by setting u
                shifted_scores[(v, val)] = score_kstep(new_clauses, new_a, v, val, n_vars, k)

            # Compute score deltas
            deltas = []
            for cand in shifted_scores:
                if cand in base_scores and base_scores[cand] > -1000 and shifted_scores[cand] > -1000:
                    deltas.append(shifted_scores[cand] - base_scores[cand])

            if len(deltas) < 3:
                continue

            mean_delta = sum(deltas) / len(deltas)
            variance = sum((d - mean_delta)**2 for d in deltas) / len(deltas)
            std_delta = math.sqrt(variance)

            # Did the ranking change?
            # Get top candidate before and after
            safe_base = {c: s for c, s in base_scores.items() if s > -1000 and c[0] != u}
            safe_shift = {c: s for c, s in shifted_scores.items() if s > -1000}
            if not safe_base or not safe_shift:
                continue

            best_before = max(safe_base, key=lambda c: safe_base[c])
            common = set(safe_base.keys()) & set(safe_shift.keys())
            if not common:
                continue
            best_after = max(common, key=lambda c: safe_shift[c])
            ranking_changed = (best_before != best_after)

            results.append({
                'n': n_vars,
                'fringe_var': u,
                'mean_delta': mean_delta,
                'std_delta': std_delta,
                'n_candidates': len(deltas),
                'ranking_changed': ranking_changed,
                'delta_range': max(deltas) - min(deltas),
            })

    return results


def main():
    print("=" * 70)
    print("  FRINGE INFLUENCE SYMMETRY")
    print("=" * 70)

    for n in [10, 15, 20, 25]:
        k = {10: 2, 15: 2, 20: 3, 25: 3}[n]
        results = measure_symmetry(n, k, n_samples=15)

        if not results:
            print(f"\n  n={n}: no data")
            continue

        avg_std = sum(r['std_delta'] for r in results) / len(results)
        avg_mean = sum(abs(r['mean_delta']) for r in results) / len(results)
        avg_range = sum(r['delta_range'] for r in results) / len(results)
        n_changed = sum(1 for r in results if r['ranking_changed'])
        n_total = len(results)

        print(f"\n  n={n} k={k}: {n_total} fringe variables tested")
        print(f"    avg |mean shift|: {avg_mean:.1f} (symmetric component)")
        print(f"    avg std of shift: {avg_std:.1f} (asymmetric component)")
        print(f"    avg range:        {avg_range:.1f}")
        print(f"    ratio std/mean:   {avg_std/avg_mean:.3f}" if avg_mean > 0 else "    ratio: N/A")
        print(f"    ranking changed:  {n_changed}/{n_total} ({100*n_changed/n_total:.0f}%)")

    print(f"\n{'='*70}")
    print(f"  CONCLUSION")
    print(f"{'='*70}")
    print("""
  If std/mean << 1: influence is mostly symmetric (all candidates shift
  together). The asymmetric residual is small → ranking preserved → proof works.

  If std/mean ≈ 1: influence is as asymmetric as it is symmetric.
  Rankings flip frequently → proof needs more work.

  The ranking_changed rate directly measures how often a single fringe
  variable can flip the top pick. If this rate × |fringe| < 1,
  then w.h.p. no fringe variable flips the winner.
""")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 14b: SYMMETRY OF FRINGE INFLUENCE")
    print("▓" * 70)
    main()

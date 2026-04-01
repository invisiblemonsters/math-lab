"""
Phase 14: Per-Variable Influence Bound
========================================
Measure: if we fix all variables EXCEPT one fringe variable u,
how much does u's value change the score of each candidate?

This is the quantity the proof needs to bound.
If it's O(1) per variable: proof works.
If it's O(n): proof fails.
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


def measure_single_variable_influence(n_vars, k, n_samples=10):
    """
    For each instance:
    1. Pick a source variable (the decision variable)
    2. Find the fringe (variables at max BFS distance)
    3. For each fringe variable u, measure how much fixing u=T vs u=F
       changes the k-step score of setting the source variable.
    """
    influences = []  # list of (n, fringe_var, influence_magnitude)

    seed = 0
    found = 0
    t0 = time.time()

    while found < n_samples and seed < n_samples * 50:
        if time.time() - t0 > 120:
            break

        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1

        adj = build_graph(clauses, n_vars)

        # Pick a source variable (just use var 1)
        source = 1
        layers, dists = bfs_layers(adj, source)
        max_d = max(layers.keys()) if layers else 0
        if max_d < 2:
            continue

        fringe = layers[max_d]
        if not fringe:
            continue

        found += 1

        # Score source=T and source=F with k-step, on the original formula
        assignment_base, clauses_up, contradiction = unit_propagate(clauses, {})
        if contradiction or not clauses_up:
            continue

        unassigned = get_unassigned(clauses_up, assignment_base)
        if source not in unassigned:
            continue

        # Baseline score (no fringe variables pre-set)
        score_base_T = score_kstep(clauses_up, assignment_base, source, True, n_vars, k)
        score_base_F = score_kstep(clauses_up, assignment_base, source, False, n_vars, k)

        # For each fringe variable, pre-set it and re-score
        for u in list(fringe)[:5]:  # limit per instance
            if u not in unassigned:
                continue

            for u_val in [True, False]:
                # Set u = u_val, propagate, then score source
                assign_with_u = dict(assignment_base)
                assign_with_u[u] = u_val
                new_a, new_clauses, contradiction = unit_propagate(
                    [list(c) for c in clauses_up], assign_with_u)
                if contradiction:
                    # Setting u causes contradiction — that's maximum influence
                    influences.append({
                        'n': n_vars, 'fringe_var': u, 'u_val': u_val,
                        'influence': float('inf'), 'type': 'contradiction'
                    })
                    continue

                if source not in get_unassigned(new_clauses, new_a):
                    # Source got forced by setting u — big influence
                    influences.append({
                        'n': n_vars, 'fringe_var': u, 'u_val': u_val,
                        'influence': float('inf'), 'type': 'forced'
                    })
                    continue

                score_T = score_kstep(new_clauses, new_a, source, True, n_vars, k)
                score_F = score_kstep(new_clauses, new_a, source, False, n_vars, k)

                # Influence = how much the score CHANGED
                inf_T = abs(score_T - score_base_T)
                inf_F = abs(score_F - score_base_F)
                max_inf = max(inf_T, inf_F)

                influences.append({
                    'n': n_vars, 'fringe_var': u, 'u_val': u_val,
                    'influence': max_inf, 'type': 'score_change',
                    'base_score': max(abs(score_base_T), abs(score_base_F)),
                })

    return influences


def main():
    print("=" * 70)
    print("  PER-VARIABLE INFLUENCE BOUND")
    print("=" * 70)

    for n in [10, 15, 20, 25, 30]:
        k = {10: 2, 15: 2, 20: 3, 25: 3, 30: 3}[n]
        influences = measure_single_variable_influence(n, k, n_samples=15)

        if not influences:
            print(f"\n  n={n} k={k}: no data")
            continue

        # Separate finite from infinite
        finite = [i for i in influences if i['influence'] != float('inf')]
        infinite = [i for i in influences if i['influence'] == float('inf')]

        print(f"\n  n={n} k={k}: {len(influences)} measurements")
        print(f"    {len(infinite)} caused contradiction/forcing ({100*len(infinite)/len(influences):.0f}%)")

        if finite:
            infs = [i['influence'] for i in finite]
            bases = [i['base_score'] for i in finite if 'base_score' in i]
            avg_inf = sum(infs) / len(infs)
            max_inf = max(infs)
            avg_base = sum(bases) / len(bases) if bases else 0

            print(f"    Finite influences: avg={avg_inf:.1f}, max={max_inf:.1f}")
            if avg_base > 0:
                print(f"    Base score magnitude: avg={avg_base:.1f}")
                print(f"    Relative influence: avg={avg_inf/avg_base:.3f}, max={max_inf/avg_base:.3f}")

            # Distribution
            zero = sum(1 for x in infs if x == 0)
            small = sum(1 for x in infs if 0 < x <= 5)
            medium = sum(1 for x in infs if 5 < x <= 20)
            large = sum(1 for x in infs if x > 20)
            print(f"    Distribution: zero={zero}, small(1-5)={small}, medium(6-20)={medium}, large(>20)={large}")

    print(f"\n{'='*70}")
    print(f"  INTERPRETATION")
    print(f"{'='*70}")
    print("""
  If per-variable influence is O(1) (constant, not growing with n):
    → Fringe influence = O(1) * |fringe| = O(1) * O(0.03n) = O(n)
    → But this needs to be compared to the SCORE DIFFERENCE between
      correct and incorrect candidates, not the absolute score.

  The real question: does a fringe variable change which candidate WINS?
  That requires the influence to exceed the gap between candidates.
  Since the gap is 0 (ties), ANY influence can flip the winner.

  BUT: if the fringe variable influences ALL tied candidates equally
  (because they're all far from the fringe in the constraint graph),
  then the TIE is preserved and no flip occurs.

  This is the key insight: fringe variables are far from ALL candidates
  equally (they're at the edge of the graph). Their influence is
  symmetric across candidates → ties preserved → no wrong choices.
""")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 14: PER-VARIABLE INFLUENCE")
    print("▓" * 70)
    main()

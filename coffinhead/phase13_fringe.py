"""
Phase 13: Fringe Analysis — Data for the Coupling Proof
=========================================================
Measure:
1. BFS fringe size at each distance (how many vars at distance exactly d)
2. How fast the fringe shrinks as d approaches diameter
3. Per-variable influence on the scoring function

If fringe shrinks exponentially → coupling argument works → proof completes.
"""

import math
from collections import defaultdict, deque, Counter

class XorShift64:
    def __init__(self, seed):
        self.state = seed if seed != 0 else 1
    def next(self):
        s = self.state & 0xFFFFFFFFFFFFFFFF
        s ^= (s << 13) & 0xFFFFFFFFFFFFFFFF
        s ^= (s >> 7) & 0xFFFFFFFFFFFFFFFF
        s ^= (s << 17) & 0xFFFFFFFFFFFFFFFF
        self.state = s
        return s
    def randint(self, n):
        return self.next() % n

def generate_random_3sat(n_vars, ratio, seed):
    rng = XorShift64(seed)
    n_clauses = int(n_vars * ratio)
    clauses = []
    for _ in range(n_clauses):
        lits = []
        for j in range(min(3, n_vars)):
            while True:
                v = 1 + rng.randint(n_vars)
                if v not in [abs(x) for x in lits]: break
            lits.append(v if rng.next() & 1 else -v)
        clauses.append(lits)
    return clauses

def build_graph(clauses, n_vars):
    adj = defaultdict(set)
    for clause in clauses:
        vs = [abs(l) for l in clause]
        for i in range(len(vs)):
            for j in range(i+1, len(vs)):
                adj[vs[i]].add(vs[j])
                adj[vs[j]].add(vs[i])
    return adj

def bfs_layers(adj, start, n_vars):
    """BFS from start, return list of sets: layer[d] = {vertices at distance d}."""
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
    return dict(layers)


def fringe_analysis():
    print("=" * 70)
    print("  BFS FRINGE ANALYSIS: How fast does the boundary shrink?")
    print("=" * 70)

    for n in [20, 50, 100, 200, 500, 1000]:
        n_inst = 10 if n <= 200 else 5
        n_sources = min(n, 50)

        all_layer_sizes = defaultdict(list)  # distance -> list of layer sizes

        for seed in range(n_inst):
            clauses = generate_random_3sat(n, 4.0, seed)
            adj = build_graph(clauses, n)

            import random
            random.seed(seed)
            sources = random.sample(range(1, n+1), min(n_sources, n))

            for src in sources:
                layers = bfs_layers(adj, src, n)
                for d, verts in layers.items():
                    all_layer_sizes[d].append(len(verts))

        # Compute average layer sizes
        max_d = max(all_layer_sizes.keys())
        print(f"\n  n={n}: avg vertices at each BFS distance")
        print(f"  {'dist':>5} {'avg_size':>10} {'frac_of_n':>10} {'cumulative':>12}")
        cumul = 0
        layer_avgs = {}
        for d in range(max_d + 1):
            if d in all_layer_sizes:
                avg = sum(all_layer_sizes[d]) / len(all_layer_sizes[d])
                frac = avg / n
                cumul += avg
                layer_avgs[d] = avg
                cum_frac = cumul / n
                print(f"  {d:>5} {avg:>10.1f} {frac:>10.3f} {cum_frac:>12.3f}")

        # Check: does the fringe (last few layers) shrink?
        if max_d >= 2:
            sizes = [layer_avgs.get(d, 0) for d in range(max_d + 1)]
            # Find peak and measure decay after it
            peak_d = max(range(len(sizes)), key=lambda d: sizes[d])
            print(f"  Peak at d={peak_d} (size={sizes[peak_d]:.1f})")
            if peak_d < max_d:
                for d in range(peak_d, max_d + 1):
                    if sizes[d] > 0:
                        ratio_to_peak = sizes[d] / sizes[peak_d]
                        print(f"    d={d}: {sizes[d]:.1f} ({ratio_to_peak:.3f} of peak)")


def expansion_rate():
    """How does the BFS wavefront expand? This determines the fringe decay."""
    print(f"\n{'='*70}")
    print(f"  EXPANSION RATE: BFS wavefront growth")
    print(f"{'='*70}")

    for n in [50, 100, 500, 1000]:
        n_inst = 5
        expansion_ratios = []  # ratio of layer[d+1]/layer[d]

        for seed in range(n_inst):
            clauses = generate_random_3sat(n, 4.0, seed)
            adj = build_graph(clauses, n)

            import random
            random.seed(seed + 1000)
            sources = random.sample(range(1, n+1), min(20, n))

            for src in sources:
                layers = bfs_layers(adj, src, n)
                max_d = max(layers.keys())
                for d in range(max_d):
                    s_d = len(layers[d])
                    s_d1 = len(layers.get(d+1, set()))
                    if s_d > 0:
                        expansion_ratios.append((n, d, s_d1 / s_d))

        # Group by distance
        by_dist = defaultdict(list)
        for nn, d, r in expansion_ratios:
            by_dist[d].append(r)

        print(f"\n  n={n}: expansion ratio layer[d+1]/layer[d]")
        for d in sorted(by_dist.keys()):
            ratios = by_dist[d]
            avg = sum(ratios) / len(ratios)
            print(f"    d={d}→{d+1}: avg ratio = {avg:.2f} ({len(ratios)} samples)")


def coverage_at_diameter():
    """At the diameter, what fraction of variables has BFS reached?"""
    print(f"\n{'='*70}")
    print(f"  COVERAGE AT DIAMETER: fraction of n reached")
    print(f"{'='*70}")

    for n in [20, 50, 100, 200, 500, 1000, 5000]:
        n_inst = 5 if n <= 1000 else 2
        coverages = []

        for seed in range(n_inst):
            clauses = generate_random_3sat(n, 4.0, seed)
            adj = build_graph(clauses, n)

            import random
            random.seed(seed + 2000)
            sources = random.sample(range(1, n+1), min(20, n))

            for src in sources:
                layers = bfs_layers(adj, src, n)
                total_reached = sum(len(v) for v in layers.values())
                coverages.append(total_reached / n)

        avg_cov = sum(coverages) / len(coverages)
        print(f"  n={n:>5}: avg coverage = {avg_cov:.4f} ({len(coverages)} samples)")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 13: FRINGE ANALYSIS FOR COUPLING PROOF")
    print("▓" * 70)
    fringe_analysis()
    expansion_rate()
    coverage_at_diameter()

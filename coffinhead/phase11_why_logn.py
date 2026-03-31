"""
THE COFFINHEAD CONJECTURE — Phase 11: Why k = O(log n)
=======================================================
The argument:

1. A SAT formula defines a constraint graph (variables connected if they
   share a clause). Random 3-SAT at ratio 4.0 produces an expander-like
   graph with diameter O(log n).

2. k-step lookahead simulates k decisions. Each decision triggers a
   unit propagation cascade that reaches some "radius" in the constraint
   graph. The effective information radius is k * cascade_reach.

3. When the information radius covers the entire graph (reaches diameter),
   the scorer has enough global information to make correct decisions.

4. If diameter = O(log n) and cascade_reach = O(1), then
   k = O(log n / 1) = O(log n) suffices.

This script MEASURES all these quantities on real instances to verify.
"""

import math
from collections import defaultdict, deque


# ─── Xorshift64 RNG (matches C solver) ───

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
        clen = min(3, n_vars)
        lits = []
        for j in range(clen):
            while True:
                v = 1 + rng.randint(n_vars)
                if v not in [abs(x) for x in lits]:
                    break
            if rng.next() & 1:
                lits.append(v)
            else:
                lits.append(-v)
        clauses.append(lits)
    return clauses


# ─── Constraint graph analysis ───

def build_constraint_graph(clauses, n_vars):
    """Build variable interaction graph: edge between v1,v2 if they share a clause."""
    adj = defaultdict(set)
    for clause in clauses:
        vars_in_clause = [abs(l) for l in clause]
        for i in range(len(vars_in_clause)):
            for j in range(i + 1, len(vars_in_clause)):
                adj[vars_in_clause[i]].add(vars_in_clause[j])
                adj[vars_in_clause[j]].add(vars_in_clause[i])
    return adj


def bfs_distances(adj, start, n_vars):
    """BFS from start, return distances to all reachable nodes."""
    dist = {start: 0}
    queue = deque([start])
    while queue:
        v = queue.popleft()
        for u in adj[v]:
            if u not in dist:
                dist[u] = dist[v] + 1
                queue.append(u)
    return dist


def graph_diameter(adj, n_vars):
    """Exact diameter (max shortest path between any two vertices)."""
    max_dist = 0
    for v in range(1, n_vars + 1):
        if v not in adj:
            continue
        dists = bfs_distances(adj, v, n_vars)
        if dists:
            max_dist = max(max_dist, max(dists.values()))
    return max_dist


def avg_distance(adj, n_vars):
    """Average shortest path length."""
    total = 0
    count = 0
    # Sample for large n
    sample = list(range(1, n_vars + 1))
    if n_vars > 50:
        import random
        random.seed(42)
        sample = random.sample(sample, min(50, n_vars))
    for v in sample:
        if v not in adj:
            continue
        dists = bfs_distances(adj, v, n_vars)
        for d in dists.values():
            if d > 0:
                total += d
                count += 1
    return total / count if count > 0 else 0


# ─── Propagation cascade analysis ───

def unit_propagate(clauses, assignment):
    assignment = dict(assignment)
    forced_count = 0
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
                return assignment, clauses, True, forced_count
            if len(simplified) == 1:
                unit_lit = simplified[0]
                var = abs(unit_lit)
                val = unit_lit > 0
                if var in assignment and assignment[var] != val:
                    return assignment, clauses, True, forced_count
                if var not in assignment:
                    assignment[var] = val
                    forced_count += 1
                    changed = True
            new_clauses.append(simplified)
        clauses = new_clauses
    return assignment, clauses, False, forced_count


def measure_cascade_reach(clauses, n_vars, adj, n_samples=50):
    """
    For random variable assignments, measure how far propagation reaches
    in the constraint graph. This is the "cascade radius" per decision.
    """
    import random
    random.seed(42)

    reaches = []
    for _ in range(n_samples):
        # Pick a random unassigned variable
        var = random.randint(1, n_vars)
        val = random.choice([True, False])

        # Propagate
        assignment = {var: val}
        new_assign, _, contradiction, forced = unit_propagate(
            [list(c) for c in clauses], assignment)

        if contradiction:
            continue

        # Measure graph distance from var to each forced variable
        forced_vars = [v for v in new_assign if v != var]
        if not forced_vars:
            reaches.append(0)
            continue

        dists = bfs_distances(adj, var, n_vars)
        max_reach = 0
        for fv in forced_vars:
            if fv in dists:
                max_reach = max(max_reach, dists[fv])
        reaches.append(max_reach)

    return reaches


def measure_propagation_depth(clauses, n_vars, n_samples=100):
    """
    How many variables get forced by a single decision?
    This is the "propagation yield" — how much work one decision does.
    """
    import random
    random.seed(42)
    yields = []
    for _ in range(n_samples):
        var = random.randint(1, n_vars)
        val = random.choice([True, False])
        assignment = {var: val}
        new_assign, _, contradiction, forced = unit_propagate(
            [list(c) for c in clauses], assignment)
        if not contradiction:
            yields.append(forced)
    return yields


# ─── Main analysis ───

def analyze_scaling():
    print("=" * 70)
    print("  WHY k = O(log n): Constraint Graph + Cascade Reach")
    print("=" * 70)

    # Measure graph properties across problem sizes
    print(f"\n{'n':>5} {'diam':>5} {'avg_d':>6} {'log2n':>6} {'d/logn':>7}"
          f" {'casc_avg':>9} {'casc_max':>9} {'prop_avg':>9}"
          f" {'k*casc':>7} {'k_pred':>7} {'k_real':>7}")
    print("-" * 100)

    # Known perfect boundaries from our experiments
    k_boundaries = {
        # n: k needed for 100% on hard core
        10: 2, 15: 2, 18: 3, 20: 3, 25: 3, 30: 3, 40: 3, 47: 3,
        48: 4, 50: 4, 75: 5, 100: 5,
    }

    for n in [7, 10, 15, 20, 25, 30, 40, 50, 75, 100]:
        # Generate a few instances and average
        diameters = []
        avg_dists = []
        cascade_avgs = []
        cascade_maxs = []
        prop_yields = []

        n_instances = 20 if n <= 50 else 10
        for seed in range(n_instances):
            clauses = generate_random_3sat(n, 4.0, seed)
            adj = build_constraint_graph(clauses, n)

            diam = graph_diameter(adj, n)
            avg_d = avg_distance(adj, n)
            diameters.append(diam)
            avg_dists.append(avg_d)

            reaches = measure_cascade_reach(clauses, n, adj, n_samples=30)
            if reaches:
                cascade_avgs.append(sum(reaches) / len(reaches))
                cascade_maxs.append(max(reaches))

            props = measure_propagation_depth(clauses, n, n_samples=30)
            if props:
                prop_yields.append(sum(props) / len(props))

        diam = sum(diameters) / len(diameters)
        avg_d = sum(avg_dists) / len(avg_dists)
        log2n = math.log2(n)
        d_over_logn = diam / log2n
        casc_avg = sum(cascade_avgs) / len(cascade_avgs) if cascade_avgs else 0
        casc_max = sum(cascade_maxs) / len(cascade_maxs) if cascade_maxs else 0
        prop_avg = sum(prop_yields) / len(prop_yields) if prop_yields else 0

        # Prediction: k needed = diameter / cascade_reach
        k_pred = diam / max(casc_avg, 0.1)
        k_real = k_boundaries.get(n, -1)

        # What k * cascade_reach gives us (effective radius)
        if k_real > 0:
            eff_radius = k_real * casc_avg
        else:
            eff_radius = -1

        k_real_str = str(k_real) if k_real > 0 else "?"
        eff_str = f"{eff_radius:.1f}" if eff_radius > 0 else "?"

        print(f"{n:>5} {diam:>5.1f} {avg_d:>6.2f} {log2n:>6.2f} {d_over_logn:>7.2f}"
              f" {casc_avg:>9.2f} {casc_max:>9.1f} {prop_avg:>9.2f}"
              f" {eff_str:>7} {k_pred:>7.1f} {k_real_str:>7}")

    print(f"\n{'='*70}")
    print(f"  INTERPRETATION")
    print(f"{'='*70}")
    print("""
  KEY COLUMNS:
  - diam: constraint graph diameter (max shortest path between any two variables)
  - log2n: log base 2 of n
  - d/logn: diameter divided by log(n) — if constant, diameter = O(log n)
  - casc_avg: average propagation reach in graph distance per decision
  - k*casc: effective information radius = k_real * cascade_reach
  - k_pred: predicted k = diameter / cascade_reach
  - k_real: actual k needed for 100% zero-BT

  THE ARGUMENT:
  1. If d/logn is approximately constant → diameter = O(log n) ✓
  2. If casc_avg is approximately constant → cascade reach = O(1) ✓
  3. Then k = diameter / cascade_reach = O(log n) / O(1) = O(log n) ✓
  4. k * cascade_reach ≈ diameter at the perfect boundary confirms
     that the solver needs to "see" the entire constraint graph.
""")


def diameter_scaling():
    """Focus: is diameter really O(log n)?"""
    print(f"\n{'='*70}")
    print(f"  DIAMETER SCALING: Is diameter = O(log n)?")
    print(f"{'='*70}")

    print(f"\n{'n':>5} {'diam':>6} {'log2(n)':>8} {'ratio':>7}")
    print(f"{'─'*5} {'─'*6} {'─'*8} {'─'*7}")

    for n in [5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100]:
        diams = []
        for seed in range(20):
            clauses = generate_random_3sat(n, 4.0, seed)
            adj = build_constraint_graph(clauses, n)
            diams.append(graph_diameter(adj, n))
        avg_diam = sum(diams) / len(diams)
        log2n = math.log2(n)
        ratio = avg_diam / log2n
        print(f"{n:>5} {avg_diam:>6.1f} {log2n:>8.2f} {ratio:>7.2f}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 11: WHY k = O(log n)")
    print("▓" * 70)
    diameter_scaling()
    analyze_scaling()

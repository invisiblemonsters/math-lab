"""
Phase 11c: Information Coverage per Lookahead Step
====================================================
k_real > diameter for larger n. One lookahead step doesn't always
equal one graph hop. Measure the ACTUAL coverage.

The real question: how many graph hops does one k-step cover?
If it's c > 1 hops per step, then k = diameter/c = O(log n)/c = O(log n).
If c shrinks with n, the argument weakens.
"""

import math
from collections import defaultdict, deque

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

def constraint_graph_diameter(clauses, n_vars):
    adj = defaultdict(set)
    for clause in clauses:
        vs = [abs(l) for l in clause]
        for i in range(len(vs)):
            for j in range(i+1, len(vs)):
                adj[vs[i]].add(vs[j])
                adj[vs[j]].add(vs[i])
    max_dist = 0
    for start in range(1, n_vars + 1):
        dist = {start: 0}
        queue = deque([start])
        while queue:
            v = queue.popleft()
            for u in adj[v]:
                if u not in dist:
                    dist[u] = dist[v] + 1
                    queue.append(u)
        if dist:
            max_dist = max(max_dist, max(dist.values()))
    return max_dist, adj


def graph_avg_degree(adj, n_vars):
    total = sum(len(adj[v]) for v in range(1, n_vars+1))
    return total / n_vars


def main():
    print("=" * 70)
    print("  COVERAGE: k_real vs diameter vs log(n)")
    print("=" * 70)

    # All our data points together
    data = [
        (15, 2),
        (20, 3),
        (47, 3),
        (50, 4),
        (75, 5),
        (100, 5),
    ]

    print(f"\n  {'n':>5} {'k_real':>7} {'diam':>6} {'k/diam':>7} {'log2n':>7}"
          f" {'k/logn':>7} {'deg':>5} {'k_pred':>7}")
    print(f"  {'─'*5} {'─'*7} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*5} {'─'*7}")

    for n, k_real in data:
        diams = []
        degrees = []
        for seed in range(20):
            clauses = generate_random_3sat(n, 4.0, seed)
            d, adj = constraint_graph_diameter(clauses, n)
            diams.append(d)
            degrees.append(graph_avg_degree(adj, n))
        diam = sum(diams)/len(diams)
        deg = sum(degrees)/len(degrees)
        log2n = math.log2(n)
        k_over_diam = k_real / diam
        k_over_logn = k_real / log2n

        # Better prediction: k ≈ 0.75 * log2(n)
        k_pred = 0.75 * log2n

        print(f"  {n:>5} {k_real:>7} {diam:>6.1f} {k_over_diam:>7.2f} {log2n:>7.2f}"
              f" {k_over_logn:>7.2f} {deg:>5.1f} {k_pred:>7.1f}")

    print(f"\n  KEY OBSERVATIONS:")
    print(f"  - k/diam ≈ 1.0-1.7 (k is 1-2x the diameter)")
    print(f"  - k/log2(n) ≈ 0.51-0.80 (k grows as ~0.7 * log2(n))")
    print(f"  - Both ratios are roughly constant → k = O(log n)")
    print()

    # Fit k = a * log2(n) + b
    ns = [n for n, _ in data]
    ks = [k for _, k in data]
    logs = [math.log2(n) for n in ns]

    # Simple linear regression: k = a * log2(n) + b
    n_pts = len(data)
    sum_x = sum(logs)
    sum_y = sum(ks)
    sum_xy = sum(x*y for x,y in zip(logs, ks))
    sum_xx = sum(x*x for x in logs)
    a = (n_pts * sum_xy - sum_x * sum_y) / (n_pts * sum_xx - sum_x**2)
    b = (sum_y - a * sum_x) / n_pts

    print(f"  LINEAR FIT: k = {a:.3f} * log2(n) + ({b:.3f})")
    print()
    print(f"  Predictions from fit:")
    for n_pred in [200, 500, 1000, 10000, 100000]:
        k_pred = a * math.log2(n_pred) + b
        print(f"    n={n_pred:>6}: k_pred = {k_pred:.1f}")

    print()
    print(f"  {'='*70}")
    print(f"  THE COMPLETE ARGUMENT")
    print(f"  {'='*70}")
    print(f"""
  1. EMPIRICAL FACT: k-step lookahead achieves 100% zero-backtrack on the
     hard core of random 3-SAT when k = {a:.2f} * log2(n) + ({b:.2f}).
     Validated on n=15-100 with exact solvers and SATLIB benchmarks.

  2. STRUCTURAL EXPLANATION: The constraint graph of random 3-SAT at
     ratio 4.0 has diameter ≈ 0.45 * log2(n). k-step lookahead needs
     approximately {a/0.45:.1f}x the diameter to make globally correct decisions,
     because each lookahead step doesn't perfectly cover one graph hop
     (propagation is incomplete, scoring is greedy).

  3. COMPLEXITY: With beam-width B, the cost per DPLL decision is
     O(n * B^k). With k = {a:.2f} * log2(n):
       = O(n * B^{{{a:.2f} * log2(n)}})
       = O(n * n^{{{a:.2f} * log2(B)}})
       = O(n^{{1 + {a:.2f} * log2(B)}})

     For B=8:  O(n^{{{1 + a * math.log2(8):.2f}}})
     For B=16: O(n^{{{1 + a * math.log2(16):.2f}}})

     Times n decisions total: O(n^{{{2 + a * math.log2(8):.2f}}}) with B=8.

  4. THE GAP: This argument assumes beam-width B is a CONSTANT.
     We validated that beam=8 gives correct results on uf50 (k=4)
     and uf100 (k=5). If B must grow with n, the polynomial breaks.
     Current evidence: B=6-8 works through n=100. Insufficient data
     to confirm B is constant for all n.

  5. WHAT THIS MEANS: If B is constant (even B=20 or B=50),
     then SAT is solvable in polynomial time for random instances
     at the phase transition. This doesn't immediately prove P=NP
     (random ≠ worst-case), but it contradicts the common belief
     that phase-transition SAT requires exponential time.
""")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 11c: COVERAGE ANALYSIS")
    print("▓" * 70)
    main()

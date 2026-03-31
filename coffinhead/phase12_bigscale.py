"""
Phase 12: Big Scale — Diameter at n=10000+ and solver at n=200-250
===================================================================
Three tests:
1. Diameter scaling to n=10000 (BFS only, no solving)
2. Generate random 3-SAT at n=500,1000,5000,10000, measure diameter
3. Parse SATLIB uf200/uf250, measure diameter
"""

import math
import os
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

def parse_cnf_file(filename):
    clauses = []
    n_vars = 0
    with open(filename) as f:
        for line in f:
            if line.startswith('c') or line.startswith('%'): continue
            if line.startswith('p'):
                parts = line.split()
                n_vars = int(parts[2])
                continue
            lits = []
            for tok in line.split():
                lit = int(tok)
                if lit == 0: break
                lits.append(lit)
            if lits:
                clauses.append(lits)
    return clauses, n_vars

def graph_diameter_sampled(clauses, n_vars, n_samples=None):
    """For large n, sample BFS sources instead of all-pairs."""
    adj = defaultdict(set)
    for clause in clauses:
        vs = [abs(l) for l in clause]
        for i in range(len(vs)):
            for j in range(i+1, len(vs)):
                adj[vs[i]].add(vs[j])
                adj[vs[j]].add(vs[i])

    if n_samples is None:
        n_samples = min(n_vars, 100)

    import random
    random.seed(42)
    sources = random.sample(range(1, n_vars+1), min(n_samples, n_vars))

    max_dist = 0
    for start in sources:
        dist = {start: 0}
        queue = deque([start])
        while queue:
            v = queue.popleft()
            for u in adj[v]:
                if u not in dist:
                    dist[u] = dist[v] + 1
                    queue.append(u)
        if dist:
            d = max(dist.values())
            if d > max_dist:
                max_dist = d
    return max_dist

def main():
    import time

    print("=" * 70)
    print("  DIAMETER AT SCALE: n=5 to n=10000")
    print("=" * 70)

    print(f"\n  {'n':>7} {'diam':>6} {'log2n':>7} {'d/logn':>7} {'predict':>8} {'time':>7}")
    print(f"  {'─'*7} {'─'*6} {'─'*7} {'─'*7} {'─'*8} {'─'*7}")

    for n in [5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]:
        t0 = time.time()
        diams = []
        n_inst = 10 if n <= 1000 else 5
        n_samples = min(n, 200)
        for seed in range(n_inst):
            clauses = generate_random_3sat(n, 4.0, seed)
            d = graph_diameter_sampled(clauses, n, n_samples=n_samples)
            diams.append(d)
        elapsed = time.time() - t0
        avg_diam = sum(diams)/len(diams)
        log2n = math.log2(n)
        ratio = avg_diam / log2n
        k_pred = 1.04 * log2n - 1.94
        print(f"  {n:>7} {avg_diam:>6.1f} {log2n:>7.2f} {ratio:>7.2f} {k_pred:>8.1f} {elapsed:>6.1f}s")

    # Now parse SATLIB uf200 and uf250
    print(f"\n{'='*70}")
    print(f"  SATLIB BENCHMARK DIAMETERS")
    print(f"{'='*70}")

    for prefix, dirname in [("uf200", "benchmarks/uf200"), ("uf250", "benchmarks/uf250")]:
        if not os.path.isdir(dirname):
            print(f"  {dirname}: not found")
            continue
        files = sorted([f for f in os.listdir(dirname) if f.endswith('.cnf')])[:20]
        diams = []
        for fname in files:
            clauses, n_vars = parse_cnf_file(os.path.join(dirname, fname))
            d = graph_diameter_sampled(clauses, n_vars, n_samples=200)
            diams.append(d)
        if diams:
            avg = sum(diams)/len(diams)
            n_vars_last = n_vars
            log2n = math.log2(n_vars_last)
            print(f"  {prefix}: n={n_vars_last}, avg_diam={avg:.1f}, log2n={log2n:.2f}, d/logn={avg/log2n:.2f}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 12: BIG SCALE DIAMETER")
    print("▓" * 70)
    main()

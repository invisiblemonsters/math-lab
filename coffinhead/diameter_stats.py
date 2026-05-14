#!/usr/bin/env python3
"""
Measure constraint graph diameter with proper statistics.
Generates random 3-SAT at ratio 4.0, builds constraint graph, measures diameter via BFS.
Reports mean, std, min, max across multiple instances.
"""
import random
import math
from collections import deque

def generate_3sat(n, ratio, seed):
    """Generate random 3-SAT instance. Returns list of clauses (each a list of signed ints)."""
    rng = random.Random(seed)
    nc = int(n * ratio)
    clauses = []
    for _ in range(nc):
        vs = rng.sample(range(1, n+1), 3)
        clause = [v if rng.random() > 0.5 else -v for v in vs]
        clauses.append(clause)
    return clauses

def constraint_graph_diameter(n, clauses):
    """Build variable interaction graph and compute diameter via BFS from all nodes."""
    # Build adjacency list
    adj = {v: set() for v in range(1, n+1)}
    for clause in clauses:
        vars_in_clause = [abs(lit) for lit in clause]
        for i in range(len(vars_in_clause)):
            for j in range(i+1, len(vars_in_clause)):
                adj[vars_in_clause[i]].add(vars_in_clause[j])
                adj[vars_in_clause[j]].add(vars_in_clause[i])
    
    # BFS from every node (for small n) or sample (for large n)
    max_dist = 0
    nodes = list(range(1, n+1))
    
    # For large n, sample source nodes
    if n > 200:
        sample_nodes = random.sample(nodes, min(50, n))
    else:
        sample_nodes = nodes
    
    for source in sample_nodes:
        dist = {source: 0}
        queue = deque([source])
        while queue:
            v = queue.popleft()
            for u in adj[v]:
                if u not in dist:
                    dist[u] = dist[v] + 1
                    queue.append(u)
                    if dist[u] > max_dist:
                        max_dist = dist[u]
    
    return max_dist

def main():
    n_values = [5, 10, 20, 50, 100, 200, 500, 1000]
    n_instances = 50
    ratio = 4.0
    
    print(f"{'n':>6} {'mean_d':>7} {'std_d':>7} {'min_d':>5} {'max_d':>5} {'log2n':>7} {'d/log2n':>8} {'instances':>9}")
    print("-" * 70)
    
    for n in n_values:
        diameters = []
        for seed in range(n_instances):
            clauses = generate_3sat(n, ratio, seed)
            d = constraint_graph_diameter(n, clauses)
            diameters.append(d)
        
        mean_d = sum(diameters) / len(diameters)
        std_d = (sum((d - mean_d)**2 for d in diameters) / len(diameters))**0.5
        min_d = min(diameters)
        max_d = max(diameters)
        log2n = math.log2(n)
        ratio_d = mean_d / log2n if log2n > 0 else 0
        
        print(f"{n:>6} {mean_d:>7.2f} {std_d:>7.3f} {min_d:>5} {max_d:>5} {log2n:>7.2f} {ratio_d:>8.3f} {n_instances:>9}")

if __name__ == "__main__":
    main()

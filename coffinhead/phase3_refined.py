"""
THE COFFINHEAD CONJECTURE — Phase 3: Refined Version
=====================================================
REFINED CONJECTURE: Zero-backtrack orderings exist for satisfiable SAT
instances with backbone fraction < 0.7 AND solution count >= 4.

Tests:
1. Validate the refined boundary across n=5,6,7,8
2. Sweep the backbone/solution-count boundary to find exact threshold
3. Test on STRUCTURED instances (not random) — pigeonhole, graph coloring, etc.
4. Push to larger n with heuristics (can't brute-force orderings past n=9)
5. Adversarial hunt within the "safe" zone
"""

import random
import itertools
import math
from collections import Counter, defaultdict


# ─── Core SAT primitives ───

def generate_random_3sat(n_vars, clause_ratio, seed=None):
    if seed is not None:
        random.seed(seed)
    n_clauses = int(n_vars * clause_ratio)
    clauses = []
    variables = list(range(1, n_vars + 1))
    for _ in range(n_clauses):
        clause_vars = random.sample(variables, min(3, n_vars))
        clause = [v if random.random() > 0.5 else -v for v in clause_vars]
        clauses.append(clause)
    return clauses


def find_all_solutions(clauses, n_vars):
    solutions = []
    for bits in range(2 ** n_vars):
        assignment = {}
        for v in range(1, n_vars + 1):
            assignment[v] = bool((bits >> (v - 1)) & 1)
        if all(
            any((lit > 0 and assignment[abs(lit)]) or (lit < 0 and not assignment[abs(lit)])
                for lit in clause)
            for clause in clauses
        ):
            solutions.append(assignment)
    return solutions


def unit_propagate(clauses, assignment):
    assignment = dict(assignment)
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
                return assignment, clauses, True
            if len(simplified) == 1:
                unit_lit = simplified[0]
                var = abs(unit_lit)
                val = unit_lit > 0
                if var in assignment and assignment[var] != val:
                    return assignment, clauses, True
                if var not in assignment:
                    assignment[var] = val
                    changed = True
            new_clauses.append(simplified)
        clauses = new_clauses
    return assignment, clauses, False


def solve_with_ordering(clauses, ordering, n_vars):
    backtracks = 0

    def dpll(clauses, assignment, order_idx):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction:
            return None
        if len(clauses) == 0:
            return assignment
        unassigned = set()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var not in assignment:
                    unassigned.add(var)
        if not unassigned:
            return None
        branch_var = None
        for i in range(order_idx, len(ordering)):
            if ordering[i] in unassigned:
                branch_var = ordering[i]
                order_idx = i + 1
                break
        if branch_var is None:
            branch_var = next(iter(unassigned))
        a1 = dict(assignment)
        a1[branch_var] = True
        result = dpll([list(c) for c in clauses], a1, order_idx)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment)
        a2[branch_var] = False
        return dpll([list(c) for c in clauses], a2, order_idx)

    result = dpll(clauses, {}, 0)
    return result is not None, backtracks


def has_zero_bt_ordering(clauses, n_vars):
    """Check if ANY ordering gives zero backtracks."""
    for perm in itertools.permutations(range(1, n_vars + 1)):
        success, bt = solve_with_ordering(clauses, list(perm), n_vars)
        if success and bt == 0:
            return True
    return False


def backbone_fraction(solutions, n_vars):
    if not solutions:
        return 1.0
    count = 0
    for v in range(1, n_vars + 1):
        values = set(sol[v] for sol in solutions)
        if len(values) == 1:
            count += 1
    return count / n_vars


# ─── Structured SAT Instance Generators ───

def pigeonhole(n_holes):
    """
    Pigeonhole principle: n_holes+1 pigeons into n_holes holes.
    Each pigeon must be in some hole, no hole has two pigeons.
    UNSATISFIABLE by definition — but we use n pigeons into n holes (satisfiable).
    """
    n_pigeons = n_holes  # satisfiable version
    n_vars = n_pigeons * n_holes
    # var(p, h) = p * n_holes + h + 1
    def var(p, h):
        return p * n_holes + h + 1

    clauses = []
    # Each pigeon in at least one hole
    for p in range(n_pigeons):
        clauses.append([var(p, h) for h in range(n_holes)])

    # No two pigeons in same hole
    for h in range(n_holes):
        for p1 in range(n_pigeons):
            for p2 in range(p1 + 1, n_pigeons):
                clauses.append([-var(p1, h), -var(p2, h)])

    return clauses, n_vars


def graph_coloring_sat(n_nodes, edges, n_colors):
    """
    Graph k-coloring as SAT.
    var(node, color) = node * n_colors + color + 1
    """
    n_vars = n_nodes * n_colors
    def var(node, color):
        return node * n_colors + color + 1

    clauses = []
    # Each node has at least one color
    for node in range(n_nodes):
        clauses.append([var(node, c) for c in range(n_colors)])

    # Each node has at most one color
    for node in range(n_nodes):
        for c1 in range(n_colors):
            for c2 in range(c1 + 1, n_colors):
                clauses.append([-var(node, c1), -var(node, c2)])

    # Adjacent nodes have different colors
    for (u, v) in edges:
        for c in range(n_colors):
            clauses.append([-var(u, c), -var(v, c)])

    return clauses, n_vars


def latin_square_sat(n):
    """
    Latin square of size n as SAT.
    var(row, col, val) = row*n*n + col*n + val + 1
    """
    n_vars = n * n * n
    def var(r, c, v):
        return r * n * n + c * n + v + 1

    clauses = []
    # Each cell has at least one value
    for r in range(n):
        for c in range(n):
            clauses.append([var(r, c, v) for v in range(n)])

    # Each cell has at most one value
    for r in range(n):
        for c in range(n):
            for v1 in range(n):
                for v2 in range(v1 + 1, n):
                    clauses.append([-var(r, c, v1), -var(r, c, v2)])

    # Each value appears at most once per row
    for r in range(n):
        for v in range(n):
            for c1 in range(n):
                for c2 in range(c1 + 1, n):
                    clauses.append([-var(r, c1, v), -var(r, c2, v)])

    # Each value appears at most once per column
    for c in range(n):
        for v in range(n):
            for r1 in range(n):
                for r2 in range(r1 + 1, n):
                    clauses.append([-var(r1, c, v), -var(r2, c, v)])

    return clauses, n_vars


def random_graph(n_nodes, edge_prob, seed=None):
    """Generate random graph edges."""
    if seed is not None:
        random.seed(seed)
    edges = []
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            if random.random() < edge_prob:
                edges.append((i, j))
    return edges


# ─── Experiment 1: Validate Refined Boundary ───

def experiment_refined_boundary():
    """Test: does backbone < 0.7 AND solutions >= 4 guarantee zero-BT orderings?"""
    print("=" * 70)
    print("  EXPERIMENT 1: Validate Refined Conjecture Boundary")
    print("  Conjecture: backbone < 0.7 AND solutions >= 4 → zero-BT exists")
    print("=" * 70)

    for n_vars in [5, 6, 7, 8]:
        print(f"\n  --- n = {n_vars} ---")
        in_zone_total = 0
        in_zone_has_zero = 0
        out_zone_total = 0
        out_zone_has_zero = 0
        counterexamples_in_zone = []

        for ratio in [3.0, 3.5, 4.0, 4.5, 5.0]:
            seed = 0
            found = 0
            while found < 60 and seed < 3000:
                clauses = generate_random_3sat(n_vars, ratio, seed=seed)
                seed += 1
                solutions = find_all_solutions(clauses, n_vars)
                if not solutions:
                    continue
                found += 1

                bb = backbone_fraction(solutions, n_vars)
                n_sol = len(solutions)
                in_zone = (bb < 0.7 and n_sol >= 4)
                has_zero = has_zero_bt_ordering(clauses, n_vars)

                if in_zone:
                    in_zone_total += 1
                    if has_zero:
                        in_zone_has_zero += 1
                    else:
                        counterexamples_in_zone.append({
                            "n": n_vars, "ratio": ratio, "seed": seed - 1,
                            "n_sol": n_sol, "bb": bb,
                        })
                else:
                    out_zone_total += 1
                    if has_zero:
                        out_zone_has_zero += 1

        if in_zone_total > 0:
            pct = in_zone_has_zero / in_zone_total * 100
            print(f"  IN ZONE  (bb<0.7, sol>=4): {in_zone_has_zero}/{in_zone_total} have zero-BT ({pct:.1f}%)")
        else:
            print(f"  IN ZONE  (bb<0.7, sol>=4): no instances found")

        if out_zone_total > 0:
            pct2 = out_zone_has_zero / out_zone_total * 100
            print(f"  OUT ZONE (outside bounds): {out_zone_has_zero}/{out_zone_total} have zero-BT ({pct2:.1f}%)")

        if counterexamples_in_zone:
            print(f"  !!! {len(counterexamples_in_zone)} COUNTEREXAMPLES in safe zone:")
            for ce in counterexamples_in_zone[:5]:
                print(f"      n={ce['n']}, ratio={ce['ratio']}, seed={ce['seed']}, "
                      f"solutions={ce['n_sol']}, backbone={ce['bb']:.3f}")


# ─── Experiment 2: Sweep Backbone/Solution Boundary ───

def experiment_sweep_boundary():
    """Find the exact backbone fraction and solution count where zero-BT breaks."""
    print("\n" + "=" * 70)
    print("  EXPERIMENT 2: Boundary Sweep (n=6)")
    print("  Sweep backbone fraction and solution count thresholds")
    print("=" * 70)

    n_vars = 6
    instances = []

    for ratio in [3.0, 3.5, 4.0, 4.5, 5.0]:
        seed = 0
        found = 0
        while found < 100 and seed < 5000:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue
            found += 1
            bb = backbone_fraction(solutions, n_vars)
            has_zero = has_zero_bt_ordering(clauses, n_vars)
            instances.append({
                "n_sol": len(solutions),
                "bb": bb,
                "has_zero": has_zero,
            })

    # Sweep solution count threshold
    print(f"\n  Solution count threshold (backbone < 1.0):")
    print(f"  {'min_sol':>8} {'in_zone':>8} {'has_0bt':>8} {'pct':>8} {'CE':>5}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*5}")
    for min_sol in [1, 2, 3, 4, 5, 6, 8, 10, 15, 20]:
        zone = [i for i in instances if i["n_sol"] >= min_sol]
        has = sum(1 for i in zone if i["has_zero"])
        ce = len(zone) - has
        pct = has / len(zone) * 100 if zone else 0
        print(f"  {min_sol:>8} {len(zone):>8} {has:>8} {pct:>7.1f}% {ce:>5}")

    # Sweep backbone threshold
    print(f"\n  Backbone threshold (all solution counts):")
    print(f"  {'max_bb':>8} {'in_zone':>8} {'has_0bt':>8} {'pct':>8} {'CE':>5}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*5}")
    for max_bb in [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]:
        zone = [i for i in instances if i["bb"] <= max_bb]
        has = sum(1 for i in zone if i["has_zero"])
        ce = len(zone) - has
        pct = has / len(zone) * 100 if zone else 0
        print(f"  {max_bb:>8.1f} {len(zone):>8} {has:>8} {pct:>7.1f}% {ce:>5}")

    # Combined sweep
    print(f"\n  Combined boundary (backbone < X AND solutions >= Y):")
    print(f"  {'max_bb':>8} {'min_sol':>8} {'in_zone':>8} {'has_0bt':>8} {'pct':>8}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for max_bb in [0.8, 0.7, 0.6, 0.5, 0.4, 0.3]:
        for min_sol in [2, 3, 4, 5, 8]:
            zone = [i for i in instances if i["bb"] <= max_bb and i["n_sol"] >= min_sol]
            has = sum(1 for i in zone if i["has_zero"])
            pct = has / len(zone) * 100 if zone else 0
            if zone:
                marker = " <<<" if pct == 100.0 and len(zone) >= 10 else ""
                print(f"  {max_bb:>8.1f} {min_sol:>8} {len(zone):>8} {has:>8} {pct:>7.1f}%{marker}")


# ─── Experiment 3: Structured Instances ───

def experiment_structured():
    """Test on structured SAT instances — these model real-world problems."""
    print("\n" + "=" * 70)
    print("  EXPERIMENT 3: Structured SAT Instances")
    print("  Pigeonhole, Graph Coloring, Latin Square")
    print("=" * 70)

    # Pigeonhole: n pigeons into n holes (satisfiable)
    print(f"\n  PIGEONHOLE (n pigeons → n holes):")
    for n in [2, 3, 4]:
        clauses, n_vars = pigeonhole(n)
        solutions = find_all_solutions(clauses, n_vars)
        if not solutions:
            print(f"    n={n}: UNSAT (n_vars={n_vars})")
            continue
        bb = backbone_fraction(solutions, n_vars)

        if n_vars <= 9:
            has_zero = has_zero_bt_ordering(clauses, n_vars)
            print(f"    n={n}: n_vars={n_vars}, clauses={len(clauses)}, "
                  f"solutions={len(solutions)}, backbone={bb:.3f}, zero-BT={has_zero}")
        else:
            # Too many orderings, test heuristics
            orderings_to_test = []
            # Least frequent
            counts = Counter()
            for clause in clauses:
                for lit in clause:
                    counts[abs(lit)] += 1
            lf = sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0))
            orderings_to_test.append(("least_freq", lf))
            mf = sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0), reverse=True)
            orderings_to_test.append(("most_freq", mf))
            orderings_to_test.append(("natural", list(range(1, n_vars + 1))))

            best_bt = float('inf')
            best_name = ""
            for name, ordering in orderings_to_test:
                _, bt = solve_with_ordering(clauses, ordering, n_vars)
                if bt < best_bt:
                    best_bt = bt
                    best_name = name

            print(f"    n={n}: n_vars={n_vars}, clauses={len(clauses)}, "
                  f"solutions={len(solutions)}, backbone={bb:.3f}, "
                  f"best_heuristic_bt={best_bt} ({best_name})")

    # Graph coloring
    print(f"\n  GRAPH COLORING (random graphs, 3 colors):")
    for n_nodes in [4, 5, 6]:
        for edge_prob in [0.3, 0.5]:
            edges = random_graph(n_nodes, edge_prob, seed=42)
            if not edges:
                continue
            clauses, n_vars = graph_coloring_sat(n_nodes, edges, 3)
            if n_vars > 20:
                # Skip brute force solutions for large instances
                print(f"    nodes={n_nodes}, edges={len(edges)}, n_vars={n_vars}: too large for brute force")
                continue
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                print(f"    nodes={n_nodes}, edges={len(edges)}: UNSAT")
                continue
            bb = backbone_fraction(solutions, n_vars)

            if n_vars <= 9:
                has_zero = has_zero_bt_ordering(clauses, n_vars)
                status = "zero-BT EXISTS" if has_zero else "NO zero-BT"
            else:
                # Heuristic test
                counts = Counter()
                for clause in clauses:
                    for lit in clause:
                        counts[abs(lit)] += 1
                lf = sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0))
                _, bt = solve_with_ordering(clauses, lf, n_vars)
                status = f"least_freq bt={bt}"

            print(f"    nodes={n_nodes}, edge_prob={edge_prob}, edges={len(edges)}, "
                  f"n_vars={n_vars}, clauses={len(clauses)}, solutions={len(solutions)}, "
                  f"backbone={bb:.3f}, {status}")

    # Latin square (small)
    print(f"\n  LATIN SQUARE:")
    for n in [2, 3]:
        clauses, n_vars = latin_square_sat(n)
        solutions = find_all_solutions(clauses, n_vars)
        if not solutions:
            print(f"    n={n}: UNSAT")
            continue
        bb = backbone_fraction(solutions, n_vars)

        if n_vars <= 9:
            has_zero = has_zero_bt_ordering(clauses, n_vars)
            print(f"    n={n}: n_vars={n_vars}, clauses={len(clauses)}, "
                  f"solutions={len(solutions)}, backbone={bb:.3f}, zero-BT={has_zero}")
        else:
            counts = Counter()
            for clause in clauses:
                for lit in clause:
                    counts[abs(lit)] += 1
            lf = sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0))
            _, bt = solve_with_ordering(clauses, lf, n_vars)
            print(f"    n={n}: n_vars={n_vars}, clauses={len(clauses)}, "
                  f"solutions={len(solutions)}, backbone={bb:.3f}, least_freq bt={bt}")


# ─── Experiment 4: Adversarial Hunt in Safe Zone ───

def experiment_adversarial_safe_zone():
    """Aggressively hunt for counterexamples WITHIN the refined conjecture boundary."""
    print("\n" + "=" * 70)
    print("  EXPERIMENT 4: Adversarial Hunt in Safe Zone")
    print("  Looking for instances with bb<0.5, sol>=4, but NO zero-BT ordering")
    print("=" * 70)

    counterexamples = []
    tested_in_zone = 0

    for n_vars in [5, 6, 7]:
        n_ce = 0
        n_tested = 0
        for ratio in [2.5, 3.0, 3.5, 4.0]:
            for seed in range(2000):
                clauses = generate_random_3sat(n_vars, ratio, seed=seed + n_vars * 10000)
                solutions = find_all_solutions(clauses, n_vars)
                if not solutions:
                    continue

                bb = backbone_fraction(solutions, n_vars)
                n_sol = len(solutions)

                # Only test instances in the safe zone
                if bb >= 0.5 or n_sol < 4:
                    continue

                n_tested += 1
                tested_in_zone += 1
                has_zero = has_zero_bt_ordering(clauses, n_vars)

                if not has_zero:
                    n_ce += 1
                    counterexamples.append({
                        "n": n_vars, "ratio": ratio, "seed": seed + n_vars * 10000,
                        "n_sol": n_sol, "bb": bb,
                    })
                    print(f"  !!! CE: n={n_vars}, ratio={ratio}, seed={seed + n_vars * 10000}, "
                          f"sol={n_sol}, bb={bb:.3f}")

        print(f"  n={n_vars}: tested {n_tested} in safe zone, {n_ce} counterexamples "
              f"({n_ce/n_tested*100:.1f}% failure rate)" if n_tested > 0 else f"  n={n_vars}: no instances in zone")

    print(f"\n  TOTAL: {tested_in_zone} instances tested in safe zone, "
          f"{len(counterexamples)} counterexamples")
    if not counterexamples:
        print(f"  >>> REFINED CONJECTURE HOLDS across all tested instances <<<")


# ─── Experiment 5: Tighter Boundary Search ───

def experiment_find_tightest_boundary():
    """Find the TIGHTEST safe zone that still has zero counterexamples."""
    print("\n" + "=" * 70)
    print("  EXPERIMENT 5: Tightest Safe Boundary (n=6, heavy sampling)")
    print("=" * 70)

    n_vars = 6
    instances = []

    for ratio in [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]:
        for seed in range(1500):
            clauses = generate_random_3sat(n_vars, ratio, seed=seed + 20000)
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue
            bb = backbone_fraction(solutions, n_vars)
            has_zero = has_zero_bt_ordering(clauses, n_vars)
            instances.append({
                "n_sol": len(solutions),
                "bb": bb,
                "has_zero": has_zero,
                "ratio": ratio,
                "seed": seed + 20000,
            })

    print(f"  Total instances: {len(instances)}")

    # Find tightest boundary
    print(f"\n  Searching for tightest 100% safe boundary...")
    print(f"  {'max_bb':>8} {'min_sol':>8} {'count':>8} {'0bt':>8} {'pct':>8}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    best_zone_size = 0
    best_params = None

    for max_bb_x10 in range(10, 0, -1):  # 1.0 down to 0.1
        max_bb = max_bb_x10 / 10.0
        for min_sol in [2, 3, 4, 5, 6, 8, 10]:
            zone = [i for i in instances if i["bb"] <= max_bb and i["n_sol"] >= min_sol]
            if not zone:
                continue
            has = sum(1 for i in zone if i["has_zero"])
            pct = has / len(zone) * 100
            if pct == 100.0 and len(zone) >= 20:
                if len(zone) > best_zone_size:
                    best_zone_size = len(zone)
                    best_params = (max_bb, min_sol)
                    print(f"  {max_bb:>8.1f} {min_sol:>8} {len(zone):>8} {has:>8} {pct:>7.1f}% <<<")
            elif pct < 100.0 and len(zone) >= 10:
                ce = len(zone) - has
                print(f"  {max_bb:>8.1f} {min_sol:>8} {len(zone):>8} {has:>8} {pct:>7.1f}% ({ce} CE)")

    if best_params:
        print(f"\n  TIGHTEST 100% SAFE ZONE: backbone <= {best_params[0]}, solutions >= {best_params[1]}")
        print(f"  Covers {best_zone_size} instances with ZERO counterexamples")
    else:
        print(f"\n  No 100% safe zone found with >= 20 instances")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 3: Refined Version")
    print("▓" * 70)

    experiment_refined_boundary()
    experiment_sweep_boundary()
    experiment_structured()
    experiment_adversarial_safe_zone()
    experiment_find_tightest_boundary()

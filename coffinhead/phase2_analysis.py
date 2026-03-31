"""
THE COFFINHEAD CONJECTURE — Phase 2: Counterexample Analysis
=============================================================
The strong conjecture is falsified at n=6. Now we need to understand:
1. What structural properties distinguish counterexamples from non-counterexamples?
2. Is there a class of SAT instances where zero-BT orderings ALWAYS exist?
3. What's the exact threshold between n=5 (100%) and n=6 (fails)?
4. Do counterexamples share graph-theoretic properties?
"""

import random
import itertools
import math
from collections import Counter, defaultdict
import json


# ─── Core SAT primitives (from phase1) ───

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
    decisions = 0

    def dpll(clauses, assignment, order_idx):
        nonlocal backtracks, decisions
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
        decisions += 1
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
    return result is not None, backtracks, decisions


def check_all_orderings(clauses, n_vars):
    variables = list(range(1, n_vars + 1))
    total = 0
    zero_bt = 0
    min_bt = float('inf')
    for perm in itertools.permutations(variables):
        ordering = list(perm)
        success, bt, _ = solve_with_ordering(clauses, ordering, n_vars)
        total += 1
        if success:
            if bt < min_bt:
                min_bt = bt
            if bt == 0:
                zero_bt += 1
    return total, zero_bt, min_bt


# ─── Structural Analysis Functions ───

def clause_variable_graph(clauses, n_vars):
    """Build variable interaction graph: edge between vars that share a clause."""
    edges = set()
    for clause in clauses:
        vars_in_clause = [abs(lit) for lit in clause]
        for i in range(len(vars_in_clause)):
            for j in range(i + 1, len(vars_in_clause)):
                edges.add((min(vars_in_clause[i], vars_in_clause[j]),
                           max(vars_in_clause[i], vars_in_clause[j])))
    return edges


def graph_density(edges, n_vars):
    """Edge density of variable interaction graph."""
    max_edges = n_vars * (n_vars - 1) / 2
    return len(edges) / max_edges if max_edges > 0 else 0


def variable_degree(clauses, n_vars):
    """How many clauses each variable appears in."""
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    return counts


def polarity_bias(clauses, n_vars):
    """For each variable, how biased is it toward positive or negative."""
    pos = Counter()
    neg = Counter()
    for clause in clauses:
        for lit in clause:
            if lit > 0:
                pos[abs(lit)] += 1
            else:
                neg[abs(lit)] += 1
    biases = {}
    for v in range(1, n_vars + 1):
        total = pos.get(v, 0) + neg.get(v, 0)
        if total > 0:
            biases[v] = abs(pos.get(v, 0) - neg.get(v, 0)) / total
        else:
            biases[v] = 0
    return biases


def clause_overlap(clauses):
    """Average number of variables shared between clause pairs."""
    if len(clauses) < 2:
        return 0
    total_overlap = 0
    pairs = 0
    for i in range(len(clauses)):
        vars_i = set(abs(lit) for lit in clauses[i])
        for j in range(i + 1, len(clauses)):
            vars_j = set(abs(lit) for lit in clauses[j])
            total_overlap += len(vars_i & vars_j)
            pairs += 1
    return total_overlap / pairs if pairs > 0 else 0


def backbone_fraction(solutions, n_vars):
    """What fraction of variables are backbone (fixed across all solutions)."""
    if not solutions:
        return 0
    backbone_count = 0
    for v in range(1, n_vars + 1):
        values = set(sol[v] for sol in solutions)
        if len(values) == 1:
            backbone_count += 1
    return backbone_count / n_vars


def solution_hamming_diversity(solutions, n_vars):
    """Average Hamming distance between solution pairs, normalized."""
    if len(solutions) < 2:
        return 0
    total_dist = 0
    pairs = 0
    for i in range(len(solutions)):
        for j in range(i + 1, len(solutions)):
            dist = sum(1 for v in range(1, n_vars + 1) if solutions[i][v] != solutions[j][v])
            total_dist += dist
            pairs += 1
    return (total_dist / pairs) / n_vars if pairs > 0 else 0


def unit_propagation_power(clauses, n_vars):
    """How many variables get assigned by unit propagation alone (no decisions)?"""
    assignment, remaining, contradiction = unit_propagate(clauses, {})
    return len(assignment) / n_vars


def clause_length_after_pure_literals(clauses, n_vars):
    """Apply pure literal elimination, measure how much the formula shrinks."""
    pos_vars = set()
    neg_vars = set()
    for clause in clauses:
        for lit in clause:
            if lit > 0:
                pos_vars.add(abs(lit))
            else:
                neg_vars.add(abs(lit))
    pure = (pos_vars - neg_vars) | (neg_vars - pos_vars)
    return len(pure) / n_vars if n_vars > 0 else 0


def constraint_tightness(clauses, n_vars):
    """
    Ratio of clauses to maximum possible clauses.
    Higher = more constrained.
    """
    # For 3-SAT with n vars: max distinct clauses = C(n,3) * 8
    max_clauses = math.comb(n_vars, 3) * 8
    return len(clauses) / max_clauses if max_clauses > 0 else 0


# ─── Main Analysis ───

def collect_instances(n_vars, n_instances, clause_ratio, seed_start=0):
    """Collect satisfiable instances, classify as counterexample or not."""
    instances = []
    seed = seed_start
    while len(instances) < n_instances and seed < seed_start + n_instances * 30:
        clauses = generate_random_3sat(n_vars, clause_ratio, seed=seed)
        seed += 1
        solutions = find_all_solutions(clauses, n_vars)
        if not solutions:
            continue
        total, zero_bt, min_bt = check_all_orderings(clauses, n_vars)
        is_counterexample = (zero_bt == 0)
        instances.append({
            "seed": seed - 1,
            "clauses": clauses,
            "n_clauses": len(clauses),
            "solutions": solutions,
            "n_solutions": len(solutions),
            "zero_bt_count": zero_bt,
            "zero_bt_pct": zero_bt / total * 100,
            "min_bt": min_bt,
            "is_counterexample": is_counterexample,
        })
    return instances


def analyze_instances(instances, n_vars):
    """Compute structural features for each instance."""
    for inst in instances:
        clauses = inst["clauses"]
        solutions = inst["solutions"]

        edges = clause_variable_graph(clauses, n_vars)
        degrees = variable_degree(clauses, n_vars)
        biases = polarity_bias(clauses, n_vars)

        inst["graph_density"] = graph_density(edges, n_vars)
        inst["avg_degree"] = sum(degrees.values()) / n_vars if degrees else 0
        inst["max_degree"] = max(degrees.values()) if degrees else 0
        inst["min_degree"] = min(degrees.get(v, 0) for v in range(1, n_vars + 1))
        inst["degree_variance"] = (
            sum((d - inst["avg_degree"])**2 for d in degrees.values()) / n_vars
        ) if degrees else 0
        inst["avg_polarity_bias"] = sum(biases.values()) / n_vars
        inst["max_polarity_bias"] = max(biases.values()) if biases else 0
        inst["min_polarity_bias"] = min(biases.values()) if biases else 0
        inst["clause_overlap"] = clause_overlap(clauses)
        inst["backbone_fraction"] = backbone_fraction(solutions, n_vars)
        inst["solution_diversity"] = solution_hamming_diversity(solutions, n_vars)
        inst["up_power"] = unit_propagation_power(clauses, n_vars)
        inst["pure_literal_fraction"] = clause_length_after_pure_literals(clauses, n_vars)
        inst["constraint_tightness"] = constraint_tightness(clauses, n_vars)


def print_comparison(instances, n_vars, label):
    """Compare structural features between counterexamples and non-counterexamples."""
    counterexamples = [i for i in instances if i["is_counterexample"]]
    non_counterexamples = [i for i in instances if not i["is_counterexample"]]

    if not counterexamples or not non_counterexamples:
        print(f"  {label}: Need both classes (CE={len(counterexamples)}, non-CE={len(non_counterexamples)})")
        return

    features = [
        "n_solutions", "backbone_fraction", "solution_diversity",
        "graph_density", "avg_degree", "degree_variance",
        "avg_polarity_bias", "max_polarity_bias", "min_polarity_bias",
        "clause_overlap", "up_power", "pure_literal_fraction",
        "constraint_tightness", "min_bt",
    ]

    print(f"\n  {label}")
    print(f"  Counterexamples: {len(counterexamples)}, Non-counterexamples: {len(non_counterexamples)}")
    print(f"  {'Feature':<25} {'CE mean':>10} {'non-CE mean':>12} {'Delta':>10} {'Direction':>10}")
    print(f"  {'-'*25} {'-'*10} {'-'*12} {'-'*10} {'-'*10}")

    separators = []
    for feat in features:
        ce_vals = [i[feat] for i in counterexamples if feat in i]
        nce_vals = [i[feat] for i in non_counterexamples if feat in i]
        if not ce_vals or not nce_vals:
            continue
        ce_mean = sum(ce_vals) / len(ce_vals)
        nce_mean = sum(nce_vals) / len(nce_vals)
        delta = ce_mean - nce_mean
        direction = "CE higher" if delta > 0 else "CE lower"
        # Significance: how many standard deviations apart?
        all_vals = ce_vals + nce_vals
        std = (sum((v - sum(all_vals)/len(all_vals))**2 for v in all_vals) / len(all_vals)) ** 0.5
        effect = abs(delta) / std if std > 0 else 0

        marker = ""
        if effect > 0.5:
            marker = " *"
            separators.append((feat, delta, effect, direction))
        if effect > 1.0:
            marker = " **"
        if effect > 1.5:
            marker = " ***"

        print(f"  {feat:<25} {ce_mean:>10.3f} {nce_mean:>12.3f} {delta:>+10.3f} {direction:>10}{marker}")

    if separators:
        print(f"\n  STRONGEST SEPARATORS (effect size > 0.5):")
        for feat, delta, effect, direction in sorted(separators, key=lambda x: -x[2]):
            print(f"    {feat}: effect={effect:.2f}, {direction}")


def experiment_structural_comparison():
    """Compare counterexample vs non-counterexample structure at n=6."""
    print("=" * 70)
    print("  EXPERIMENT 1: Structural Feature Comparison (n=6)")
    print("=" * 70)

    for ratio in [3.0, 3.5, 4.0, 5.0]:
        instances = collect_instances(6, 200, ratio)
        analyze_instances(instances, 6)
        ce_count = sum(1 for i in instances if i["is_counterexample"])
        nce_count = sum(1 for i in instances if not i["is_counterexample"])
        print_comparison(instances, 6, f"ratio={ratio} (CE={ce_count}, non-CE={nce_count})")


def experiment_solution_count_threshold():
    """Is there a solution count threshold above which zero-BT always exists?"""
    print("\n" + "=" * 70)
    print("  EXPERIMENT 2: Zero-BT vs Solution Count (n=6)")
    print("=" * 70)

    for ratio in [3.0, 4.0, 5.0]:
        instances = collect_instances(6, 300, ratio, seed_start=1000)
        # Don't need full analysis, just solution count vs zero-BT
        by_solutions = defaultdict(lambda: {"total": 0, "has_zero_bt": 0})
        for inst in instances:
            n_sol = inst["n_solutions"]
            bucket = "1" if n_sol == 1 else "2-3" if n_sol <= 3 else "4-10" if n_sol <= 10 else "11-50" if n_sol <= 50 else "50+"
            by_solutions[bucket]["total"] += 1
            if inst["zero_bt_count"] > 0:
                by_solutions[bucket]["has_zero_bt"] += 1

        print(f"\n  ratio={ratio}:")
        print(f"  {'solutions':>12} {'total':>8} {'has_zero_bt':>12} {'pct':>8}")
        print(f"  {'-'*12} {'-'*8} {'-'*12} {'-'*8}")
        for bucket in ["1", "2-3", "4-10", "11-50", "50+"]:
            if bucket in by_solutions:
                d = by_solutions[bucket]
                pct = d["has_zero_bt"] / d["total"] * 100 if d["total"] > 0 else 0
                print(f"  {bucket:>12} {d['total']:>8} {d['has_zero_bt']:>12} {pct:>7.1f}%")


def experiment_threshold_n5_to_n6():
    """Find EXACTLY what changes between n=5 (always works) and n=6 (sometimes fails)."""
    print("\n" + "=" * 70)
    print("  EXPERIMENT 3: Threshold Analysis n=5 vs n=6")
    print("=" * 70)

    for n_vars in [5, 6]:
        print(f"\n  n = {n_vars}:")
        for ratio in [3.0, 4.0, 5.0, 6.0]:
            instances = collect_instances(n_vars, 100, ratio, seed_start=5000)
            ce = sum(1 for i in instances if i["is_counterexample"])
            total = len(instances)

            # For counterexamples at n=6, check if they have unique solutions
            if n_vars == 6 and ce > 0:
                ce_instances = [i for i in instances if i["is_counterexample"]]
                unique_sol = sum(1 for i in ce_instances if i["n_solutions"] == 1)
                print(f"    ratio={ratio}: {ce}/{total} counterexamples "
                      f"({ce/total*100:.1f}%), {unique_sol}/{ce} have unique solution")
            else:
                print(f"    ratio={ratio}: {ce}/{total} counterexamples ({ce/total*100:.1f}%)")


def experiment_propagation_depth():
    """
    KEY HYPOTHESIS: Counterexamples have LOW unit propagation power.
    When UP can't determine many variables, you MUST make decisions,
    and decisions can be wrong, requiring backtracking.
    """
    print("\n" + "=" * 70)
    print("  EXPERIMENT 4: Unit Propagation Power Analysis")
    print("=" * 70)

    instances = collect_instances(6, 300, 4.0, seed_start=2000)
    analyze_instances(instances, 6)

    ce = [i for i in instances if i["is_counterexample"]]
    nce = [i for i in instances if not i["is_counterexample"]]

    if ce and nce:
        ce_up = [i["up_power"] for i in ce]
        nce_up = [i["up_power"] for i in nce]
        ce_bb = [i["backbone_fraction"] for i in ce]
        nce_bb = [i["backbone_fraction"] for i in nce]

        print(f"\n  Unit Propagation Power (fraction of vars assigned by UP alone):")
        print(f"    Counterexamples (n={len(ce)}):     mean={sum(ce_up)/len(ce_up):.3f}")
        print(f"    Non-counterexamples (n={len(nce)}): mean={sum(nce_up)/len(nce_up):.3f}")
        print(f"\n  Backbone Fraction:")
        print(f"    Counterexamples:     mean={sum(ce_bb)/len(ce_bb):.3f}")
        print(f"    Non-counterexamples: mean={sum(nce_bb)/len(nce_bb):.3f}")

        # Cross-tabulate UP power and zero-BT
        print(f"\n  UP Power vs Zero-BT existence:")
        print(f"  {'UP power':>12} {'total':>8} {'has_0bt':>8} {'pct':>8}")
        print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8}")
        buckets = defaultdict(lambda: {"total": 0, "has_0bt": 0})
        for inst in instances:
            up = inst["up_power"]
            bucket = f"{up:.1f}"
            buckets[bucket]["total"] += 1
            if inst["zero_bt_count"] > 0:
                buckets[bucket]["has_0bt"] += 1
        for bucket in sorted(buckets.keys()):
            d = buckets[bucket]
            pct = d["has_0bt"] / d["total"] * 100 if d["total"] > 0 else 0
            print(f"  {bucket:>12} {d['total']:>8} {d['has_0bt']:>8} {pct:>7.1f}%")


def experiment_degree_uniformity():
    """
    HYPOTHESIS: Counterexamples have MORE UNIFORM variable degrees.
    When all variables are equally constrained, there's no "obvious" ordering.
    Non-counterexamples might have clear bottleneck variables.
    """
    print("\n" + "=" * 70)
    print("  EXPERIMENT 5: Degree Uniformity Analysis")
    print("=" * 70)

    instances = collect_instances(6, 300, 4.0, seed_start=3000)
    analyze_instances(instances, 6)

    ce = [i for i in instances if i["is_counterexample"]]
    nce = [i for i in instances if not i["is_counterexample"]]

    if ce and nce:
        ce_var = [i["degree_variance"] for i in ce]
        nce_var = [i["degree_variance"] for i in nce]
        ce_range = [i["max_degree"] - i["min_degree"] for i in ce]
        nce_range = [i["max_degree"] - i["min_degree"] for i in nce]

        print(f"\n  Degree Variance (higher = more variation between variables):")
        print(f"    Counterexamples (n={len(ce)}):     mean={sum(ce_var)/len(ce_var):.3f}")
        print(f"    Non-counterexamples (n={len(nce)}): mean={sum(nce_var)/len(nce_var):.3f}")
        print(f"\n  Degree Range (max - min):")
        print(f"    Counterexamples:     mean={sum(ce_range)/len(ce_range):.3f}")
        print(f"    Non-counterexamples: mean={sum(nce_range)/len(nce_range):.3f}")


def experiment_deep_counterexample():
    """Deeply analyze the worst counterexample from Phase 1b."""
    print("\n" + "=" * 70)
    print("  EXPERIMENT 6: Deep Dive — Worst Counterexample")
    print("  (seed=22, ratio=3.0, n=6, 1 solution, min_bt=3)")
    print("=" * 70)

    clauses = generate_random_3sat(6, 3.0, seed=22)
    solutions = find_all_solutions(clauses, 6)

    print(f"\n  Clauses ({len(clauses)}):")
    for i, c in enumerate(clauses):
        print(f"    {i}: {c}")

    print(f"\n  Solutions ({len(solutions)}):")
    for sol in solutions:
        assignment = "".join("1" if sol[v] else "0" for v in range(1, 7))
        print(f"    x1..x6 = {assignment}")

    # Variable analysis
    degrees = variable_degree(clauses, 6)
    biases = polarity_bias(clauses, 6)
    print(f"\n  Variable degrees: {dict(sorted(degrees.items()))}")
    print(f"  Polarity bias: ", end="")
    for v in range(1, 7):
        pos = sum(1 for c in clauses for l in c if l == v)
        neg = sum(1 for c in clauses for l in c if l == -v)
        print(f"x{v}(+{pos}/-{neg}) ", end="")
    print()

    # Graph structure
    edges = clause_variable_graph(clauses, 6)
    print(f"\n  Variable interaction graph:")
    print(f"    Edges ({len(edges)}): {sorted(edges)}")
    print(f"    Density: {graph_density(edges, 6):.3f}")

    # UP power
    assignment, remaining, contradiction = unit_propagate(clauses, {})
    print(f"\n  Unit propagation from empty: assigns {len(assignment)} vars: {assignment}")
    print(f"  Remaining clauses: {len(remaining)}")

    # Backbone
    bb = {}
    for v in range(1, 7):
        vals = set(sol[v] for sol in solutions)
        if len(vals) == 1:
            bb[v] = next(iter(vals))
    print(f"  Backbone variables: {bb if bb else 'NONE'}")

    # Best orderings
    print(f"\n  ALL orderings backtrack distribution:")
    dist = Counter()
    best_orderings = []
    for perm in itertools.permutations(range(1, 7)):
        ordering = list(perm)
        success, bt, decisions = solve_with_ordering(clauses, ordering, 6)
        dist[bt] += 1
        if bt <= 3:
            best_orderings.append((bt, ordering, decisions))

    print(f"    {dict(sorted(dist.items()))}")
    best_orderings.sort()
    print(f"\n  Best orderings (bt=3, first 10):")
    for bt, ordering, decisions in best_orderings[:10]:
        print(f"    bt={bt}, decisions={decisions}, ordering={ordering}")

    # What do the best orderings have in common?
    if best_orderings:
        min_bt_val = best_orderings[0][0]
        best_only = [(bt, o, d) for bt, o, d in best_orderings if bt == min_bt_val]
        first_vars = Counter(o[0] for _, o, _ in best_only)
        print(f"\n  First variable in best orderings: {dict(first_vars)}")
        second_vars = Counter(o[1] for _, o, _ in best_only)
        print(f"  Second variable in best orderings: {dict(second_vars)}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 2: Counterexample Analysis")
    print("▓" * 70)

    experiment_deep_counterexample()
    experiment_solution_count_threshold()
    experiment_threshold_n5_to_n6()
    experiment_propagation_depth()
    experiment_degree_uniformity()
    experiment_structural_comparison()

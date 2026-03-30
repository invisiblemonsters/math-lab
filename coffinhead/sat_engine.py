"""
THE COFFINHEAD CONJECTURE — Phase 1: Empirical Harness
======================================================
Does there exist a variable ordering for any satisfiable SAT formula
such that unit propagation produces a satisfying assignment WITHOUT backtracking?

This harness:
1. Generates random 3-SAT instances
2. Implements DPLL with unit propagation + backtrack counting
3. Brute-forces ALL variable orderings on small instances
4. Measures zero-backtrack ordering frequency
5. Tests heuristic orderings (backbone-first, least-frequent-first, endpoint)
"""

import random
import itertools
import time
import json
from copy import deepcopy
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ─── SAT Instance Generation ───

def generate_3sat(n_vars: int, clause_ratio: float = 4.26, seed: int = None) -> list[list[int]]:
    """
    Generate a random 3-SAT instance.
    clause_ratio ~4.26 is the satisfiability phase transition threshold.
    Lower ratios = more likely satisfiable.
    Returns list of clauses, each clause is a list of signed ints (positive=true, negative=negated).
    """
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


def generate_satisfiable_3sat(n_vars: int, clause_ratio: float = 3.5, max_attempts: int = 100, seed: int = None) -> Optional[tuple[list[list[int]], list[bool]]]:
    """
    Generate a random 3-SAT instance that is guaranteed satisfiable.
    Returns (clauses, planted_solution) or None if couldn't find one.
    Uses planted solution method: pick a random assignment, generate clauses consistent with it.
    """
    if seed is not None:
        random.seed(seed)
    n_clauses = int(n_vars * clause_ratio)
    # Plant a random solution
    solution = [random.random() > 0.5 for _ in range(n_vars)]  # index 0 = var 1
    clauses = []
    variables = list(range(1, n_vars + 1))
    for _ in range(n_clauses):
        clause_vars = random.sample(variables, min(3, n_vars))
        clause = []
        for v in clause_vars:
            # Bias toward satisfying literals but allow some noise
            val = solution[v - 1]
            if random.random() < 0.7:
                # Make this literal satisfy the planted solution
                clause.append(v if val else -v)
            else:
                clause.append(v if random.random() > 0.5 else -v)
        # Ensure at least one literal satisfies planted solution
        satisfied = any(
            (lit > 0 and solution[abs(lit) - 1]) or
            (lit < 0 and not solution[abs(lit) - 1])
            for lit in clause
        )
        if not satisfied:
            # Force one literal to match
            fix_idx = random.randrange(len(clause))
            v = abs(clause[fix_idx])
            clause[fix_idx] = v if solution[v - 1] else -v
        clauses.append(clause)
    return clauses, solution


# ─── Unit Propagation Engine ───

@dataclass
class PropagationResult:
    success: bool           # True if satisfying assignment found
    assignment: dict        # variable -> True/False
    backtracks: int         # number of backtracks needed
    propagations: int       # total unit propagations performed
    decisions: int          # total decision points


def unit_propagate(clauses: list[list[int]], assignment: dict) -> tuple[dict, list[list[int]], bool]:
    """
    Perform unit propagation until fixpoint.
    Returns (updated_assignment, simplified_clauses, contradiction_found).
    """
    assignment = dict(assignment)
    clauses = [list(c) for c in clauses]
    changed = True
    while changed:
        changed = False
        # Simplify clauses with current assignment
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
                    # else this literal is false, skip it
                else:
                    simplified.append(lit)
            if satisfied:
                continue
            if len(simplified) == 0:
                return assignment, clauses, True  # CONTRADICTION — empty clause
            if len(simplified) == 1:
                # Unit clause — force assignment
                unit_lit = simplified[0]
                var = abs(unit_lit)
                val = unit_lit > 0
                if var in assignment:
                    if assignment[var] != val:
                        return assignment, clauses, True  # CONTRADICTION
                else:
                    assignment[var] = val
                    changed = True
            new_clauses.append(simplified)
        clauses = new_clauses
    return assignment, clauses, False


def solve_with_ordering(clauses: list[list[int]], ordering: list[int], n_vars: int) -> PropagationResult:
    """
    Solve SAT using DPLL with a FIXED variable ordering.
    The ordering determines which variable to branch on at each decision point.
    Counts backtracks precisely.
    """
    backtracks = 0
    propagations = 0
    decisions = 0

    def dpll(clauses, assignment, order_idx):
        nonlocal backtracks, propagations, decisions

        # Unit propagate
        propagations += 1
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)

        if contradiction:
            return None

        # Check if all clauses satisfied
        if len(clauses) == 0:
            # Fill unassigned variables
            for v in range(1, n_vars + 1):
                if v not in assignment:
                    assignment[v] = True
            return assignment

        # Check for remaining unassigned variables in clauses
        unassigned_in_clauses = set()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var not in assignment:
                    unassigned_in_clauses.add(var)

        if not unassigned_in_clauses:
            # All variables assigned but clauses remain — unsatisfied
            return None

        # Pick next variable from ordering
        branch_var = None
        for i in range(order_idx, len(ordering)):
            if ordering[i] in unassigned_in_clauses:
                branch_var = ordering[i]
                order_idx = i + 1
                break

        if branch_var is None:
            # Fallback: pick any unassigned
            branch_var = next(iter(unassigned_in_clauses))

        decisions += 1

        # Try True first
        new_assignment = dict(assignment)
        new_assignment[branch_var] = True
        result = dpll([list(c) for c in clauses], new_assignment, order_idx)
        if result is not None:
            return result

        # Backtrack — try False
        backtracks += 1
        new_assignment = dict(assignment)
        new_assignment[branch_var] = False
        result = dpll([list(c) for c in clauses], new_assignment, order_idx)
        return result

    result = dpll(clauses, {}, 0)
    return PropagationResult(
        success=result is not None,
        assignment=result or {},
        backtracks=backtracks,
        propagations=propagations,
        decisions=decisions,
    )


# ─── Brute Force Ordering Search ───

def check_all_orderings(clauses: list[list[int]], n_vars: int) -> dict:
    """
    For small instances: try ALL n! variable orderings.
    Returns stats on zero-backtrack orderings.
    """
    variables = list(range(1, n_vars + 1))
    total_orderings = 0
    zero_backtrack = 0
    min_backtracks = float('inf')
    max_backtracks = 0
    backtrack_distribution = Counter()
    zero_backtrack_orderings = []

    for perm in itertools.permutations(variables):
        ordering = list(perm)
        result = solve_with_ordering(clauses, ordering, n_vars)
        total_orderings += 1

        if result.success:
            backtrack_distribution[result.backtracks] += 1
            if result.backtracks < min_backtracks:
                min_backtracks = result.backtracks
            if result.backtracks > max_backtracks:
                max_backtracks = result.backtracks
            if result.backtracks == 0:
                zero_backtrack += 1
                zero_backtrack_orderings.append(ordering)

    return {
        "total_orderings": total_orderings,
        "zero_backtrack_count": zero_backtrack,
        "zero_backtrack_pct": (zero_backtrack / total_orderings * 100) if total_orderings > 0 else 0,
        "min_backtracks": min_backtracks if min_backtracks != float('inf') else -1,
        "max_backtracks": max_backtracks,
        "backtrack_distribution": dict(backtrack_distribution),
        "zero_backtrack_orderings": zero_backtrack_orderings[:10],  # keep first 10
    }


# ─── Heuristic Orderings ───

def ordering_least_frequent(clauses: list[list[int]], n_vars: int) -> list[int]:
    """Coffinhead heuristic: start with least-occurring variable."""
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    # All variables, sorted by frequency (ascending = least first)
    all_vars = list(range(1, n_vars + 1))
    all_vars.sort(key=lambda v: counts.get(v, 0))
    return all_vars


def ordering_most_frequent(clauses: list[list[int]], n_vars: int) -> list[int]:
    """VSIDS-like: start with most-occurring variable."""
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    all_vars = list(range(1, n_vars + 1))
    all_vars.sort(key=lambda v: counts.get(v, 0), reverse=True)
    return all_vars


def ordering_most_constrained(clauses: list[list[int]], n_vars: int) -> list[int]:
    """
    Most constrained first: variables that appear in the most SMALL clauses.
    Intuition: tightly constrained variables have less freedom, resolve them first.
    """
    scores = Counter()
    for clause in clauses:
        weight = 1.0 / len(clause)  # smaller clauses = more constraining
        for lit in clause:
            scores[abs(lit)] += weight
    all_vars = list(range(1, n_vars + 1))
    all_vars.sort(key=lambda v: scores.get(v, 0), reverse=True)
    return all_vars


def ordering_polarity_balance(clauses: list[list[int]], n_vars: int) -> list[int]:
    """
    Variables with most imbalanced polarity first.
    If a variable appears mostly positive (or mostly negative),
    its assignment is more "obvious" — handle those first.
    """
    pos_count = Counter()
    neg_count = Counter()
    for clause in clauses:
        for lit in clause:
            if lit > 0:
                pos_count[abs(lit)] += 1
            else:
                neg_count[abs(lit)] += 1
    all_vars = list(range(1, n_vars + 1))
    all_vars.sort(key=lambda v: abs(pos_count.get(v, 0) - neg_count.get(v, 0)), reverse=True)
    return all_vars


def ordering_random(n_vars: int) -> list[int]:
    """Random ordering for baseline."""
    variables = list(range(1, n_vars + 1))
    random.shuffle(variables)
    return variables


def ordering_natural(n_vars: int) -> list[int]:
    """Natural ordering: 1, 2, 3, ..."""
    return list(range(1, n_vars + 1))


# ─── Backbone Detection ───

def find_backbones_bruteforce(clauses: list[list[int]], n_vars: int) -> dict[int, bool]:
    """
    Find backbone variables by brute-force: enumerate all solutions,
    check which variables are fixed across ALL of them.
    Only feasible for small instances (n <= 15 or so).
    """
    solutions = []

    def enumerate_solutions(assignment, var_idx):
        if var_idx > n_vars:
            # Check if all clauses satisfied
            for clause in clauses:
                satisfied = False
                for lit in clause:
                    v = abs(lit)
                    val = assignment.get(v, True)
                    if (lit > 0 and val) or (lit < 0 and not val):
                        satisfied = True
                        break
                if not satisfied:
                    return
            solutions.append(dict(assignment))
            return

        assignment[var_idx] = True
        enumerate_solutions(assignment, var_idx + 1)
        assignment[var_idx] = False
        enumerate_solutions(assignment, var_idx + 1)
        del assignment[var_idx]

    enumerate_solutions({}, 1)

    if not solutions:
        return {}

    backbones = {}
    for v in range(1, n_vars + 1):
        values = set(sol[v] for sol in solutions)
        if len(values) == 1:
            backbones[v] = next(iter(values))

    return backbones


def ordering_backbone_first(clauses: list[list[int]], n_vars: int) -> list[int]:
    """
    Backbone-first ordering: put backbone variables at the front.
    Remaining variables sorted by frequency.
    """
    backbones = find_backbones_bruteforce(clauses, n_vars)
    backbone_vars = list(backbones.keys())
    non_backbone = [v for v in range(1, n_vars + 1) if v not in backbones]

    # Sort non-backbone by frequency
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    non_backbone.sort(key=lambda v: counts.get(v, 0))

    return backbone_vars + non_backbone


# ─── Endpoint Testing ───

def test_endpoints(clauses: list[list[int]], n_vars: int) -> dict:
    """
    Coffinhead's endpoint test: check all-true and all-false,
    measure which clauses are satisfied/violated, extract structural info.
    """
    all_true = {v: True for v in range(1, n_vars + 1)}
    all_false = {v: False for v in range(1, n_vars + 1)}

    def check_clauses(assignment):
        satisfied = 0
        violated = []
        for i, clause in enumerate(clauses):
            sat = False
            for lit in clause:
                v = abs(lit)
                val = assignment[v]
                if (lit > 0 and val) or (lit < 0 and not val):
                    sat = True
                    break
            if sat:
                satisfied += 1
            else:
                violated.append(i)
        return satisfied, violated

    true_sat, true_violated = check_clauses(all_true)
    false_sat, false_violated = check_clauses(all_false)

    # Variables that need to be TRUE (appear only negative in true-violated clauses)
    # Variables that need to be FALSE (appear only positive in false-violated clauses)
    forced_true = set()
    forced_false = set()

    for ci in true_violated:
        # All-true violated this clause, so all literals are negative
        for lit in clauses[ci]:
            if lit < 0:
                forced_false.add(abs(lit))

    for ci in false_violated:
        # All-false violated this clause, so all literals are positive
        for lit in clauses[ci]:
            if lit > 0:
                forced_true.add(abs(lit))

    return {
        "all_true_satisfied": true_sat,
        "all_true_violated": len(true_violated),
        "all_false_satisfied": false_sat,
        "all_false_violated": len(false_violated),
        "forced_true": sorted(forced_true),
        "forced_false": sorted(forced_false),
        "conflicts": sorted(forced_true & forced_false),
        "total_clauses": len(clauses),
    }


# ─── Main Experiment ───

def run_experiment(n_vars: int = 5, n_instances: int = 50, clause_ratio: float = 3.0, verbose: bool = True):
    """Run the full Phase 1 experiment."""

    print("=" * 70)
    print(f"  THE COFFINHEAD CONJECTURE — Phase 1 Empirical Harness")
    print(f"  Variables: {n_vars}  |  Instances: {n_instances}  |  Clause ratio: {clause_ratio}")
    print("=" * 70)
    print()

    heuristics = {
        "least_frequent": ordering_least_frequent,
        "most_frequent": ordering_most_frequent,
        "most_constrained": ordering_most_constrained,
        "polarity_balance": ordering_polarity_balance,
        "natural": lambda c, n: ordering_natural(n),
        "backbone_first": ordering_backbone_first,
    }

    all_results = []
    instances_with_zero_bt = 0
    instances_without_zero_bt = 0
    heuristic_zero_bt_counts = defaultdict(int)
    heuristic_total_bt = defaultdict(int)

    for inst_idx in range(n_instances):
        result = generate_satisfiable_3sat(n_vars, clause_ratio, seed=inst_idx * 37 + 42)
        if result is None:
            continue
        clauses, planted = result

        if verbose and inst_idx < 3:
            print(f"--- Instance {inst_idx + 1} ---")
            print(f"  Clauses: {len(clauses)}")
            print(f"  Planted solution: {planted}")

        # Brute force all orderings (only feasible for small n)
        t0 = time.time()
        if n_vars <= 8:
            bf_result = check_all_orderings(clauses, n_vars)
            bf_time = time.time() - t0

            has_zero = bf_result["zero_backtrack_count"] > 0
            if has_zero:
                instances_with_zero_bt += 1
            else:
                instances_without_zero_bt += 1

            if verbose and inst_idx < 3:
                print(f"  Brute force ({bf_result['total_orderings']} orderings, {bf_time:.2f}s):")
                print(f"    Zero-backtrack orderings: {bf_result['zero_backtrack_count']} "
                      f"({bf_result['zero_backtrack_pct']:.1f}%)")
                print(f"    Backtrack range: {bf_result['min_backtracks']} - {bf_result['max_backtracks']}")
                print(f"    Distribution: {dict(sorted(bf_result['backtrack_distribution'].items()))}")
                if bf_result['zero_backtrack_orderings']:
                    print(f"    Example zero-BT ordering: {bf_result['zero_backtrack_orderings'][0]}")
        else:
            bf_result = None
            has_zero = None

        # Test heuristics
        for name, heur_fn in heuristics.items():
            if name == "backbone_first" and n_vars > 12:
                continue  # too expensive for large n
            ordering = heur_fn(clauses, n_vars)
            result = solve_with_ordering(clauses, ordering, n_vars)
            heuristic_total_bt[name] += result.backtracks
            if result.backtracks == 0:
                heuristic_zero_bt_counts[name] += 1

            if verbose and inst_idx < 3:
                print(f"  {name}: backtracks={result.backtracks}, decisions={result.decisions}, "
                      f"success={result.success}")

        # Random baseline (average of 10)
        random_bt = []
        for _ in range(10):
            ordering = ordering_random(n_vars)
            result = solve_with_ordering(clauses, ordering, n_vars)
            random_bt.append(result.backtracks)
        avg_random_bt = sum(random_bt) / len(random_bt)
        random_zero = sum(1 for b in random_bt if b == 0)
        heuristic_total_bt["random_avg"] += avg_random_bt
        heuristic_zero_bt_counts["random_avg"] += random_zero / 10.0

        if verbose and inst_idx < 3:
            print(f"  random (avg 10): backtracks={avg_random_bt:.1f}, "
                  f"zero_bt_rate={random_zero / 10:.0%}")

        # Endpoint testing
        ep = test_endpoints(clauses, n_vars)
        if verbose and inst_idx < 3:
            print(f"  Endpoint test: all-T satisfies {ep['all_true_satisfied']}/{ep['total_clauses']}, "
                  f"all-F satisfies {ep['all_false_satisfied']}/{ep['total_clauses']}")
            print(f"    Forced true: {ep['forced_true']}, Forced false: {ep['forced_false']}, "
                  f"Conflicts: {ep['conflicts']}")
            print()

        all_results.append({
            "instance": inst_idx,
            "n_vars": n_vars,
            "n_clauses": len(clauses),
            "brute_force": bf_result,
            "endpoint": ep,
        })

    # ─── Summary ───
    print()
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()

    if n_vars <= 8:
        total = instances_with_zero_bt + instances_without_zero_bt
        print(f"ZERO-BACKTRACK ORDERING EXISTS?")
        print(f"  YES: {instances_with_zero_bt}/{total} instances ({instances_with_zero_bt/total*100:.1f}%)")
        print(f"  NO:  {instances_without_zero_bt}/{total} instances ({instances_without_zero_bt/total*100:.1f}%)")
        print()
        if instances_without_zero_bt == 0:
            print("  >>> EVERY satisfiable instance had at least one zero-backtrack ordering! <<<")
        elif instances_with_zero_bt == 0:
            print("  >>> NO instance had a zero-backtrack ordering. Conjecture FALSIFIED. <<<")
        else:
            pct = instances_with_zero_bt / total * 100
            print(f"  >>> {pct:.1f}% of instances have zero-backtrack orderings. Partial support. <<<")
        print()

    print(f"HEURISTIC COMPARISON (across {n_instances} instances):")
    print(f"  {'Heuristic':<22} {'Zero-BT instances':>20} {'Total backtracks':>18}")
    print(f"  {'-'*22} {'-'*20} {'-'*18}")
    for name in sorted(heuristic_zero_bt_counts.keys()):
        zbt = heuristic_zero_bt_counts[name]
        tbt = heuristic_total_bt[name]
        if isinstance(zbt, float):
            print(f"  {name:<22} {zbt:>18.1f}  {tbt:>18.1f}")
        else:
            print(f"  {name:<22} {zbt:>18d}    {tbt:>18}")
    print()

    return all_results


# ─── Scaling Experiment ───

def run_scaling(max_vars: int = 8, n_instances: int = 30):
    """Test how zero-backtrack ordering frequency scales with problem size."""
    print()
    print("=" * 70)
    print("  SCALING EXPERIMENT — Zero-BT ordering frequency vs problem size")
    print("=" * 70)
    print()
    print(f"  {'n_vars':>6} {'instances':>10} {'has_zero_bt':>12} {'pct':>8} {'avg_zero_bt_pct':>16}")
    print(f"  {'-'*6} {'-'*10} {'-'*12} {'-'*8} {'-'*16}")

    for n_vars in range(3, max_vars + 1):
        has_zero = 0
        total = 0
        zero_bt_pcts = []

        for i in range(n_instances):
            result = generate_satisfiable_3sat(n_vars, clause_ratio=3.0, seed=i * 37 + 42)
            if result is None:
                continue
            clauses, _ = result
            bf = check_all_orderings(clauses, n_vars)
            total += 1
            if bf["zero_backtrack_count"] > 0:
                has_zero += 1
                zero_bt_pcts.append(bf["zero_backtrack_pct"])

        pct = has_zero / total * 100 if total > 0 else 0
        avg_zbt_pct = sum(zero_bt_pcts) / len(zero_bt_pcts) if zero_bt_pcts else 0
        print(f"  {n_vars:>6} {total:>10} {has_zero:>12} {pct:>7.1f}% {avg_zbt_pct:>15.1f}%")

    print()


if __name__ == "__main__":
    # Phase 1a: Small instance deep dive
    print("\n" + "▓" * 70)
    print("  PHASE 1a: Deep dive on 5-variable instances")
    print("▓" * 70 + "\n")
    run_experiment(n_vars=5, n_instances=50, clause_ratio=3.0, verbose=True)

    # Phase 1b: Scaling
    print("\n" + "▓" * 70)
    print("  PHASE 1b: Scaling experiment (3-8 variables)")
    print("▓" * 70 + "\n")
    run_scaling(max_vars=8, n_instances=30)

    # Phase 1c: Slightly larger instances (heuristics only, no brute force)
    print("\n" + "▓" * 70)
    print("  PHASE 1c: Larger instances — heuristics only (15 vars)")
    print("▓" * 70 + "\n")
    run_experiment(n_vars=15, n_instances=30, clause_ratio=3.0, verbose=False)

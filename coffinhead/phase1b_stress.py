"""
THE COFFINHEAD CONJECTURE — Phase 1b: Stress Test
===================================================
Push harder:
1. Phase transition instances (clause ratio 4.26) — hardest random SAT
2. Truly random instances (not planted) — filter for satisfiable
3. Scale to 10+ variables with brute-force ordering search
4. Actively hunt for counterexamples
5. Track how zero-BT ordering % scales (does it decay to 0?)
"""

import random
import itertools
import time
import math
from collections import Counter, defaultdict
from typing import Optional


# ─── SAT Primitives ───

def evaluate(clauses, assignment):
    """Check if assignment satisfies all clauses."""
    for clause in clauses:
        satisfied = False
        for lit in clause:
            v = abs(lit)
            val = assignment.get(v, True)
            if (lit > 0 and val) or (lit < 0 and not val):
                satisfied = True
                break
        if not satisfied:
            return False
    return True


def find_all_solutions(clauses, n_vars):
    """Brute-force all 2^n assignments, return list of solutions."""
    solutions = []
    for bits in range(2 ** n_vars):
        assignment = {}
        for v in range(1, n_vars + 1):
            assignment[v] = bool((bits >> (v - 1)) & 1)
        if evaluate(clauses, assignment):
            solutions.append(assignment)
    return solutions


def generate_random_3sat(n_vars, clause_ratio, seed=None):
    """Truly random 3-SAT. No planted solution."""
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


# ─── Unit Propagation + DPLL ───

def unit_propagate(clauses, assignment):
    """Unit propagation. Returns (assignment, remaining_clauses, contradiction)."""
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
    """DPLL with fixed ordering. Returns (success, backtracks, decisions)."""
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
    """Try all n! orderings. Returns (total, zero_bt_count, min_bt, max_bt, distribution)."""
    variables = list(range(1, n_vars + 1))
    total = 0
    zero_bt = 0
    min_bt = float('inf')
    max_bt = 0
    dist = Counter()
    example_zero = None

    for perm in itertools.permutations(variables):
        ordering = list(perm)
        success, bt, _ = solve_with_ordering(clauses, ordering, n_vars)
        total += 1
        if success:
            dist[bt] += 1
            if bt < min_bt:
                min_bt = bt
            if bt > max_bt:
                max_bt = bt
            if bt == 0:
                zero_bt += 1
                if example_zero is None:
                    example_zero = ordering

    return total, zero_bt, min_bt, max_bt, dict(dist), example_zero


# ─── Heuristic Orderings ───

def ordering_least_frequent(clauses, n_vars):
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    all_vars = list(range(1, n_vars + 1))
    all_vars.sort(key=lambda v: counts.get(v, 0))
    return all_vars


def ordering_most_frequent(clauses, n_vars):
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    all_vars = list(range(1, n_vars + 1))
    all_vars.sort(key=lambda v: counts.get(v, 0), reverse=True)
    return all_vars


# ─── Experiment 1: Phase Transition Stress Test ───

def experiment_phase_transition(n_vars=5, n_instances=100):
    """Test at the hardest clause ratios (near 4.26 phase transition)."""
    print("=" * 70)
    print(f"  EXPERIMENT 1: Phase Transition Stress Test (n={n_vars})")
    print(f"  Truly random 3-SAT, filtering for satisfiable instances")
    print("=" * 70)
    print()

    ratios = [2.0, 3.0, 3.5, 4.0, 4.26, 4.5, 5.0]

    print(f"  {'ratio':>6} {'sat_found':>10} {'tested':>8} {'all_have_0bt':>13} "
          f"{'avg_0bt_pct':>12} {'min_0bt_pct':>12} {'counterex':>10}")
    print(f"  {'-'*6} {'-'*10} {'-'*8} {'-'*13} {'-'*12} {'-'*12} {'-'*10}")

    for ratio in ratios:
        sat_count = 0
        tested = 0
        all_have_zero = 0
        zero_bt_pcts = []
        min_zero_pct = 100.0
        counterexamples = 0

        seed = 0
        while sat_count < n_instances and tested < n_instances * 20:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            tested += 1

            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue

            sat_count += 1
            total, zero_bt, min_bt, max_bt, dist, example = check_all_orderings(clauses, n_vars)
            pct = zero_bt / total * 100 if total > 0 else 0
            zero_bt_pcts.append(pct)

            if pct < min_zero_pct:
                min_zero_pct = pct

            if zero_bt > 0:
                all_have_zero += 1
            else:
                counterexamples += 1
                print(f"\n  !!! COUNTEREXAMPLE at ratio={ratio}, seed={seed-1} !!!")
                print(f"      Clauses: {clauses}")
                print(f"      Solutions: {len(solutions)}")
                print(f"      Min backtracks: {min_bt}, Distribution: {dist}")
                print()

        avg_pct = sum(zero_bt_pcts) / len(zero_bt_pcts) if zero_bt_pcts else 0
        print(f"  {ratio:>6.2f} {sat_count:>10} {tested:>8} {all_have_zero:>10}/{sat_count:<2} "
              f"{avg_pct:>11.1f}% {min_zero_pct:>11.1f}% {counterexamples:>10}")

    print()


# ─── Experiment 2: Scaling with Random Instances ───

def experiment_scaling_random(max_vars=10, n_instances=50):
    """How does zero-BT ordering frequency scale with RANDOM (not planted) instances?"""
    print("=" * 70)
    print(f"  EXPERIMENT 2: Scaling with Truly Random SAT")
    print(f"  Clause ratio 3.5 (moderate), {n_instances} satisfiable instances per size")
    print("=" * 70)
    print()

    print(f"  {'n':>4} {'n!':>10} {'instances':>10} {'all_have_0bt':>13} "
          f"{'avg_0bt_pct':>12} {'min_0bt_pct':>12} {'time':>8}")
    print(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*13} {'-'*12} {'-'*12} {'-'*8}")

    for n_vars in range(3, max_vars + 1):
        t0 = time.time()
        sat_count = 0
        tested = 0
        all_have_zero = 0
        zero_bt_pcts = []
        min_zero_pct = 100.0
        counterexamples = []

        seed = 0
        while sat_count < n_instances and tested < n_instances * 30:
            clauses = generate_random_3sat(n_vars, 3.5, seed=seed)
            seed += 1
            tested += 1

            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue

            sat_count += 1
            total, zero_bt, min_bt, max_bt, dist, example = check_all_orderings(clauses, n_vars)
            pct = zero_bt / total * 100 if total > 0 else 0
            zero_bt_pcts.append(pct)

            if pct < min_zero_pct:
                min_zero_pct = pct

            if zero_bt > 0:
                all_have_zero += 1
            else:
                counterexamples.append((seed - 1, clauses, len(solutions), min_bt))

        elapsed = time.time() - t0
        avg_pct = sum(zero_bt_pcts) / len(zero_bt_pcts) if zero_bt_pcts else 0
        n_fact = math.factorial(n_vars)
        print(f"  {n_vars:>4} {n_fact:>10} {sat_count:>10} {all_have_zero:>10}/{sat_count:<2} "
              f"{avg_pct:>11.1f}% {min_zero_pct:>11.1f}% {elapsed:>7.1f}s")

        if counterexamples:
            for seed_val, cls, n_sol, min_bt in counterexamples[:3]:
                print(f"       COUNTEREXAMPLE: seed={seed_val}, #solutions={n_sol}, min_bt={min_bt}")

    print()


# ─── Experiment 3: Unique Solution Instances (hardest case) ───

def experiment_unique_solution(max_vars=9, n_instances=30):
    """
    Instances with EXACTLY ONE satisfying assignment.
    These should be the hardest — no freedom, every variable is a backbone.
    If zero-BT orderings exist here, that's very strong evidence.
    """
    print("=" * 70)
    print(f"  EXPERIMENT 3: Unique Solution Instances (hardest case)")
    print(f"  Only instances with EXACTLY 1 satisfying assignment")
    print("=" * 70)
    print()

    print(f"  {'n':>4} {'found':>8} {'have_0bt':>10} {'avg_0bt_pct':>12} {'min_0bt_pct':>12} {'time':>8}")
    print(f"  {'-'*4} {'-'*8} {'-'*10} {'-'*12} {'-'*12} {'-'*8}")

    for n_vars in range(3, max_vars + 1):
        t0 = time.time()
        found = 0
        have_zero = 0
        zero_bt_pcts = []
        min_zero_pct = 100.0

        seed = 0
        # Unique solutions are rare at low ratios, need more clauses
        while found < n_instances and seed < n_instances * 200:
            clauses = generate_random_3sat(n_vars, 5.0, seed=seed)
            seed += 1

            solutions = find_all_solutions(clauses, n_vars)
            if len(solutions) != 1:
                continue

            found += 1
            total, zero_bt, min_bt, max_bt, dist, example = check_all_orderings(clauses, n_vars)
            pct = zero_bt / total * 100 if total > 0 else 0
            zero_bt_pcts.append(pct)

            if pct < min_zero_pct:
                min_zero_pct = pct

            if zero_bt > 0:
                have_zero += 1
            else:
                print(f"       !!! COUNTEREXAMPLE: n={n_vars}, seed={seed-1}, "
                      f"min_bt={min_bt}, dist={dist}")
                print(f"           Clauses: {clauses}")

        elapsed = time.time() - t0
        avg_pct = sum(zero_bt_pcts) / len(zero_bt_pcts) if zero_bt_pcts else 0
        print(f"  {n_vars:>4} {found:>8} {have_zero:>7}/{found:<2} "
              f"{avg_pct:>11.1f}% {min_zero_pct:>11.1f}% {elapsed:>7.1f}s")

    print()


# ─── Experiment 4: Heuristic Race at Scale ───

def experiment_heuristic_race(sizes=[10, 15, 20, 25, 30], n_instances=50):
    """
    At sizes too large for brute-force ordering enumeration,
    which heuristic achieves zero backtracks most often?
    """
    print("=" * 70)
    print(f"  EXPERIMENT 4: Heuristic Race at Scale")
    print(f"  Clause ratio 3.5, {n_instances} instances per size")
    print("=" * 70)
    print()

    heuristics = {
        "least_freq": ordering_least_frequent,
        "most_freq": ordering_most_frequent,
    }

    # Add more orderings
    def ordering_natural(c, n):
        return list(range(1, n + 1))

    def ordering_reverse(c, n):
        return list(range(n, 0, -1))

    def ordering_polarity(clauses, n):
        pos = Counter()
        neg = Counter()
        for clause in clauses:
            for lit in clause:
                if lit > 0: pos[abs(lit)] += 1
                else: neg[abs(lit)] += 1
        all_vars = list(range(1, n + 1))
        all_vars.sort(key=lambda v: abs(pos.get(v, 0) - neg.get(v, 0)), reverse=True)
        return all_vars

    def ordering_clause_length(clauses, n):
        """Variables in shortest remaining clauses first."""
        scores = Counter()
        for clause in clauses:
            w = 1.0 / len(clause)
            for lit in clause:
                scores[abs(lit)] += w
        all_vars = list(range(1, n + 1))
        all_vars.sort(key=lambda v: scores.get(v, 0), reverse=True)
        return all_vars

    heuristics["natural"] = ordering_natural
    heuristics["reverse"] = ordering_reverse
    heuristics["polarity"] = ordering_polarity
    heuristics["clause_wt"] = ordering_clause_length

    for n_vars in sizes:
        print(f"  --- n = {n_vars} ---")
        results = defaultdict(lambda: {"zero_bt": 0, "total_bt": 0, "total": 0})

        # Also track random baseline
        random_zero = 0
        random_total_bt = 0

        sat_count = 0
        seed = 0
        while sat_count < n_instances and seed < n_instances * 30:
            clauses = generate_random_3sat(n_vars, 3.5, seed=seed)
            seed += 1

            # Quick satisfiability check via DPLL
            ordering = list(range(1, n_vars + 1))
            success, _, _ = solve_with_ordering(clauses, ordering, n_vars)
            if not success:
                continue

            sat_count += 1
            for name, hfn in heuristics.items():
                o = hfn(clauses, n_vars)
                _, bt, _ = solve_with_ordering(clauses, o, n_vars)
                results[name]["total"] += 1
                results[name]["total_bt"] += bt
                if bt == 0:
                    results[name]["zero_bt"] += 1

            # Random: average of 5
            for _ in range(5):
                ro = list(range(1, n_vars + 1))
                random.shuffle(ro)
                _, bt, _ = solve_with_ordering(clauses, ro, n_vars)
                random_total_bt += bt
                if bt == 0:
                    random_zero += 1

        print(f"  {'heuristic':<14} {'zero_bt':>10} {'avg_bt':>10}")
        print(f"  {'-'*14} {'-'*10} {'-'*10}")
        for name in sorted(results.keys()):
            r = results[name]
            avg_bt = r["total_bt"] / r["total"] if r["total"] > 0 else 0
            print(f"  {name:<14} {r['zero_bt']:>7}/{r['total']:<2} {avg_bt:>10.2f}")

        r_total = sat_count * 5
        r_avg = random_total_bt / r_total if r_total > 0 else 0
        print(f"  {'random(x5)':<14} {random_zero:>7}/{r_total:<2} {r_avg:>10.2f}")
        print()


# ─── Experiment 5: Adversarial Instance Construction ───

def experiment_adversarial(n_vars=6, n_attempts=500):
    """
    Actively TRY to build instances that have NO zero-backtrack ordering.
    Strategy: generate many instances, keep the ones with lowest zero-BT percentage.
    """
    print("=" * 70)
    print(f"  EXPERIMENT 5: Adversarial Counterexample Hunt (n={n_vars})")
    print(f"  Testing {n_attempts} random SAT instances at various clause ratios")
    print(f"  Looking for instances with ZERO zero-backtrack orderings")
    print("=" * 70)
    print()

    worst_pct = 100.0
    worst_instance = None
    counterexamples = 0
    total_tested = 0

    for ratio in [3.0, 3.5, 4.0, 4.26, 4.5, 5.0, 6.0, 7.0, 8.0]:
        ratio_worst = 100.0
        ratio_tested = 0

        for seed in range(n_attempts):
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue

            total_tested += 1
            ratio_tested += 1
            total, zero_bt, min_bt, max_bt, dist, example = check_all_orderings(clauses, n_vars)
            pct = zero_bt / total * 100

            if pct < ratio_worst:
                ratio_worst = pct

            if pct < worst_pct:
                worst_pct = pct
                worst_instance = {
                    "ratio": ratio,
                    "seed": seed,
                    "clauses": clauses,
                    "n_solutions": len(solutions),
                    "zero_bt": zero_bt,
                    "total": total,
                    "pct": pct,
                    "min_bt": min_bt,
                    "dist": dist,
                }

            if zero_bt == 0:
                counterexamples += 1
                print(f"  !!! COUNTEREXAMPLE: ratio={ratio}, seed={seed}, "
                      f"#solutions={len(solutions)}, min_bt={min_bt}")
                print(f"      Clauses: {clauses}")
                print(f"      Distribution: {dist}")

        print(f"  ratio={ratio:.2f}: tested {ratio_tested} satisfiable, "
              f"worst zero-BT% = {ratio_worst:.1f}%")

    print()
    print(f"  TOTAL: {total_tested} satisfiable instances tested, "
          f"{counterexamples} counterexamples found")
    print(f"  WORST CASE: {worst_pct:.1f}% zero-BT orderings")
    if worst_instance:
        w = worst_instance
        print(f"    ratio={w['ratio']}, seed={w['seed']}, #solutions={w['n_solutions']}")
        print(f"    {w['zero_bt']}/{w['total']} orderings are zero-BT")
        print(f"    min backtracks={w['min_bt']}, distribution={w['dist']}")
    print()


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Stress Tests")
    print("▓" * 70 + "\n")

    experiment_phase_transition(n_vars=5, n_instances=100)
    experiment_scaling_random(max_vars=9, n_instances=50)
    experiment_unique_solution(max_vars=8, n_instances=30)
    experiment_heuristic_race(sizes=[10, 15, 20, 30, 40], n_instances=50)
    experiment_adversarial(n_vars=6, n_attempts=500)

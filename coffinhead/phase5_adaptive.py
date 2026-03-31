"""
THE COFFINHEAD CONJECTURE — Phase 5: Adaptive LFF
===================================================
Static LFF picks ordering once. Adaptive LFF recomputes frequencies
after each decision + unit propagation, always choosing the currently
least-frequent unassigned variable in the REMAINING formula.

Also test:
- Adaptive most-frequent (VSIDS-like but recomputed)
- Adaptive polarity (pick most biased variable next)
- Adaptive combined (least-frequent with polarity-guided value choice)
"""

import random
import itertools
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


def simplify(clauses, assignment):
    """Simplify clauses given assignment. Returns remaining unsatisfied clauses."""
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
        if not satisfied:
            new_clauses.append(simplified)
    return new_clauses


# ─── Static ordering solver (for comparison) ───

def solve_static(clauses, ordering, n_vars):
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


# ─── Adaptive Solvers ───

def solve_adaptive_lff(clauses, n_vars):
    """
    Adaptive Least-Frequent-First: after each decision + UP,
    recompute frequencies on REMAINING clauses, pick least frequent.
    """
    backtracks = 0

    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction:
            return None
        if len(clauses) == 0:
            return assignment

        # Find unassigned variables in remaining clauses
        unassigned = set()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var not in assignment:
                    unassigned.add(var)
        if not unassigned:
            return None

        # Recompute frequencies on REMAINING clauses
        counts = Counter()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    counts[var] += 1

        # Pick least frequent
        branch_var = min(unassigned, key=lambda v: counts.get(v, 0))

        # Try True first
        a1 = dict(assignment)
        a1[branch_var] = True
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment)
        a2[branch_var] = False
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_mff(clauses, n_vars):
    """Adaptive Most-Frequent-First."""
    backtracks = 0

    def dpll(clauses, assignment):
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
        counts = Counter()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    counts[var] += 1
        branch_var = max(unassigned, key=lambda v: counts.get(v, 0))
        a1 = dict(assignment)
        a1[branch_var] = True
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment)
        a2[branch_var] = False
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_polarity(clauses, n_vars):
    """
    Adaptive Polarity-First: pick variable with most biased polarity,
    then set it to the dominant polarity (True if more positive, False if more negative).
    """
    backtracks = 0

    def dpll(clauses, assignment):
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

        # Count positive vs negative occurrences
        pos = Counter()
        neg = Counter()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    if lit > 0:
                        pos[var] += 1
                    else:
                        neg[var] += 1

        # Pick most biased
        branch_var = max(unassigned,
                        key=lambda v: abs(pos.get(v, 0) - neg.get(v, 0)))

        # Set to dominant polarity
        value = pos.get(branch_var, 0) >= neg.get(branch_var, 0)

        a1 = dict(assignment)
        a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment)
        a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_lff_polarity(clauses, n_vars):
    """
    Adaptive LFF with polarity-guided value: pick least frequent variable,
    but set it to its dominant polarity instead of always True.
    """
    backtracks = 0

    def dpll(clauses, assignment):
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

        pos = Counter()
        neg = Counter()
        counts = Counter()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    counts[var] += 1
                    if lit > 0:
                        pos[var] += 1
                    else:
                        neg[var] += 1

        # Least frequent variable
        branch_var = min(unassigned, key=lambda v: counts.get(v, 0))
        # Dominant polarity value
        value = pos.get(branch_var, 0) >= neg.get(branch_var, 0)

        a1 = dict(assignment)
        a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment)
        a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_smallest_clause(clauses, n_vars):
    """
    Pick the variable that appears in the smallest remaining clause,
    breaking ties by least-frequent. This is closest to the MRV heuristic
    from constraint satisfaction.
    """
    backtracks = 0

    def dpll(clauses, assignment):
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

        # Find smallest clause
        min_clause_size = float('inf')
        for clause in clauses:
            size = sum(1 for lit in clause if abs(lit) in unassigned)
            if 0 < size < min_clause_size:
                min_clause_size = size

        # Variables in smallest clauses
        candidates = set()
        for clause in clauses:
            size = sum(1 for lit in clause if abs(lit) in unassigned)
            if size == min_clause_size:
                for lit in clause:
                    if abs(lit) in unassigned:
                        candidates.add(abs(lit))

        # Among candidates, pick least frequent overall
        counts = Counter()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var in candidates:
                    counts[var] += 1

        branch_var = min(candidates, key=lambda v: counts.get(v, 0))

        # Polarity-guided value
        pos = sum(1 for c in clauses for l in c if l == branch_var)
        neg = sum(1 for c in clauses for l in c if l == -branch_var)
        value = pos >= neg

        a1 = dict(assignment)
        a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment)
        a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_jeroslow_wang(clauses, n_vars):
    """
    Jeroslow-Wang heuristic: weight each literal by 2^(-clause_length).
    Pick variable with highest J(v) = J(v) + J(-v), set to dominant literal.
    Classic informed SAT heuristic.
    """
    backtracks = 0

    def dpll(clauses, assignment):
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

        # Jeroslow-Wang scoring
        jw_pos = defaultdict(float)
        jw_neg = defaultdict(float)
        for clause in clauses:
            w = 2.0 ** (-len(clause))
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    if lit > 0:
                        jw_pos[var] += w
                    else:
                        jw_neg[var] += w

        # Pick variable with highest total JW score
        branch_var = max(unassigned, key=lambda v: jw_pos.get(v, 0) + jw_neg.get(v, 0))
        value = jw_pos.get(branch_var, 0) >= jw_neg.get(branch_var, 0)

        a1 = dict(assignment)
        a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment)
        a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


# ─── Static LFF for comparison ───

def ordering_least_frequent(clauses, n_vars):
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    return sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0))


# ─── Main Experiments ───

def experiment_adaptive_vs_static(n_vars=6, n_target=500):
    """Head-to-head: static LFF vs adaptive LFF vs other adaptive strategies."""
    print("=" * 70)
    print(f"  EXPERIMENT 1: Adaptive vs Static Heuristics (n={n_vars})")
    print(f"  {n_target} satisfiable instances per ratio")
    print("=" * 70)

    solvers = {
        "static_lff": lambda c, n: solve_static(c, ordering_least_frequent(c, n), n),
        "adaptive_lff": solve_adaptive_lff,
        "adaptive_mff": solve_adaptive_mff,
        "adaptive_polarity": solve_adaptive_polarity,
        "adaptive_lff_pol": solve_adaptive_lff_polarity,
        "adaptive_sm_clause": solve_adaptive_smallest_clause,
        "adaptive_jw": solve_adaptive_jeroslow_wang,
    }

    totals = {name: {"zero_bt": 0, "total_bt": 0, "total": 0} for name in solvers}

    for ratio in [2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
        ratio_results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0} for name in solvers}

        found = 0
        seed = 0
        while found < n_target and seed < n_target * 20:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            # Quick sat check
            _, bt = solve_static(clauses, list(range(1, n_vars + 1)), n_vars)
            # Actually need to check satisfiability properly
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue
            found += 1

            for name, solver in solvers.items():
                success, bt = solver(clauses, n_vars)
                ratio_results[name]["count"] += 1
                ratio_results[name]["total_bt"] += bt
                if bt == 0:
                    ratio_results[name]["zero_bt"] += 1
                totals[name]["total"] += 1
                totals[name]["total_bt"] += bt
                if bt == 0:
                    totals[name]["zero_bt"] += 1

        print(f"\n  ratio={ratio}:")
        print(f"  {'Solver':<22} {'Zero-BT':>10} {'Avg BT':>10}")
        print(f"  {'-'*22} {'-'*10} {'-'*10}")
        for name in solvers:
            r = ratio_results[name]
            pct = r["zero_bt"] / r["count"] * 100 if r["count"] > 0 else 0
            avg = r["total_bt"] / r["count"] if r["count"] > 0 else 0
            print(f"  {name:<22} {r['zero_bt']:>5}/{r['count']:<4} {avg:>10.2f}")

    print(f"\n  === TOTALS ACROSS ALL RATIOS ===")
    print(f"  {'Solver':<22} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>10} {'Total BT':>10}")
    print(f"  {'-'*22} {'-'*10} {'-'*8} {'-'*10} {'-'*10}")
    for name in sorted(totals.keys(), key=lambda n: -totals[n]["zero_bt"]):
        t = totals[name]
        pct = t["zero_bt"] / t["total"] * 100 if t["total"] > 0 else 0
        avg = t["total_bt"] / t["total"] if t["total"] > 0 else 0
        print(f"  {name:<22} {t['zero_bt']:>5}/{t['total']:<4} {pct:>7.1f}% {avg:>10.2f} {t['total_bt']:>10}")


def experiment_adaptive_scaling(sizes=[6, 7, 8, 9, 10, 12, 15], n_target=100):
    """How do adaptive solvers scale?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 2: Adaptive Solver Scaling")
    print("=" * 70)

    solvers = {
        "static_lff": lambda c, n: solve_static(c, ordering_least_frequent(c, n), n),
        "adaptive_lff": solve_adaptive_lff,
        "adaptive_lff_pol": solve_adaptive_lff_polarity,
        "adaptive_jw": solve_adaptive_jeroslow_wang,
    }

    for n_vars in sizes:
        print(f"\n  n={n_vars}:")
        results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0} for name in solvers}

        found = 0
        seed = 0
        ratio = 3.5
        while found < n_target and seed < n_target * 30:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1

            # For larger n, can't brute force solutions — just check satisfiability via solver
            success, _ = solve_adaptive_lff(clauses, n_vars)
            if not success:
                continue
            found += 1

            for name, solver in solvers.items():
                success, bt = solver(clauses, n_vars)
                results[name]["count"] += 1
                results[name]["total_bt"] += bt
                if bt == 0:
                    results[name]["zero_bt"] += 1

        print(f"  {'Solver':<22} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>10}")
        print(f"  {'-'*22} {'-'*10} {'-'*8} {'-'*10}")
        for name in solvers:
            r = results[name]
            pct = r["zero_bt"] / r["count"] * 100 if r["count"] > 0 else 0
            avg = r["total_bt"] / r["count"] if r["count"] > 0 else 0
            print(f"  {name:<22} {r['zero_bt']:>5}/{r['count']:<4} {pct:>7.1f}% {avg:>10.2f}")


def experiment_adaptive_on_failures(n_vars=6, n_target=100):
    """Specifically test adaptive solvers on instances where static LFF fails."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 3: Adaptive Solvers on Static LFF Failures (n={n_vars})")
    print("=" * 70)

    solvers = {
        "adaptive_lff": solve_adaptive_lff,
        "adaptive_mff": solve_adaptive_mff,
        "adaptive_polarity": solve_adaptive_polarity,
        "adaptive_lff_pol": solve_adaptive_lff_polarity,
        "adaptive_sm_clause": solve_adaptive_smallest_clause,
        "adaptive_jw": solve_adaptive_jeroslow_wang,
    }

    results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0} for name in solvers}
    # Also check if ANY has zero BT
    any_zero = 0
    all_fail = 0
    total = 0

    seed = 0
    while total < n_target and seed < 50000:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        solutions = find_all_solutions(clauses, n_vars)
        if not solutions:
            continue

        ordering = ordering_least_frequent(clauses, n_vars)
        _, bt = solve_static(clauses, ordering, n_vars)
        if bt == 0:
            continue

        total += 1
        got_zero = False
        for name, solver in solvers.items():
            _, abt = solver(clauses, n_vars)
            results[name]["count"] += 1
            results[name]["total_bt"] += abt
            if abt == 0:
                results[name]["zero_bt"] += 1
                got_zero = True

        if got_zero:
            any_zero += 1
        else:
            all_fail += 1

    print(f"\n  Tested {total} instances where static LFF fails")
    print(f"  At least one adaptive solver achieves zero-BT: {any_zero}/{total} ({any_zero/total*100:.1f}%)")
    print(f"  ALL adaptive solvers fail: {all_fail}/{total} ({all_fail/total*100:.1f}%)")
    print()
    print(f"  {'Solver':<22} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>10}")
    print(f"  {'-'*22} {'-'*10} {'-'*8} {'-'*10}")
    for name in sorted(results.keys(), key=lambda n: -results[n]["zero_bt"]):
        r = results[name]
        pct = r["zero_bt"] / r["count"] * 100 if r["count"] > 0 else 0
        avg = r["total_bt"] / r["count"] if r["count"] > 0 else 0
        print(f"  {name:<22} {r['zero_bt']:>5}/{r['count']:<4} {pct:>7.1f}% {avg:>10.2f}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 5: Adaptive LFF")
    print("▓" * 70)

    experiment_adaptive_vs_static(n_vars=6, n_target=300)
    experiment_adaptive_on_failures(n_vars=6, n_target=200)
    experiment_adaptive_scaling(sizes=[6, 7, 8, 9, 10, 12, 15], n_target=100)

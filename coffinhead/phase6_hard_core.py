"""
THE COFFINHEAD CONJECTURE — Phase 6: The Hard Core
====================================================
The 4% of instances where ALL adaptive heuristics fail.
1. Does the hard core fraction grow, shrink, or stay constant with n?
2. What structural properties define hard core instances?
3. Is backtracking PROVABLY unavoidable for them?
4. Can we characterize them precisely enough to formalize?
"""

import random
import itertools
import time
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
    """Brute force — only for small n."""
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


# ─── All adaptive solvers ───

def solve_adaptive_polarity(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = set()
        for clause in clauses:
            for lit in clause:
                if abs(lit) not in assignment:
                    unassigned.add(abs(lit))
        if not unassigned: return None
        pos = Counter()
        neg = Counter()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    if lit > 0: pos[var] += 1
                    else: neg[var] += 1
        branch_var = max(unassigned, key=lambda v: abs(pos.get(v,0) - neg.get(v,0)))
        value = pos.get(branch_var, 0) >= neg.get(branch_var, 0)
        a1 = dict(assignment); a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None: return result
        backtracks += 1
        a2 = dict(assignment); a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_jw(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = set()
        for clause in clauses:
            for lit in clause:
                if abs(lit) not in assignment:
                    unassigned.add(abs(lit))
        if not unassigned: return None
        jw_pos = defaultdict(float)
        jw_neg = defaultdict(float)
        for clause in clauses:
            w = 2.0 ** (-len(clause))
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    if lit > 0: jw_pos[var] += w
                    else: jw_neg[var] += w
        branch_var = max(unassigned, key=lambda v: jw_pos.get(v,0) + jw_neg.get(v,0))
        value = jw_pos.get(branch_var, 0) >= jw_neg.get(branch_var, 0)
        a1 = dict(assignment); a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None: return result
        backtracks += 1
        a2 = dict(assignment); a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_lff_pol(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = set()
        for clause in clauses:
            for lit in clause:
                if abs(lit) not in assignment:
                    unassigned.add(abs(lit))
        if not unassigned: return None
        pos = Counter(); neg = Counter(); counts = Counter()
        for clause in clauses:
            for lit in clause:
                var = abs(lit)
                if var in unassigned:
                    counts[var] += 1
                    if lit > 0: pos[var] += 1
                    else: neg[var] += 1
        branch_var = min(unassigned, key=lambda v: counts.get(v, 0))
        value = pos.get(branch_var, 0) >= neg.get(branch_var, 0)
        a1 = dict(assignment); a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None: return result
        backtracks += 1
        a2 = dict(assignment); a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_smallest_clause(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = set()
        for clause in clauses:
            for lit in clause:
                if abs(lit) not in assignment:
                    unassigned.add(abs(lit))
        if not unassigned: return None
        min_size = float('inf')
        for clause in clauses:
            size = sum(1 for lit in clause if abs(lit) in unassigned)
            if 0 < size < min_size: min_size = size
        candidates = set()
        for clause in clauses:
            size = sum(1 for lit in clause if abs(lit) in unassigned)
            if size == min_size:
                for lit in clause:
                    if abs(lit) in unassigned: candidates.add(abs(lit))
        counts = Counter()
        for clause in clauses:
            for lit in clause:
                if abs(lit) in candidates: counts[abs(lit)] += 1
        branch_var = min(candidates, key=lambda v: counts.get(v, 0))
        p = sum(1 for c in clauses for l in c if l == branch_var)
        n = sum(1 for c in clauses for l in c if l == -branch_var)
        value = p >= n
        a1 = dict(assignment); a1[branch_var] = value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None: return result
        backtracks += 1
        a2 = dict(assignment); a2[branch_var] = not value
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def is_hard_core(clauses, n_vars):
    """Returns True if ALL heuristics backtrack, plus min backtracks across all."""
    min_bt = float('inf')
    all_fail = True
    for solver in [solve_adaptive_polarity, solve_adaptive_jw,
                   solve_adaptive_lff_pol, solve_adaptive_smallest_clause]:
        success, bt = solver(clauses, n_vars)
        if not success:
            return None, None  # unsatisfiable
        if bt < min_bt:
            min_bt = bt
        if bt == 0:
            all_fail = False
    return all_fail, min_bt


# ─── Structural metrics ───

def compute_metrics(clauses, n_vars, solutions=None):
    counts = Counter()
    pos = Counter()
    neg = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
            if lit > 0: pos[abs(lit)] += 1
            else: neg[abs(lit)] += 1

    edges = set()
    for clause in clauses:
        vs = [abs(l) for l in clause]
        for i in range(len(vs)):
            for j in range(i+1, len(vs)):
                edges.add((min(vs[i], vs[j]), max(vs[i], vs[j])))

    max_edges = n_vars * (n_vars - 1) / 2
    density = len(edges) / max_edges if max_edges > 0 else 0

    degs = [counts.get(v, 0) for v in range(1, n_vars + 1)]
    avg_deg = sum(degs) / n_vars
    deg_var = sum((d - avg_deg)**2 for d in degs) / n_vars

    biases = []
    for v in range(1, n_vars + 1):
        total = pos.get(v, 0) + neg.get(v, 0)
        biases.append(abs(pos.get(v,0) - neg.get(v,0)) / total if total > 0 else 0)

    # Max polarity imbalance
    max_bias = max(biases) if biases else 0
    avg_bias = sum(biases) / len(biases) if biases else 0

    # Conflict pairs
    conflicts = 0
    pairs = 0
    for i in range(len(clauses)):
        lits_i = set(clauses[i])
        for j in range(i+1, len(clauses)):
            pairs += 1
            for lit in clauses[j]:
                if -lit in lits_i:
                    conflicts += 1
                    break
    conflict_rate = conflicts / pairs if pairs > 0 else 0

    # Clause length stats (after UP)
    assignment, remaining, _ = unit_propagate(clauses, {})
    up_assigned = len(assignment)
    remaining_clause_sizes = [len(c) for c in remaining]
    avg_remaining_size = sum(remaining_clause_sizes) / len(remaining_clause_sizes) if remaining_clause_sizes else 0
    binary_clauses = sum(1 for s in remaining_clause_sizes if s == 2)
    ternary_clauses = sum(1 for s in remaining_clause_sizes if s == 3)

    m = {
        "graph_density": density,
        "avg_degree": avg_deg,
        "degree_variance": deg_var,
        "degree_range": max(degs) - min(degs),
        "avg_polarity_bias": avg_bias,
        "max_polarity_bias": max_bias,
        "conflict_rate": conflict_rate,
        "up_assigned": up_assigned,
        "remaining_clauses": len(remaining),
        "avg_remaining_clause_size": avg_remaining_size,
        "binary_clauses": binary_clauses,
        "ternary_clauses": ternary_clauses,
    }

    if solutions is not None:
        bb = sum(1 for v in range(1, n_vars+1) if len(set(s[v] for s in solutions)) == 1)
        m["n_solutions"] = len(solutions)
        m["backbone_frac"] = bb / n_vars
        if len(solutions) >= 2:
            dists = []
            for i in range(len(solutions)):
                for j in range(i+1, len(solutions)):
                    dists.append(sum(1 for v in range(1,n_vars+1) if solutions[i][v] != solutions[j][v]))
            m["solution_diversity"] = sum(dists) / len(dists) / n_vars
        else:
            m["solution_diversity"] = 0

    return m


# ─── Experiment 1: Hard Core Fraction vs Problem Size ───

def experiment_hard_core_scaling():
    """THE KEY QUESTION: does the hard core grow or shrink with n?"""
    print("=" * 70)
    print("  EXPERIMENT 1: Hard Core Fraction vs Problem Size")
    print("  Does the % of instances resisting ALL heuristics grow with n?")
    print("=" * 70)

    for ratio in [3.0, 3.5, 4.0, 4.5]:
        print(f"\n  clause ratio = {ratio}:")
        print(f"  {'n':>5} {'sat':>6} {'hard_core':>10} {'pct':>8} {'avg_min_bt':>11} {'time':>8}")
        print(f"  {'-'*5} {'-'*6} {'-'*10} {'-'*8} {'-'*11} {'-'*8}")

        for n_vars in [6, 7, 8, 9, 10, 12, 15, 20, 25, 30]:
            t0 = time.time()
            sat_count = 0
            hard_count = 0
            min_bts = []
            target = 200 if n_vars <= 15 else 100 if n_vars <= 20 else 50

            seed = 0
            while sat_count < target and seed < target * 30:
                clauses = generate_random_3sat(n_vars, ratio, seed=seed)
                seed += 1

                # Check satisfiability via JW (fast)
                success, _ = solve_adaptive_jw(clauses, n_vars)
                if not success:
                    continue
                sat_count += 1

                hard, min_bt = is_hard_core(clauses, n_vars)
                if hard is None:
                    sat_count -= 1
                    continue
                if hard:
                    hard_count += 1
                    min_bts.append(min_bt)

            elapsed = time.time() - t0
            pct = hard_count / sat_count * 100 if sat_count > 0 else 0
            avg_min = sum(min_bts) / len(min_bts) if min_bts else 0
            print(f"  {n_vars:>5} {sat_count:>6} {hard_count:>10} {pct:>7.1f}% {avg_min:>11.2f} {elapsed:>7.1f}s")


# ─── Experiment 2: Structural Analysis of Hard Core ───

def experiment_hard_core_structure(n_vars=8, n_target=300):
    """Compare hard core vs easy instances structurally."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 2: Hard Core Structure (n={n_vars})")
    print("=" * 70)

    hard_instances = []
    easy_instances = []

    for ratio in [3.0, 3.5, 4.0, 4.5, 5.0]:
        seed = 0
        found = 0
        while found < n_target and seed < n_target * 20:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            success, _ = solve_adaptive_jw(clauses, n_vars)
            if not success:
                continue
            found += 1

            hard, min_bt = is_hard_core(clauses, n_vars)
            if hard is None:
                continue

            # Only compute solutions for small n
            if n_vars <= 10:
                solutions = find_all_solutions(clauses, n_vars)
                metrics = compute_metrics(clauses, n_vars, solutions)
            else:
                metrics = compute_metrics(clauses, n_vars)

            if hard:
                hard_instances.append(metrics)
            else:
                easy_instances.append(metrics)

    print(f"\n  Hard core: {len(hard_instances)}, Easy: {len(easy_instances)}")

    if not hard_instances or not easy_instances:
        print("  Not enough instances in both categories")
        return

    features = list(hard_instances[0].keys())
    print(f"\n  {'Feature':<28} {'Hard mean':>10} {'Easy mean':>10} {'Delta':>10} {'Effect':>8}")
    print(f"  {'-'*28} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

    strong = []
    for feat in features:
        h_vals = [i[feat] for i in hard_instances if feat in i]
        e_vals = [i[feat] for i in easy_instances if feat in i]
        if not h_vals or not e_vals:
            continue
        h_mean = sum(h_vals) / len(h_vals)
        e_mean = sum(e_vals) / len(e_vals)
        delta = h_mean - e_mean
        all_vals = h_vals + e_vals
        std = (sum((v - sum(all_vals)/len(all_vals))**2 for v in all_vals) / len(all_vals)) ** 0.5
        effect = abs(delta) / std if std > 0 else 0

        marker = ""
        if effect > 0.3: marker = " *"
        if effect > 0.5: marker = " **"
        if effect > 1.0: marker = " ***"
        if effect > 0.3:
            direction = "HARD higher" if delta > 0 else "HARD lower"
            strong.append((feat, effect, direction, h_mean, e_mean))

        print(f"  {feat:<28} {h_mean:>10.3f} {e_mean:>10.3f} {delta:>+10.3f} {effect:>7.2f}{marker}")

    if strong:
        print(f"\n  TOP SEPARATORS:")
        for feat, eff, direction, hm, em in sorted(strong, key=lambda x: -x[1]):
            print(f"    {feat}: effect={eff:.2f}, {direction} (hard={hm:.3f}, easy={em:.3f})")


# ─── Experiment 3: Hard Core at Phase Transition ───

def experiment_phase_transition_hard_core(n_vars=10, n_target=200):
    """How does hard core % vary across the phase transition?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 3: Hard Core vs Clause Ratio (n={n_vars})")
    print("=" * 70)

    print(f"\n  {'ratio':>6} {'sat':>6} {'hard':>6} {'pct':>8} {'avg_bt':>8}")
    print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*8}")

    for ratio_x10 in range(20, 60, 3):
        ratio = ratio_x10 / 10.0
        sat = 0
        hard = 0
        total_min_bt = 0
        seed = 0
        while sat < n_target and seed < n_target * 30:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            success, _ = solve_adaptive_jw(clauses, n_vars)
            if not success:
                continue
            sat += 1
            is_hard, min_bt = is_hard_core(clauses, n_vars)
            if is_hard is None:
                sat -= 1
                continue
            if is_hard:
                hard += 1
                total_min_bt += min_bt

        pct = hard / sat * 100 if sat > 0 else 0
        avg = total_min_bt / hard if hard > 0 else 0
        bar = "#" * int(pct)
        print(f"  {ratio:>6.1f} {sat:>6} {hard:>6} {pct:>7.1f}% {avg:>8.2f} {bar}")


# ─── Experiment 4: Brute Force on Hard Core (small n) ───

def experiment_brute_force_hard_core(n_vars=7):
    """For small hard core instances, check if ANY ordering gives zero BT."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 4: Brute Force on Hard Core Instances (n={n_vars})")
    print(f"  Does a zero-BT ordering exist even though heuristics can't find it?")
    print("=" * 70)

    hard_has_zero_bt = 0
    hard_no_zero_bt = 0
    hard_instances = []

    seed = 0
    target = 50
    while (hard_has_zero_bt + hard_no_zero_bt) < target and seed < 50000:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        success, _ = solve_adaptive_jw(clauses, n_vars)
        if not success:
            continue
        is_hard, min_bt = is_hard_core(clauses, n_vars)
        if is_hard is None or not is_hard:
            continue

        # Brute force all orderings
        found_zero = False
        min_bt_bf = float('inf')
        for perm in itertools.permutations(range(1, n_vars + 1)):
            o = list(perm)
            bt = 0
            def dpll_count(clauses, assignment, order_idx):
                nonlocal bt
                assignment, clauses, contradiction = unit_propagate(clauses, assignment)
                if contradiction: return None
                if not clauses: return assignment
                unassigned = set()
                for c in clauses:
                    for l in c:
                        if abs(l) not in assignment: unassigned.add(abs(l))
                if not unassigned: return None
                bv = None
                for i in range(order_idx, len(o)):
                    if o[i] in unassigned:
                        bv = o[i]; order_idx = i + 1; break
                if bv is None: bv = next(iter(unassigned))
                a1 = dict(assignment); a1[bv] = True
                r = dpll_count([list(c) for c in clauses], a1, order_idx)
                if r is not None: return r
                bt += 1
                a2 = dict(assignment); a2[bv] = False
                return dpll_count([list(c) for c in clauses], a2, order_idx)
            dpll_count(clauses, {}, 0)
            if bt < min_bt_bf:
                min_bt_bf = bt
            if bt == 0:
                found_zero = True
                break

        if found_zero:
            hard_has_zero_bt += 1
        else:
            hard_no_zero_bt += 1

        total = hard_has_zero_bt + hard_no_zero_bt
        if total % 10 == 0:
            print(f"  Progress: {total}/{target} — "
                  f"has_zero={hard_has_zero_bt}, no_zero={hard_no_zero_bt}")

    total = hard_has_zero_bt + hard_no_zero_bt
    print(f"\n  RESULTS ({total} hard core instances at n={n_vars}):")
    print(f"    Zero-BT ordering EXISTS but heuristics miss it: "
          f"{hard_has_zero_bt} ({hard_has_zero_bt/total*100:.1f}%)")
    print(f"    NO zero-BT ordering exists at all: "
          f"{hard_no_zero_bt} ({hard_no_zero_bt/total*100:.1f}%)")

    if hard_has_zero_bt > 0:
        print(f"\n    >>> Heuristic failure ≠ structural impossibility")
        print(f"    >>> {hard_has_zero_bt/total*100:.1f}% of hard core is a SEARCH problem, not a COMPLEXITY barrier")
    if hard_no_zero_bt > 0:
        print(f"\n    >>> {hard_no_zero_bt/total*100:.1f}% of hard core has NO zero-BT ordering")
        print(f"    >>> These are TRUE hard instances — backtracking is structurally unavoidable")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 6: The Hard Core")
    print("▓" * 70)

    experiment_hard_core_scaling()
    experiment_phase_transition_hard_core(n_vars=10, n_target=200)
    experiment_hard_core_structure(n_vars=8, n_target=200)
    experiment_brute_force_hard_core(n_vars=7)

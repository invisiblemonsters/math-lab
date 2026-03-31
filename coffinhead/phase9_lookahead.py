"""
THE COFFINHEAD CONJECTURE — Phase 9: Multi-Step Lookahead
==========================================================
Max-yield (1-step lookahead) gets 48% on hard core.
Can 2-step or 3-step lookahead close the gap to 100%?

If k-step lookahead with polynomial k solves everything,
that's a polynomial-time SAT algorithm. That's P=NP.
"""

import random
from collections import Counter, defaultdict
import time


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


def get_unassigned(clauses, assignment):
    unassigned = set()
    for c in clauses:
        for l in c:
            if abs(l) not in assignment:
                unassigned.add(abs(l))
    return unassigned


def propagate_and_simplify(clauses, assignment, var, value):
    """Set var=value, run UP. Return (new_assignment, remaining_clauses, contradiction)."""
    new_a = dict(assignment)
    new_a[var] = value
    return unit_propagate(clauses, new_a)


# ─── Lookahead scoring ───

def score_1step(clauses, assignment, var, value, n_vars):
    """1-step lookahead: propagation yield."""
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000  # bad
    n_forced = len(new_a) - len(assignment) - 1  # minus the decision itself
    n_eliminated = len(clauses) - len(remaining)
    return n_forced + n_eliminated


def score_2step(clauses, assignment, var, value, n_vars):
    """
    2-step lookahead: set var=value, propagate, then for each remaining
    unassigned variable, measure best 1-step yield. Return sum of:
    - immediate yield
    - best available yield at next step
    """
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000

    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))

    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 100  # solved!

    # Best 1-step yield available at next step
    best_next = -1000
    for v2 in unassigned:
        for val2 in [True, False]:
            s = score_1step(remaining, new_a, v2, val2, n_vars)
            if s > best_next:
                best_next = s

    return immediate + (best_next if best_next > -1000 else 0)


def score_2step_avg(clauses, assignment, var, value, n_vars):
    """
    2-step lookahead variant: instead of best next yield,
    use AVERAGE next yield across all safe choices.
    Measures how good the LANDSCAPE is after this decision.
    """
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000

    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))

    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 100

    yields = []
    for v2 in unassigned:
        for val2 in [True, False]:
            s = score_1step(remaining, new_a, v2, val2, n_vars)
            if s > -1000:
                yields.append(s)

    avg_next = sum(yields) / len(yields) if yields else 0
    return immediate + avg_next


def score_2step_min(clauses, assignment, var, value, n_vars):
    """
    2-step lookahead: measure WORST-CASE next yield.
    Pick the choice that leaves the best worst-case — minimax style.
    """
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000

    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))

    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 100

    # For each next variable, what's its BEST yield?
    # The min across those is the worst-case
    var_best = []
    for v2 in unassigned:
        best = -1000
        for val2 in [True, False]:
            s = score_1step(remaining, new_a, v2, val2, n_vars)
            if s > best:
                best = s
        var_best.append(best)

    worst_next = min(var_best) if var_best else 0
    return immediate + worst_next


def score_2step_freedom(clauses, assignment, var, value, n_vars):
    """
    2-step lookahead: count how many next variables have BOTH values safe.
    Maximize remaining freedom after this decision.
    """
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000

    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))

    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 100

    both_safe_count = 0
    for v2 in unassigned:
        _, _, ct = propagate_and_simplify(remaining, new_a, v2, True)
        _, _, cf = propagate_and_simplify(remaining, new_a, v2, False)
        if not ct and not cf:
            both_safe_count += 1

    return immediate + both_safe_count * 2


def score_3step(clauses, assignment, var, value, n_vars):
    """3-step lookahead: 1-step yield + best 2-step yield at next level."""
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000

    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))

    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 200

    best_next = -1000
    for v2 in unassigned:
        for val2 in [True, False]:
            s = score_2step(remaining, new_a, v2, val2, n_vars)
            if s > best_next:
                best_next = s

    return immediate + (best_next if best_next > -1000 else 0)


# ─── Solvers ───

def make_lookahead_solver(score_fn, name="lookahead"):
    """Create an adaptive solver using a given scoring function."""
    def solver(clauses, n_vars):
        backtracks = 0
        def dpll(clauses, assignment):
            nonlocal backtracks
            assignment, clauses, contradiction = unit_propagate(clauses, assignment)
            if contradiction: return None
            if not clauses: return assignment
            unassigned = get_unassigned(clauses, assignment)
            if not unassigned: return None

            # Score all (variable, value) pairs
            candidates = []
            for v in unassigned:
                for value in [True, False]:
                    s = score_fn(clauses, assignment, v, value, n_vars)
                    candidates.append((s, v, value))

            candidates.sort(reverse=True)

            # Pick best non-contradicting
            best_var = None
            best_value = True
            for s, v, val in candidates:
                if s > -1000:
                    best_var = v
                    best_value = val
                    break

            if best_var is None:
                best_var = next(iter(unassigned))
                best_value = True

            a1 = dict(assignment); a1[best_var] = best_value
            result = dpll([list(c) for c in clauses], a1)
            if result is not None: return result
            backtracks += 1
            a2 = dict(assignment); a2[best_var] = not best_value
            return dpll([list(c) for c in clauses], a2)

        result = dpll(clauses, {})
        return result is not None, backtracks
    return solver


# Existing solvers for comparison
def solve_adaptive_jw(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None
        jw_pos = defaultdict(float); jw_neg = defaultdict(float)
        for c in clauses:
            w = 2.0 ** (-len(c))
            for l in c:
                v = abs(l)
                if v in unassigned:
                    if l > 0: jw_pos[v] += w
                    else: jw_neg[v] += w
        bv = max(unassigned, key=lambda v: jw_pos.get(v,0)+jw_neg.get(v,0))
        val = jw_pos.get(bv,0) >= jw_neg.get(bv,0)
        a1 = dict(assignment); a1[bv] = val
        r = dpll([list(c) for c in clauses], a1)
        if r is not None: return r
        backtracks += 1
        a2 = dict(assignment); a2[bv] = not val
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_polarity(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None
        pos = Counter(); neg = Counter()
        for c in clauses:
            for l in c:
                v = abs(l)
                if v in unassigned:
                    if l > 0: pos[v] += 1
                    else: neg[v] += 1
        bv = max(unassigned, key=lambda v: abs(pos.get(v,0)-neg.get(v,0)))
        val = pos.get(bv,0) >= neg.get(bv,0)
        a1 = dict(assignment); a1[bv] = val
        r = dpll([list(c) for c in clauses], a1)
        if r is not None: return r
        backtracks += 1
        a2 = dict(assignment); a2[bv] = not val
        return dpll([list(c) for c in clauses], a2)
    result = dpll(clauses, {})
    return result is not None, backtracks


def is_hard_core(clauses, n_vars):
    for solver in [solve_adaptive_polarity, solve_adaptive_jw]:
        success, bt = solver(clauses, n_vars)
        if not success: return None
        if bt == 0: return False
    return True


# ─── Experiments ───

def experiment_lookahead_comparison(n_vars=7, n_target=200):
    """Compare 1-step, 2-step variants, and 3-step lookahead."""
    print("=" * 70)
    print(f"  EXPERIMENT 1: Lookahead Depth Comparison (n={n_vars})")
    print("=" * 70)

    solvers = {
        "jw": solve_adaptive_jw,
        "polarity": solve_adaptive_polarity,
        "1step_yield": make_lookahead_solver(score_1step),
        "2step_best": make_lookahead_solver(score_2step),
        "2step_avg": make_lookahead_solver(score_2step_avg),
        "2step_min": make_lookahead_solver(score_2step_min),
        "2step_freedom": make_lookahead_solver(score_2step_freedom),
    }

    results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0, "time": 0}
               for name in solvers}

    found = 0
    seed = 0
    while found < n_target and seed < n_target * 20:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        success, _ = solve_adaptive_jw(clauses, n_vars)
        if not success:
            continue
        found += 1

        for name, solver in solvers.items():
            t0 = time.time()
            _, bt = solver(clauses, n_vars)
            elapsed = time.time() - t0
            results[name]["count"] += 1
            results[name]["total_bt"] += bt
            results[name]["time"] += elapsed
            if bt == 0:
                results[name]["zero_bt"] += 1

    print(f"\n  All satisfiable instances ({found} instances, ratio=4.0):")
    print(f"  {'Solver':<20} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>8} {'Time':>8}")
    print(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*8} {'-'*8}")
    for name in sorted(results.keys(), key=lambda n: -results[n]["zero_bt"]):
        r = results[name]
        pct = r["zero_bt"] / r["count"] * 100
        avg = r["total_bt"] / r["count"]
        t = r["time"]
        print(f"  {name:<20} {r['zero_bt']:>5}/{r['count']:<4} {pct:>7.1f}% {avg:>8.2f} {t:>7.2f}s")


def experiment_hard_core_lookahead(n_vars=7, n_target=50):
    """Test lookahead solvers specifically on hard core instances."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 2: Lookahead on Hard Core (n={n_vars})")
    print("=" * 70)

    solvers = {
        "jw": solve_adaptive_jw,
        "polarity": solve_adaptive_polarity,
        "1step": make_lookahead_solver(score_1step),
        "2step_best": make_lookahead_solver(score_2step),
        "2step_avg": make_lookahead_solver(score_2step_avg),
        "2step_freedom": make_lookahead_solver(score_2step_freedom),
    }

    results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0}
               for name in solvers}

    found = 0
    seed = 0
    while found < n_target and seed < 100000:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        if not is_hard_core(clauses, n_vars):
            continue
        found += 1

        for name, solver in solvers.items():
            _, bt = solver(clauses, n_vars)
            results[name]["count"] += 1
            results[name]["total_bt"] += bt
            if bt == 0:
                results[name]["zero_bt"] += 1

        if found % 10 == 0:
            print(f"  progress: {found}/{n_target}")

    print(f"\n  Hard core only ({found} instances):")
    print(f"  {'Solver':<20} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>8}")
    print(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*8}")
    for name in sorted(results.keys(), key=lambda n: -results[n]["zero_bt"]):
        r = results[name]
        pct = r["zero_bt"] / r["count"] * 100
        avg = r["total_bt"] / r["count"]
        print(f"  {name:<20} {r['zero_bt']:>5}/{r['count']:<4} {pct:>7.1f}% {avg:>8.2f}")


def experiment_3step_on_hard_core(n_vars=7, n_target=30):
    """3-step is expensive. Test on small hard core sample."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 3: 3-Step Lookahead on Hard Core (n={n_vars})")
    print("=" * 70)

    solvers = {
        "1step": make_lookahead_solver(score_1step),
        "2step_best": make_lookahead_solver(score_2step),
        "3step": make_lookahead_solver(score_3step),
    }

    results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0, "time": 0}
               for name in solvers}

    found = 0
    seed = 0
    while found < n_target and seed < 100000:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        if not is_hard_core(clauses, n_vars):
            continue
        found += 1

        for name, solver in solvers.items():
            t0 = time.time()
            _, bt = solver(clauses, n_vars)
            elapsed = time.time() - t0
            results[name]["count"] += 1
            results[name]["total_bt"] += bt
            results[name]["time"] += elapsed
            if bt == 0:
                results[name]["zero_bt"] += 1

        if found % 10 == 0:
            print(f"  progress: {found}/{n_target}")

    print(f"\n  Hard core ({found} instances):")
    print(f"  {'Solver':<20} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>8} {'Time':>8}")
    print(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*8} {'-'*8}")
    for name in sorted(results.keys(), key=lambda n: -results[n]["zero_bt"]):
        r = results[name]
        pct = r["zero_bt"] / r["count"] * 100
        avg = r["total_bt"] / r["count"]
        t = r["time"]
        print(f"  {name:<20} {r['zero_bt']:>5}/{r['count']:<4} {pct:>7.1f}% {avg:>8.2f} {t:>7.2f}s")


def experiment_scaling_lookahead(n_target=100):
    """How does 2-step lookahead scale with problem size?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 4: 2-Step Lookahead Scaling")
    print("=" * 70)

    solver_2step = make_lookahead_solver(score_2step)

    for n_vars in [7, 8, 9, 10, 12]:
        results = {
            "jw": {"zero_bt": 0, "total_bt": 0, "count": 0, "time": 0},
            "2step": {"zero_bt": 0, "total_bt": 0, "count": 0, "time": 0},
        }

        found = 0
        seed = 0
        while found < n_target and seed < n_target * 20:
            clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
            seed += 1
            success, _ = solve_adaptive_jw(clauses, n_vars)
            if not success:
                continue
            found += 1

            t0 = time.time()
            _, bt = solve_adaptive_jw(clauses, n_vars)
            results["jw"]["time"] += time.time() - t0
            results["jw"]["count"] += 1
            results["jw"]["total_bt"] += bt
            if bt == 0: results["jw"]["zero_bt"] += 1

            t0 = time.time()
            _, bt = solver_2step(clauses, n_vars)
            results["2step"]["time"] += time.time() - t0
            results["2step"]["count"] += 1
            results["2step"]["total_bt"] += bt
            if bt == 0: results["2step"]["zero_bt"] += 1

        jw = results["jw"]
        ts = results["2step"]
        jw_pct = jw["zero_bt"]/jw["count"]*100 if jw["count"] else 0
        ts_pct = ts["zero_bt"]/ts["count"]*100 if ts["count"] else 0
        jw_avg = jw["total_bt"]/jw["count"] if jw["count"] else 0
        ts_avg = ts["total_bt"]/ts["count"] if ts["count"] else 0
        print(f"  n={n_vars:>2}: JW {jw['zero_bt']:>3}/{jw['count']} ({jw_pct:>5.1f}%, avg_bt={jw_avg:.2f}, {jw['time']:.1f}s) | "
              f"2step {ts['zero_bt']:>3}/{ts['count']} ({ts_pct:>5.1f}%, avg_bt={ts_avg:.2f}, {ts['time']:.1f}s)")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 9: Multi-Step Lookahead")
    print("▓" * 70)

    experiment_lookahead_comparison(n_vars=7, n_target=200)
    experiment_hard_core_lookahead(n_vars=7, n_target=50)
    experiment_3step_on_hard_core(n_vars=7, n_target=30)
    experiment_scaling_lookahead(n_target=100)

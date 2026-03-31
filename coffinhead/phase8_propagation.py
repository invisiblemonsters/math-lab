"""
THE COFFINHEAD CONJECTURE — Phase 8: Propagation Dynamics
==========================================================
The winning ordering WORKS. Trace WHY it works.

At each decision point in the solve:
1. How many variables does UP force after this decision?
2. How many clauses get eliminated?
3. What value does the winning ordering assign (True or False)?
4. Is the winning ordering choosing the variable that maximizes propagation?

Compare step-by-step: winning ordering vs failing heuristic on same instance.
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


def solve_with_ordering(clauses, ordering, n_vars):
    backtracks = 0
    def dpll(clauses, assignment, order_idx):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = set()
        for c in clauses:
            for l in c:
                if abs(l) not in assignment: unassigned.add(abs(l))
        if not unassigned: return None
        bv = None
        for i in range(order_idx, len(ordering)):
            if ordering[i] in unassigned:
                bv = ordering[i]; order_idx = i + 1; break
        if bv is None: bv = next(iter(unassigned))
        a1 = dict(assignment); a1[bv] = True
        r = dpll([list(c) for c in clauses], a1, order_idx)
        if r is not None: return r
        backtracks += 1
        a2 = dict(assignment); a2[bv] = False
        return dpll([list(c) for c in clauses], a2, order_idx)
    result = dpll(clauses, {}, 0)
    return result is not None, backtracks


# ─── Step-by-step trace ───

def trace_solve(clauses, ordering, n_vars):
    """
    Trace the solve process step by step.
    Returns list of steps, each with:
    - decision variable and value
    - vars forced by UP
    - clauses eliminated
    - remaining clauses
    - whether backtrack occurred
    """
    steps = []
    backtracks = 0

    def dpll(clauses, assignment, order_idx, depth):
        nonlocal backtracks
        pre_assigned = set(assignment.keys())
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        post_assigned = set(assignment.keys())
        forced = post_assigned - pre_assigned

        if contradiction:
            return None, forced

        if not clauses:
            return assignment, forced

        unassigned = set()
        for c in clauses:
            for l in c:
                if abs(l) not in assignment:
                    unassigned.add(abs(l))
        if not unassigned:
            return None, forced

        bv = None
        for i in range(order_idx, len(ordering)):
            if ordering[i] in unassigned:
                bv = ordering[i]; order_idx = i + 1; break
        if bv is None:
            bv = next(iter(unassigned))

        step = {
            "depth": depth,
            "decision_var": bv,
            "decision_value": True,
            "forced_by_up": forced,
            "n_forced": len(forced),
            "remaining_clauses": len(clauses),
            "remaining_vars": len(unassigned),
            "backtracked": False,
        }

        a1 = dict(assignment); a1[bv] = True
        result, child_forced = dpll([list(c) for c in clauses], a1, order_idx, depth + 1)

        if result is not None:
            step["total_forced_after"] = len(forced) + len(child_forced)
            steps.append(step)
            return result, forced | child_forced

        # Backtrack
        backtracks += 1
        step["backtracked"] = True
        step["decision_value"] = False  # switched
        steps.append(step)

        a2 = dict(assignment); a2[bv] = False
        result, child_forced = dpll([list(c) for c in clauses], a2, order_idx, depth + 1)
        return result, forced | (child_forced if result else set())

    initial_assignment, initial_clauses, contradiction = unit_propagate(clauses, {})
    initial_forced = set(initial_assignment.keys())

    if initial_forced:
        steps.append({
            "depth": -1,
            "decision_var": None,
            "decision_value": None,
            "forced_by_up": initial_forced,
            "n_forced": len(initial_forced),
            "remaining_clauses": len(initial_clauses),
            "remaining_vars": n_vars - len(initial_forced),
            "backtracked": False,
        })

    if not contradiction:
        unassigned = set()
        for c in initial_clauses:
            for l in c:
                if abs(l) not in initial_assignment:
                    unassigned.add(abs(l))

        if unassigned:
            bv = None
            for i, v in enumerate(ordering):
                if v in unassigned:
                    bv = v
                    break

            if bv:
                dpll(initial_clauses, dict(initial_assignment), 0, 0)

    return steps, backtracks


# ─── Propagation yield measurement ───

def measure_propagation_yield(clauses, assignment, var, value, n_vars):
    """
    If we set var=value, how much does UP give us?
    Returns (n_forced, n_clauses_eliminated, contradiction)
    """
    new_assignment = dict(assignment)
    new_assignment[var] = value

    pre_count = len(new_assignment)
    post_assignment, remaining, contradiction = unit_propagate(clauses, new_assignment)
    n_forced = len(post_assignment) - pre_count

    # Count eliminated clauses
    remaining_simplified = []
    for clause in clauses:
        satisfied = False
        for lit in clause:
            v = abs(lit)
            if v in post_assignment:
                val = post_assignment[v]
                if (lit > 0 and val) or (lit < 0 and not val):
                    satisfied = True
                    break
        if not satisfied:
            remaining_simplified.append(clause)

    n_eliminated = len(clauses) - len(remaining_simplified)
    return n_forced, n_eliminated, contradiction


# ─── Adaptive solvers for comparison ───

def solve_adaptive_jw(clauses, n_vars):
    backtracks = 0
    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = set()
        for c in clauses:
            for l in c:
                if abs(l) not in assignment: unassigned.add(abs(l))
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
        unassigned = set()
        for c in clauses:
            for l in c:
                if abs(l) not in assignment: unassigned.add(abs(l))
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


# ─── Experiment 1: Side-by-side trace ───

def experiment_trace_comparison(n_vars=7, n_instances=10):
    """Trace winning vs losing ordering side by side."""
    print("=" * 70)
    print(f"  EXPERIMENT 1: Step-by-Step Trace (n={n_vars})")
    print("=" * 70)

    found = 0
    seed = 0
    while found < n_instances and seed < 100000:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        if not is_hard_core(clauses, n_vars):
            continue

        # Find a winning ordering
        winner = None
        for perm in itertools.permutations(range(1, n_vars + 1)):
            o = list(perm)
            _, bt = solve_with_ordering(clauses, o, n_vars)
            if bt == 0:
                winner = o
                break
        if not winner:
            continue

        found += 1
        solutions = find_all_solutions(clauses, n_vars)

        # Build JW ordering for comparison
        counts = Counter()
        for c in clauses:
            for l in c:
                counts[abs(l)] += 1
        jw_ordering = sorted(range(1, n_vars+1),
                            key=lambda v: -sum(2.0**(-len(c)) for c in clauses
                                               for l in c if abs(l)==v))

        print(f"\n  --- Instance {found} (seed={seed-1}, solutions={len(solutions)}) ---")
        sol_str = ", ".join("".join("1" if s[v] else "0" for v in range(1,n_vars+1))
                          for s in solutions[:3])
        print(f"  Solutions: {sol_str}{'...' if len(solutions) > 3 else ''}")

        # Trace both
        for label, ordering in [("WINNER", winner), ("JW", jw_ordering)]:
            steps, bt = trace_solve(clauses, ordering, n_vars)
            print(f"\n    {label} ordering: {ordering} (backtracks={bt})")
            for step in steps:
                if step["decision_var"] is None:
                    print(f"      [initial UP] forced {step['n_forced']} vars: {sorted(step['forced_by_up'])}")
                    continue
                bt_mark = " *** BACKTRACK ***" if step["backtracked"] else ""
                val_str = "T→F" if step["backtracked"] else ("True" if step["decision_value"] else "False")
                print(f"      decide x{step['decision_var']}={val_str}, "
                      f"UP forced {step['n_forced']}, "
                      f"remaining: {step['remaining_clauses']} clauses, "
                      f"{step['remaining_vars']} vars{bt_mark}")


# ─── Experiment 2: Propagation yield at each step ───

def experiment_propagation_yield(n_vars=7, n_instances=30):
    """
    At the FIRST decision point, measure propagation yield for ALL variables.
    Does the winning ordering pick the one with highest yield?
    """
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 2: Propagation Yield at First Decision (n={n_vars})")
    print("=" * 70)

    winner_has_max_yield = 0
    winner_yield_rank = []
    winner_picks_no_contradiction = 0
    loser_picks_contradiction = 0
    total = 0

    yield_vs_bt = []  # (yield_of_choice, backtracks)

    for seed in range(100000):
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        if not is_hard_core(clauses, n_vars):
            continue

        # Find a winning ordering
        winner = None
        for perm in itertools.permutations(range(1, n_vars + 1)):
            o = list(perm)
            _, bt = solve_with_ordering(clauses, o, n_vars)
            if bt == 0:
                winner = o
                break
        if not winner:
            continue

        total += 1

        # Initial UP
        assignment, remaining, _ = unit_propagate(clauses, {})
        unassigned = set()
        for c in remaining:
            for l in c:
                if abs(l) not in assignment:
                    unassigned.add(abs(l))

        if not unassigned:
            continue

        # Measure propagation yield for each variable, both True and False
        yields = {}
        for v in unassigned:
            for value in [True, False]:
                n_forced, n_elim, contradiction = measure_propagation_yield(
                    remaining, assignment, v, value, n_vars)
                yields[(v, value)] = {
                    "forced": n_forced,
                    "eliminated": n_elim,
                    "contradiction": contradiction,
                    "total_yield": n_forced + n_elim,
                }

        # What did the winner pick?
        winner_var = winner[0]
        # The solver tries True first
        winner_choice = (winner_var, True)
        winner_yield = yields.get(winner_choice, {}).get("total_yield", 0)
        winner_contradiction = yields.get(winner_choice, {}).get("contradiction", False)

        # If winner's True contradicts, it would try False — but that means bt>0
        # So in a zero-bt solve, True must NOT contradict
        if not winner_contradiction:
            winner_picks_no_contradiction += 1

        # What's the max yield across all (var, True) choices?
        max_yield = max(yields[(v, True)]["total_yield"] for v in unassigned
                       if not yields[(v, True)]["contradiction"])
        max_yield_any = max(yields[(v, val)]["total_yield"]
                          for v in unassigned for val in [True, False]
                          if not yields[(v, val)]["contradiction"])

        if winner_yield == max_yield:
            winner_has_max_yield += 1

        # Rank of winner's yield
        all_yields = sorted(set(yields[(v, True)]["total_yield"] for v in unassigned
                               if not yields[(v, True)]["contradiction"]), reverse=True)
        if winner_yield in all_yields:
            rank = all_yields.index(winner_yield)
        else:
            rank = len(all_yields)
        winner_yield_rank.append(rank)

        # Check: do losing heuristics pick variables that CONTRADICT on True?
        jw_scores = {}
        for c in remaining:
            w = 2.0 ** (-len(c))
            for l in c:
                v = abs(l)
                if v in unassigned:
                    jw_scores[v] = jw_scores.get(v, 0) + w
        jw_var = max(unassigned, key=lambda v: jw_scores.get(v, 0))
        jw_contradicts = yields.get((jw_var, True), {}).get("contradiction", False)
        if jw_contradicts:
            loser_picks_contradiction += 1

        if total >= n_instances:
            break

    print(f"\n  Analyzed {total} hard-core instances with winning orderings")
    print(f"\n  WINNER'S FIRST DECISION:")
    print(f"    Picks var where True doesn't contradict: {winner_picks_no_contradiction}/{total} "
          f"({winner_picks_no_contradiction/total*100:.1f}%)")
    print(f"    Has MAX propagation yield (True, no contradiction): {winner_has_max_yield}/{total} "
          f"({winner_has_max_yield/total*100:.1f}%)")
    avg_rank = sum(winner_yield_rank) / len(winner_yield_rank) if winner_yield_rank else 0
    print(f"    Average yield rank: {avg_rank:.2f} (0=best)")
    print(f"\n  JW HEURISTIC picks a var that CONTRADICTS on True: {loser_picks_contradiction}/{total} "
          f"({loser_picks_contradiction/total*100:.1f}%)")

    # Distribution of yield rank
    rank_dist = Counter(winner_yield_rank)
    print(f"\n  Winner's yield rank distribution:")
    for r in sorted(rank_dist.keys()):
        ct = rank_dist[r]
        bar = "#" * int(ct / max(rank_dist.values()) * 40)
        print(f"    rank {r}: {ct:>4} ({ct/total*100:>5.1f}%) {bar}")


# ─── Experiment 3: Contradiction avoidance ───

def experiment_contradiction_avoidance(n_vars=7, n_instances=30):
    """
    Key hypothesis: the winning ordering picks variables where
    BOTH True and False don't immediately contradict.
    It maximizes FREEDOM — keeping options open.
    """
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 3: Contradiction Avoidance (n={n_vars})")
    print("=" * 70)

    both_safe_winner = 0
    one_contradicts_winner = 0
    both_safe_available = 0
    winner_picks_both_safe = 0
    total = 0

    for seed in range(100000):
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        if not is_hard_core(clauses, n_vars):
            continue

        winner = None
        for perm in itertools.permutations(range(1, n_vars + 1)):
            o = list(perm)
            _, bt = solve_with_ordering(clauses, o, n_vars)
            if bt == 0:
                winner = o
                break
        if not winner:
            continue

        total += 1
        assignment, remaining, _ = unit_propagate(clauses, {})
        unassigned = set()
        for c in remaining:
            for l in c:
                if abs(l) not in assignment:
                    unassigned.add(abs(l))
        if not unassigned:
            continue

        # For each variable: does True contradict? Does False contradict?
        var_safety = {}
        for v in unassigned:
            _, _, ct = measure_propagation_yield(remaining, assignment, v, True, n_vars)
            _, _, cf = measure_propagation_yield(remaining, assignment, v, False, n_vars)
            var_safety[v] = {
                "true_safe": not ct,
                "false_safe": not cf,
                "both_safe": not ct and not cf,
                "one_contradicts": ct != cf,  # exactly one contradicts
                "both_contradict": ct and cf,
            }

        winner_var = winner[0]
        ws = var_safety[winner_var]

        if ws["both_safe"]:
            both_safe_winner += 1
        if ws["one_contradicts"]:
            one_contradicts_winner += 1

        # Is there ANY both-safe variable available?
        any_both_safe = any(var_safety[v]["both_safe"] for v in unassigned)
        if any_both_safe:
            both_safe_available += 1
            if ws["both_safe"]:
                winner_picks_both_safe += 1

        if total >= n_instances:
            break

    print(f"\n  Analyzed {total} hard-core instances")
    print(f"\n  Winner's first variable safety:")
    print(f"    Both True and False are safe: {both_safe_winner}/{total} "
          f"({both_safe_winner/total*100:.1f}%)")
    print(f"    Exactly one value contradicts: {one_contradicts_winner}/{total} "
          f"({one_contradicts_winner/total*100:.1f}%)")
    print(f"\n  When both-safe variables exist ({both_safe_available}/{total}):")
    if both_safe_available > 0:
        print(f"    Winner picks a both-safe var: {winner_picks_both_safe}/{both_safe_available} "
              f"({winner_picks_both_safe/both_safe_available*100:.1f}%)")


# ─── Experiment 4: Adaptive max-yield solver ───

def solve_adaptive_max_yield(clauses, n_vars):
    """
    At each step, try ALL unassigned variables with True,
    pick the one with highest propagation yield (forced + eliminated)
    that doesn't contradict.
    """
    backtracks = 0

    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment

        unassigned = set()
        for c in clauses:
            for l in c:
                if abs(l) not in assignment:
                    unassigned.add(abs(l))
        if not unassigned: return None

        # Measure yield for each variable
        best_var = None
        best_yield = -1
        best_value = True

        for v in unassigned:
            for value in [True, False]:
                n_forced, n_elim, contradiction = measure_propagation_yield(
                    clauses, assignment, v, value, n_vars)
                if not contradiction:
                    total_yield = n_forced + n_elim
                    if total_yield > best_yield:
                        best_yield = total_yield
                        best_var = v
                        best_value = value

        if best_var is None:
            # All choices contradict — pick any
            best_var = next(iter(unassigned))
            best_value = True

        a1 = dict(assignment); a1[best_var] = best_value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment); a2[best_var] = not best_value
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def solve_adaptive_both_safe_first(clauses, n_vars):
    """
    Pick variable where BOTH True and False are non-contradicting (most freedom).
    Among those, pick highest propagation yield.
    If no both-safe variable, fall back to max yield.
    """
    backtracks = 0

    def dpll(clauses, assignment):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment

        unassigned = set()
        for c in clauses:
            for l in c:
                if abs(l) not in assignment:
                    unassigned.add(abs(l))
        if not unassigned: return None

        both_safe = []
        one_safe = []
        for v in unassigned:
            ft, et, ct = measure_propagation_yield(clauses, assignment, v, True, n_vars)
            ff, ef, cf = measure_propagation_yield(clauses, assignment, v, False, n_vars)
            if not ct and not cf:
                both_safe.append((v, max(ft+et, ff+ef), ft+et >= ff+ef))
            elif not ct:
                one_safe.append((v, ft+et, True))
            elif not cf:
                one_safe.append((v, ff+ef, False))

        if both_safe:
            both_safe.sort(key=lambda x: -x[1])
            best_var = both_safe[0][0]
            best_value = both_safe[0][2]
        elif one_safe:
            one_safe.sort(key=lambda x: -x[1])
            best_var = one_safe[0][0]
            best_value = one_safe[0][2]
        else:
            best_var = next(iter(unassigned))
            best_value = True

        a1 = dict(assignment); a1[best_var] = best_value
        result = dpll([list(c) for c in clauses], a1)
        if result is not None:
            return result
        backtracks += 1
        a2 = dict(assignment); a2[best_var] = not best_value
        return dpll([list(c) for c in clauses], a2)

    result = dpll(clauses, {})
    return result is not None, backtracks


def experiment_new_solvers(n_vars=7, n_target=200):
    """Test propagation-yield-based solvers against existing ones."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 4: Propagation-Yield Solvers (n={n_vars})")
    print("=" * 70)

    solvers = {
        "adaptive_jw": solve_adaptive_jw,
        "adaptive_polarity": solve_adaptive_polarity,
        "max_yield": solve_adaptive_max_yield,
        "both_safe_first": solve_adaptive_both_safe_first,
    }

    results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0} for name in solvers}

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
            _, bt = solver(clauses, n_vars)
            results[name]["count"] += 1
            results[name]["total_bt"] += bt
            if bt == 0:
                results[name]["zero_bt"] += 1

    print(f"\n  All satisfiable instances (n={n_vars}, ratio=4.0, {found} instances):")
    print(f"  {'Solver':<22} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>8}")
    print(f"  {'-'*22} {'-'*10} {'-'*8} {'-'*8}")
    for name in sorted(results.keys(), key=lambda n: -results[n]["zero_bt"]):
        r = results[name]
        pct = r["zero_bt"] / r["count"] * 100
        avg = r["total_bt"] / r["count"]
        print(f"  {name:<22} {r['zero_bt']:>5}/{r['count']:<4} {pct:>7.1f}% {avg:>8.2f}")

    # Now test ONLY on hard core
    print(f"\n  Hard core instances only:")
    hc_results = {name: {"zero_bt": 0, "total_bt": 0, "count": 0} for name in solvers}

    found = 0
    seed = 0
    while found < 50 and seed < 100000:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        if not is_hard_core(clauses, n_vars):
            continue
        found += 1

        for name, solver in solvers.items():
            _, bt = solver(clauses, n_vars)
            hc_results[name]["count"] += 1
            hc_results[name]["total_bt"] += bt
            if bt == 0:
                hc_results[name]["zero_bt"] += 1

    print(f"  {'Solver':<22} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>8}")
    print(f"  {'-'*22} {'-'*10} {'-'*8} {'-'*8}")
    for name in sorted(hc_results.keys(), key=lambda n: -hc_results[n]["zero_bt"]):
        r = hc_results[name]
        pct = r["zero_bt"] / r["count"] * 100 if r["count"] > 0 else 0
        avg = r["total_bt"] / r["count"] if r["count"] > 0 else 0
        print(f"  {name:<22} {r['zero_bt']:>5}/{r['count']:<4} {pct:>7.1f}% {avg:>8.2f}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 8: Propagation Dynamics")
    print("▓" * 70)

    experiment_trace_comparison(n_vars=7, n_instances=5)
    experiment_propagation_yield(n_vars=7, n_instances=50)
    experiment_contradiction_avoidance(n_vars=7, n_instances=50)
    experiment_new_solvers(n_vars=7, n_target=200)

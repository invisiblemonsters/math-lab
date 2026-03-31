"""
THE COFFINHEAD CONJECTURE — Phase 7: The Winning Orderings
============================================================
The hard core has zero-BT orderings that heuristics miss.
WHAT DO THEY LOOK LIKE? Is there a computable pattern?

If we can find a polynomial-time function f(formula) → ordering that
always produces zero backtracks, that's a P=NP proof.

1. Collect hard core instances where zero-BT orderings exist
2. Extract ALL zero-BT orderings for each instance
3. Analyze: what properties do winning orderings share?
4. Compare winning orderings to heuristic orderings — where do they diverge?
5. Look for a computable rule that predicts the winning ordering
"""

import random
import itertools
from collections import Counter, defaultdict
import json


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


# ─── Adaptive solvers ───

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


def is_hard_core(clauses, n_vars):
    for solver in [solve_adaptive_polarity, solve_adaptive_jw]:
        success, bt = solver(clauses, n_vars)
        if not success: return None
        if bt == 0: return False
    return True


# ─── Variable metrics relative to formula ───

def var_metrics(clauses, n_vars):
    """Compute per-variable metrics."""
    counts = Counter()
    pos = Counter()
    neg = Counter()
    clause_sizes = defaultdict(list)  # var -> list of clause sizes it appears in

    for clause in clauses:
        for lit in clause:
            v = abs(lit)
            counts[v] += 1
            if lit > 0: pos[v] += 1
            else: neg[v] += 1
            clause_sizes[v].append(len(clause))

    # Neighbor count (how many other vars share a clause)
    neighbors = defaultdict(set)
    for clause in clauses:
        vs = [abs(l) for l in clause]
        for i in range(len(vs)):
            for j in range(i+1, len(vs)):
                neighbors[vs[i]].add(vs[j])
                neighbors[vs[j]].add(vs[i])

    metrics = {}
    for v in range(1, n_vars + 1):
        total = pos.get(v, 0) + neg.get(v, 0)
        bias = abs(pos.get(v, 0) - neg.get(v, 0)) / total if total > 0 else 0
        dominant = pos.get(v, 0) >= neg.get(v, 0)  # True if more positive
        avg_clause_size = sum(clause_sizes.get(v, [3])) / len(clause_sizes.get(v, [3]))

        # JW score
        jw_pos = sum(2.0**(-s) for s, l in zip(clause_sizes.get(v,[]), 
                      [l for c in clauses for l in c if abs(l)==v]) if l > 0)
        jw_neg = sum(2.0**(-s) for s, l in zip(clause_sizes.get(v,[]),
                      [l for c in clauses for l in c if abs(l)==v]) if l < 0)
        # Simpler JW
        jw_score = 0
        for clause in clauses:
            for lit in clause:
                if abs(lit) == v:
                    jw_score += 2.0 ** (-len(clause))

        metrics[v] = {
            "frequency": counts.get(v, 0),
            "pos": pos.get(v, 0),
            "neg": neg.get(v, 0),
            "polarity_bias": bias,
            "dominant_polarity": dominant,
            "n_neighbors": len(neighbors.get(v, set())),
            "avg_clause_size": avg_clause_size,
            "jw_score": jw_score,
        }
    return metrics


# ─── Collect hard core instances with winning orderings ───

def collect_hard_core_with_winners(n_vars=7, n_target=50, ratio=4.0):
    """Find hard core instances that have zero-BT orderings."""
    instances = []
    seed = 0
    while len(instances) < n_target and seed < 100000:
        clauses = generate_random_3sat(n_vars, ratio, seed=seed)
        seed += 1

        if not is_hard_core(clauses, n_vars):
            continue

        # Find ALL zero-BT orderings
        zero_bt_orderings = []
        all_bt = []
        for perm in itertools.permutations(range(1, n_vars + 1)):
            o = list(perm)
            _, bt = solve_with_ordering(clauses, o, n_vars)
            all_bt.append(bt)
            if bt == 0:
                zero_bt_orderings.append(o)

        if not zero_bt_orderings:
            continue  # True hard core — skip, we want the ones WITH winners

        solutions = find_all_solutions(clauses, n_vars)
        vm = var_metrics(clauses, n_vars)

        instances.append({
            "seed": seed - 1,
            "clauses": clauses,
            "solutions": solutions,
            "zero_bt_orderings": zero_bt_orderings,
            "n_zero_bt": len(zero_bt_orderings),
            "total_orderings": len(all_bt),
            "min_bt": min(all_bt),
            "var_metrics": vm,
        })

        if len(instances) % 10 == 0:
            print(f"  collected {len(instances)}/{n_target}...")

    return instances


# ─── Experiment 1: What position does each variable take in winning orderings? ───

def experiment_position_analysis(instances, n_vars):
    """For each variable, what position does it take in winning vs losing orderings?"""
    print("=" * 70)
    print(f"  EXPERIMENT 1: Variable Position in Winning Orderings (n={n_vars})")
    print("=" * 70)

    # For each instance, for each variable, what's its rank in the winning orderings?
    # Map variable PROPERTIES to their winning POSITION

    # Aggregate: variable sorted by property X — what position do they get in winners?
    property_position_corr = defaultdict(list)  # property_name -> list of (rank_by_property, winning_position)

    for inst in instances:
        vm = inst["var_metrics"]
        winners = inst["zero_bt_orderings"]

        # Average position of each var across winning orderings
        avg_pos = {}
        for v in range(1, n_vars + 1):
            positions = [o.index(v) for o in winners]
            avg_pos[v] = sum(positions) / len(positions)

        # Sort vars by each property
        properties = {
            "frequency": lambda v: vm[v]["frequency"],
            "polarity_bias": lambda v: vm[v]["polarity_bias"],
            "n_neighbors": lambda v: vm[v]["n_neighbors"],
            "jw_score": lambda v: vm[v]["jw_score"],
            "neg_count": lambda v: vm[v]["neg"],
            "pos_count": lambda v: vm[v]["pos"],
        }

        for prop_name, prop_fn in properties.items():
            sorted_by_prop = sorted(range(1, n_vars + 1), key=prop_fn)
            for rank, v in enumerate(sorted_by_prop):
                property_position_corr[prop_name].append((rank, avg_pos[v]))

    # Compute correlation for each property
    print(f"\n  PROPERTY → WINNING POSITION CORRELATION:")
    print(f"  (negative = property predicts EARLY position in winner)")
    print(f"  {'Property':<20} {'Correlation':>12} {'Interpretation':>30}")
    print(f"  {'-'*20} {'-'*12} {'-'*30}")

    for prop_name in sorted(property_position_corr.keys()):
        pairs = property_position_corr[prop_name]
        n = len(pairs)
        x = [p[0] for p in pairs]
        y = [p[1] for p in pairs]
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        cov = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y)) / n
        x_std = (sum((xi - x_mean)**2 for xi in x) / n) ** 0.5
        y_std = (sum((yi - y_mean)**2 for yi in y) / n) ** 0.5
        corr = cov / (x_std * y_std) if x_std > 0 and y_std > 0 else 0

        if corr > 0.3:
            interp = "low prop → early position"
        elif corr < -0.3:
            interp = "high prop → early position"
        else:
            interp = "weak/no correlation"

        marker = " ***" if abs(corr) > 0.5 else " **" if abs(corr) > 0.3 else ""
        print(f"  {prop_name:<20} {corr:>+12.3f} {interp:>30}{marker}")


# ─── Experiment 2: First variable analysis ───

def experiment_first_variable(instances, n_vars):
    """What property does the FIRST variable in winning orderings have?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 2: First Variable in Winning Orderings")
    print("=" * 70)

    first_var_props = defaultdict(list)

    for inst in instances:
        vm = inst["var_metrics"]
        winners = inst["zero_bt_orderings"]

        # Count which variable appears first most often
        first_counts = Counter(o[0] for o in winners)
        most_common_first = first_counts.most_common(1)[0][0]
        v = most_common_first

        # What are its properties?
        all_vars = list(range(1, n_vars + 1))

        # Rank by frequency (0 = least frequent)
        by_freq = sorted(all_vars, key=lambda x: vm[x]["frequency"])
        freq_rank = by_freq.index(v)

        # Rank by polarity bias (0 = least biased)
        by_bias = sorted(all_vars, key=lambda x: vm[x]["polarity_bias"])
        bias_rank = by_bias.index(v)

        # Rank by JW score (0 = lowest)
        by_jw = sorted(all_vars, key=lambda x: vm[x]["jw_score"])
        jw_rank = by_jw.index(v)

        # Rank by neighbor count (0 = fewest)
        by_neigh = sorted(all_vars, key=lambda x: vm[x]["n_neighbors"])
        neigh_rank = by_neigh.index(v)

        first_var_props["freq_rank"].append(freq_rank)
        first_var_props["bias_rank"].append(bias_rank)
        first_var_props["jw_rank"].append(jw_rank)
        first_var_props["neigh_rank"].append(neigh_rank)
        first_var_props["frequency"].append(vm[v]["frequency"])
        first_var_props["polarity_bias"].append(vm[v]["polarity_bias"])
        first_var_props["jw_score"].append(vm[v]["jw_score"])

    print(f"\n  First variable in winning orderings (averaged across {len(instances)} instances):")
    print(f"  Ranks are 0 to {n_vars-1} (0=lowest value of that property)")
    print()
    for prop in sorted(first_var_props.keys()):
        vals = first_var_props[prop]
        avg = sum(vals) / len(vals)
        print(f"    {prop:<20}: avg={avg:.2f}")

    # Distribution of frequency rank
    print(f"\n  Frequency rank distribution of first winning variable:")
    dist = Counter(first_var_props["freq_rank"])
    for r in range(n_vars):
        ct = dist.get(r, 0)
        bar = "#" * int(ct / max(dist.values()) * 40) if dist else ""
        label = "least" if r == 0 else "most" if r == n_vars - 1 else ""
        print(f"    rank {r} ({label:>5}): {ct:>4} {bar}")


# ─── Experiment 3: Divergence point ───

def experiment_divergence(instances, n_vars):
    """At which position do heuristic orderings diverge from winning orderings?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 3: Where Heuristics Diverge from Winners")
    print("=" * 70)

    heuristic_orderings = {}

    divergence_positions = defaultdict(list)

    for inst in instances:
        clauses = inst["clauses"]
        vm = inst["var_metrics"]
        winners = inst["zero_bt_orderings"]
        # Pick one representative winner (the one that appears most? just first)
        winner = winners[0]

        # Build heuristic orderings from var_metrics
        all_vars = list(range(1, n_vars + 1))
        h_orderings = {
            "least_freq": sorted(all_vars, key=lambda v: vm[v]["frequency"]),
            "most_freq": sorted(all_vars, key=lambda v: -vm[v]["frequency"]),
            "most_biased": sorted(all_vars, key=lambda v: -vm[v]["polarity_bias"]),
            "least_biased": sorted(all_vars, key=lambda v: vm[v]["polarity_bias"]),
            "highest_jw": sorted(all_vars, key=lambda v: -vm[v]["jw_score"]),
            "most_neighbors": sorted(all_vars, key=lambda v: -vm[v]["n_neighbors"]),
            "least_neighbors": sorted(all_vars, key=lambda v: vm[v]["n_neighbors"]),
        }

        for h_name, h_order in h_orderings.items():
            # Find first position where they disagree
            # But "disagree" needs nuance — the winner might have many equivalent orderings
            # Check: is h_order[i] EVER in position i in ANY winning ordering?
            for pos in range(n_vars):
                h_var = h_order[pos]
                # Is this var at this position in any winner?
                any_match = any(w[pos] == h_var for w in winners)
                if not any_match:
                    divergence_positions[h_name].append(pos)
                    break
            else:
                divergence_positions[h_name].append(n_vars)  # never diverges

    print(f"\n  Average divergence position (0=first variable is wrong):")
    print(f"  {'Heuristic':<20} {'Avg diverge':>12} {'At pos 0':>10} {'At pos 1':>10} {'Never':>8}")
    print(f"  {'-'*20} {'-'*12} {'-'*10} {'-'*10} {'-'*8}")

    for h_name in sorted(divergence_positions.keys()):
        positions = divergence_positions[h_name]
        avg = sum(positions) / len(positions)
        at_0 = sum(1 for p in positions if p == 0)
        at_1 = sum(1 for p in positions if p == 1)
        never = sum(1 for p in positions if p == n_vars)
        n = len(positions)
        print(f"  {h_name:<20} {avg:>12.2f} {at_0:>7}/{n:<2} {at_1:>7}/{n:<2} {never:>5}/{n:<2}")


# ─── Experiment 4: Can we LEARN the winning ordering? ───

def experiment_learn_ordering(instances, n_vars):
    """
    Try to find a COMPUTABLE RULE that produces a winning ordering.
    Test composite scoring functions that combine multiple metrics.
    """
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 4: Learning a Winning Ordering Rule")
    print("=" * 70)

    # Define candidate scoring functions
    # The ordering is: sort variables by score, lowest first
    def score_freq_only(vm, v):
        return vm[v]["frequency"]

    def score_bias_only(vm, v):
        return -vm[v]["polarity_bias"]  # most biased first

    def score_jw(vm, v):
        return -vm[v]["jw_score"]  # highest JW first

    def score_freq_minus_bias(vm, v):
        return vm[v]["frequency"] - vm[v]["polarity_bias"] * 10

    def score_bias_div_freq(vm, v):
        return -vm[v]["polarity_bias"] / (vm[v]["frequency"] + 1)

    def score_neighbors_minus_bias(vm, v):
        return vm[v]["n_neighbors"] - vm[v]["polarity_bias"] * 5

    def score_jw_times_bias(vm, v):
        return -(vm[v]["jw_score"] * (1 + vm[v]["polarity_bias"]))

    def score_neg_dominance(vm, v):
        """Variables with more negative occurrences first."""
        return -vm[v]["neg"]

    def score_imbalance_times_freq(vm, v):
        return -(abs(vm[v]["pos"] - vm[v]["neg"]) * vm[v]["frequency"])

    def score_clause_size_bias(vm, v):
        """Low avg clause size + high bias = most constrained + most obvious"""
        return vm[v]["avg_clause_size"] - vm[v]["polarity_bias"] * 3

    def score_inverse_freedom(vm, v):
        """Variables with least 'freedom' first — high freq, high bias, many neighbors"""
        return -(vm[v]["frequency"] * vm[v]["polarity_bias"] * vm[v]["n_neighbors"])

    def score_coffinhead(vm, v):
        """
        The Coffinhead heuristic: combine insights from all phases.
        High polarity bias → strong signal → go first
        High JW score → appears in short clauses → more constrained → go first
        Low frequency → less entangled → cleaner propagation → go first
        """
        bias = vm[v]["polarity_bias"]
        jw = vm[v]["jw_score"]
        freq = vm[v]["frequency"]
        return -(bias * 3 + jw * 2 - freq * 0.1)

    scoring_fns = {
        "freq_only": score_freq_only,
        "bias_only": score_bias_only,
        "jw_only": score_jw,
        "freq-bias*10": score_freq_minus_bias,
        "bias/freq": score_bias_div_freq,
        "neigh-bias*5": score_neighbors_minus_bias,
        "jw*bias": score_jw_times_bias,
        "neg_dominance": score_neg_dominance,
        "imbal*freq": score_imbalance_times_freq,
        "clause_sz-bias": score_clause_size_bias,
        "inv_freedom": score_inverse_freedom,
        "coffinhead": score_coffinhead,
    }

    results = {}
    for name, score_fn in scoring_fns.items():
        zero_bt = 0
        total_bt = 0
        for inst in instances:
            vm = inst["var_metrics"]
            clauses = inst["clauses"]
            ordering = sorted(range(1, n_vars + 1), key=lambda v: score_fn(vm, v))
            _, bt = solve_with_ordering(clauses, ordering, n_vars)
            if bt == 0:
                zero_bt += 1
            total_bt += bt

        results[name] = {
            "zero_bt": zero_bt,
            "total": len(instances),
            "total_bt": total_bt,
        }

    print(f"\n  Scoring functions tested on {len(instances)} hard-core instances:")
    print(f"  (These are instances where polarity & JW FAIL)")
    print(f"  {'Scoring':<20} {'Zero-BT':>10} {'Rate':>8} {'Avg BT':>8}")
    print(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*8}")
    for name in sorted(results.keys(), key=lambda n: -results[n]["zero_bt"]):
        r = results[name]
        pct = r["zero_bt"] / r["total"] * 100
        avg = r["total_bt"] / r["total"]
        marker = " <<<" if r["zero_bt"] == max(rr["zero_bt"] for rr in results.values()) else ""
        print(f"  {name:<20} {r['zero_bt']:>5}/{r['total']:<4} {pct:>7.1f}% {avg:>8.2f}{marker}")


# ─── Experiment 5: Winning ordering SEQUENCES ───

def experiment_winning_sequences(instances, n_vars):
    """Look at the actual sequences. What variable comes first, second, third?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 5: Winning Ordering Patterns")
    print("=" * 70)

    # For each instance, characterize the winning first variable
    # by which PROPERTY makes it stand out
    first_var_standout = Counter()
    second_var_standout = Counter()

    for inst in instances:
        vm = inst["var_metrics"]
        winners = inst["zero_bt_orderings"]
        all_vars = list(range(1, n_vars + 1))

        # Most common first variable
        first_counts = Counter(o[0] for o in winners)
        first_var = first_counts.most_common(1)[0][0]

        # What property does it rank highest on?
        rankings = {
            "most_biased": sorted(all_vars, key=lambda v: -vm[v]["polarity_bias"]),
            "least_freq": sorted(all_vars, key=lambda v: vm[v]["frequency"]),
            "highest_jw": sorted(all_vars, key=lambda v: -vm[v]["jw_score"]),
            "most_neg": sorted(all_vars, key=lambda v: -vm[v]["neg"]),
            "least_neighbors": sorted(all_vars, key=lambda v: vm[v]["n_neighbors"]),
        }

        best_rank = n_vars
        best_prop = "none"
        for prop, ranked in rankings.items():
            rank = ranked.index(first_var)
            if rank < best_rank:
                best_rank = rank
                best_prop = prop

        first_var_standout[f"{best_prop}(rank={best_rank})"] += 1

        # Second most common variable
        if len(winners[0]) > 1:
            second_counts = Counter(o[1] for o in winners)
            second_var = second_counts.most_common(1)[0][0]
            best_rank2 = n_vars
            best_prop2 = "none"
            for prop, ranked in rankings.items():
                rank = ranked.index(second_var)
                if rank < best_rank2:
                    best_rank2 = rank
                    best_prop2 = prop
            second_var_standout[f"{best_prop2}(rank={best_rank2})"] += 1

    print(f"\n  First variable standout property:")
    for k, v in first_var_standout.most_common():
        bar = "#" * int(v / max(first_var_standout.values()) * 30)
        print(f"    {k:<30}: {v:>4} {bar}")

    print(f"\n  Second variable standout property:")
    for k, v in second_var_standout.most_common():
        bar = "#" * int(v / max(second_var_standout.values()) * 30)
        print(f"    {k:<30}: {v:>4} {bar}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 7: The Winning Orderings")
    print("▓" * 70)

    n_vars = 7
    print(f"\n  Collecting hard core instances with winning orderings (n={n_vars})...")
    instances = collect_hard_core_with_winners(n_vars=n_vars, n_target=50, ratio=4.0)
    print(f"  Collected {len(instances)} instances\n")

    experiment_position_analysis(instances, n_vars)
    experiment_first_variable(instances, n_vars)
    experiment_divergence(instances, n_vars)
    experiment_winning_sequences(instances, n_vars)
    experiment_learn_ordering(instances, n_vars)

"""
THE COFFINHEAD CONJECTURE — Phase 4: The 1% Failure
====================================================
Least-frequent-first (LFF) achieves zero backtracks ~99% of the time.
What's special about the 1% where it fails?

1. Collect large sample, separate LFF successes from failures
2. Compare every structural metric between the two groups
3. Deep-dive the failure instances — what ordering WOULD have worked?
4. Is there a computable predicate that identifies failures in advance?
5. Can we build a hybrid heuristic that covers the gap?
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
    decisions = 0
    # Track which variable caused each backtrack
    backtrack_vars = []

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
        backtrack_vars.append(branch_var)
        a2 = dict(assignment)
        a2[branch_var] = False
        return dpll([list(c) for c in clauses], a2, order_idx)

    result = dpll(clauses, {}, 0)
    return result is not None, backtracks, decisions, backtrack_vars


# ─── Ordering Functions ───

def ordering_least_frequent(clauses, n_vars):
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    return sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0))


def ordering_most_frequent(clauses, n_vars):
    counts = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
    return sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0), reverse=True)


def ordering_polarity_bias(clauses, n_vars):
    pos = Counter()
    neg = Counter()
    for clause in clauses:
        for lit in clause:
            if lit > 0: pos[abs(lit)] += 1
            else: neg[abs(lit)] += 1
    return sorted(range(1, n_vars + 1),
                  key=lambda v: abs(pos.get(v, 0) - neg.get(v, 0)), reverse=True)


def ordering_clause_weight(clauses, n_vars):
    scores = Counter()
    for clause in clauses:
        w = 1.0 / len(clause)
        for lit in clause:
            scores[abs(lit)] += w
    return sorted(range(1, n_vars + 1), key=lambda v: scores.get(v, 0))


def ordering_neg_bias_first(clauses, n_vars):
    """Variables that appear more often NEGATIVE first, set to False."""
    neg = Counter()
    for clause in clauses:
        for lit in clause:
            if lit < 0:
                neg[abs(lit)] += 1
    return sorted(range(1, n_vars + 1), key=lambda v: neg.get(v, 0), reverse=True)


# ─── Structural Metrics ───

def compute_metrics(clauses, n_vars, solutions):
    counts = Counter()
    pos = Counter()
    neg = Counter()
    for clause in clauses:
        for lit in clause:
            counts[abs(lit)] += 1
            if lit > 0: pos[abs(lit)] += 1
            else: neg[abs(lit)] += 1

    # Variable interaction graph
    edges = set()
    for clause in clauses:
        vs = [abs(l) for l in clause]
        for i in range(len(vs)):
            for j in range(i+1, len(vs)):
                edges.add((min(vs[i], vs[j]), max(vs[i], vs[j])))

    max_edges = n_vars * (n_vars - 1) / 2
    density = len(edges) / max_edges if max_edges > 0 else 0

    # Degree stats
    degs = [counts.get(v, 0) for v in range(1, n_vars + 1)]
    avg_deg = sum(degs) / n_vars
    deg_var = sum((d - avg_deg)**2 for d in degs) / n_vars
    deg_range = max(degs) - min(degs)

    # Polarity stats
    biases = []
    for v in range(1, n_vars + 1):
        total = pos.get(v, 0) + neg.get(v, 0)
        if total > 0:
            biases.append(abs(pos.get(v, 0) - neg.get(v, 0)) / total)
        else:
            biases.append(0)

    # Backbone
    bb_count = 0
    for v in range(1, n_vars + 1):
        vals = set(sol[v] for sol in solutions)
        if len(vals) == 1:
            bb_count += 1

    # Clause overlap
    total_overlap = 0
    pairs = 0
    for i in range(len(clauses)):
        vi = set(abs(l) for l in clauses[i])
        for j in range(i+1, len(clauses)):
            vj = set(abs(l) for l in clauses[j])
            total_overlap += len(vi & vj)
            pairs += 1
    avg_overlap = total_overlap / pairs if pairs > 0 else 0

    # Conflict density: how many clause pairs have contradictory literals?
    conflicts = 0
    for i in range(len(clauses)):
        lits_i = set(clauses[i])
        for j in range(i+1, len(clauses)):
            for lit in clauses[j]:
                if -lit in lits_i:
                    conflicts += 1
                    break
    conflict_rate = conflicts / pairs if pairs > 0 else 0

    # LFF-specific: how much frequency gap between first and second variable?
    sorted_degs = sorted(degs)
    freq_gap = sorted_degs[1] - sorted_degs[0] if len(sorted_degs) >= 2 else 0
    freq_ratio = sorted_degs[0] / sorted_degs[-1] if sorted_degs[-1] > 0 else 1

    return {
        "n_solutions": len(solutions),
        "backbone_frac": bb_count / n_vars,
        "graph_density": density,
        "avg_degree": avg_deg,
        "degree_variance": deg_var,
        "degree_range": deg_range,
        "avg_polarity_bias": sum(biases) / len(biases),
        "min_polarity_bias": min(biases),
        "max_polarity_bias": max(biases),
        "clause_overlap": avg_overlap,
        "conflict_rate": conflict_rate,
        "freq_gap": freq_gap,
        "freq_ratio": freq_ratio,
        "min_freq": sorted_degs[0],
        "max_freq": sorted_degs[-1],
    }


# ─── Experiment 1: Large Scale LFF Success vs Failure ───

def experiment_lff_failures(n_vars=6, n_target=500):
    """Collect large sample, classify by LFF outcome."""
    print("=" * 70)
    print(f"  EXPERIMENT 1: LFF Success vs Failure Analysis (n={n_vars})")
    print(f"  Target: {n_target} satisfiable instances per ratio")
    print("=" * 70)

    successes = []
    failures = []

    for ratio in [2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
        found = 0
        seed = 0
        ratio_succ = 0
        ratio_fail = 0
        while found < n_target and seed < n_target * 20:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue
            found += 1

            ordering = ordering_least_frequent(clauses, n_vars)
            success, bt, decisions, bt_vars = solve_with_ordering(clauses, ordering, n_vars)

            metrics = compute_metrics(clauses, n_vars, solutions)
            metrics["ratio"] = ratio
            metrics["seed"] = seed - 1
            metrics["lff_backtracks"] = bt
            metrics["lff_decisions"] = decisions
            metrics["lff_bt_vars"] = bt_vars

            if bt == 0:
                successes.append(metrics)
                ratio_succ += 1
            else:
                failures.append(metrics)
                ratio_fail += 1

        print(f"  ratio={ratio}: {ratio_succ} success, {ratio_fail} failure "
              f"({ratio_fail/(ratio_succ+ratio_fail)*100:.1f}% fail)")

    print(f"\n  TOTAL: {len(successes)} successes, {len(failures)} failures "
          f"({len(failures)/(len(successes)+len(failures))*100:.1f}% fail)")

    # Compare metrics
    features = [
        "n_solutions", "backbone_frac", "graph_density",
        "avg_degree", "degree_variance", "degree_range",
        "avg_polarity_bias", "min_polarity_bias", "max_polarity_bias",
        "clause_overlap", "conflict_rate",
        "freq_gap", "freq_ratio", "min_freq", "max_freq",
    ]

    print(f"\n  {'Feature':<22} {'Fail mean':>10} {'Succ mean':>10} {'Delta':>10} {'Effect':>8}")
    print(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

    strong = []
    for feat in features:
        f_vals = [i[feat] for i in failures]
        s_vals = [i[feat] for i in successes]
        f_mean = sum(f_vals) / len(f_vals) if f_vals else 0
        s_mean = sum(s_vals) / len(s_vals) if s_vals else 0
        delta = f_mean - s_mean
        all_vals = f_vals + s_vals
        std = (sum((v - sum(all_vals)/len(all_vals))**2 for v in all_vals) / len(all_vals)) ** 0.5
        effect = abs(delta) / std if std > 0 else 0

        marker = ""
        if effect > 0.3: marker = " *"
        if effect > 0.5: marker = " **"
        if effect > 1.0: marker = " ***"

        if effect > 0.3:
            direction = "FAIL higher" if delta > 0 else "FAIL lower"
            strong.append((feat, effect, direction, f_mean, s_mean))

        print(f"  {feat:<22} {f_mean:>10.3f} {s_mean:>10.3f} {delta:>+10.3f} {effect:>7.2f}{marker}")

    if strong:
        print(f"\n  TOP SEPARATORS:")
        for feat, eff, direction, fm, sm in sorted(strong, key=lambda x: -x[1]):
            print(f"    {feat}: effect={eff:.2f}, {direction} (fail={fm:.3f}, succ={sm:.3f})")

    return successes, failures


# ─── Experiment 2: What ordering WOULD have worked? ───

def experiment_optimal_vs_lff(n_vars=6, n_failures=30):
    """For each LFF failure, find the best ordering and compare."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 2: Optimal vs LFF on Failure Instances (n={n_vars})")
    print("=" * 70)

    failures = []
    seed = 0
    while len(failures) < n_failures and seed < 50000:
        clauses = generate_random_3sat(n_vars, 4.0, seed=seed)
        seed += 1
        solutions = find_all_solutions(clauses, n_vars)
        if not solutions:
            continue
        ordering = ordering_least_frequent(clauses, n_vars)
        success, bt, decisions, bt_vars = solve_with_ordering(clauses, ordering, n_vars)
        if bt > 0:
            failures.append({
                "seed": seed - 1, "clauses": clauses, "solutions": solutions,
                "lff_bt": bt, "lff_ordering": ordering, "lff_bt_vars": bt_vars,
            })

    print(f"  Found {len(failures)} LFF failures\n")

    # For each failure, try all orderings to find the best
    has_zero_bt_count = 0
    lff_position_in_ranking = []

    # Also test alternative heuristics
    alt_heuristics = {
        "most_freq": ordering_most_frequent,
        "polarity": ordering_polarity_bias,
        "clause_wt": ordering_clause_weight,
        "neg_bias": ordering_neg_bias_first,
    }
    alt_zero_counts = defaultdict(int)

    for i, fail in enumerate(failures):
        clauses = fail["clauses"]

        # Brute force best ordering
        best_bt = float('inf')
        best_ordering = None
        all_bts = []
        for perm in itertools.permutations(range(1, n_vars + 1)):
            o = list(perm)
            _, bt, _, _ = solve_with_ordering(clauses, o, n_vars)
            all_bts.append(bt)
            if bt < best_bt:
                best_bt = bt
                best_ordering = o

        if best_bt == 0:
            has_zero_bt_count += 1

        # Where does LFF rank among all orderings?
        lff_bt = fail["lff_bt"]
        better_count = sum(1 for b in all_bts if b < lff_bt)
        rank_pct = better_count / len(all_bts) * 100
        lff_position_in_ranking.append(rank_pct)

        # Test alternatives
        for name, hfn in alt_heuristics.items():
            o = hfn(clauses, n_vars)
            _, bt, _, _ = solve_with_ordering(clauses, o, n_vars)
            if bt == 0:
                alt_zero_counts[name] += 1

        if i < 10:
            lff_o = fail["lff_ordering"]
            counts = Counter()
            for c in clauses:
                for l in c:
                    counts[abs(l)] += 1
            freq_str = " ".join(f"x{v}:{counts.get(v,0)}" for v in lff_o)
            print(f"  Instance {i+1} (seed={fail['seed']}):")
            print(f"    LFF ordering: {lff_o} (bt={lff_bt})")
            print(f"    Frequencies:  {freq_str}")
            print(f"    Best ordering: {best_ordering} (bt={best_bt})")
            print(f"    LFF bt vars:  {fail['lff_bt_vars']}")
            print(f"    {better_count}/{len(all_bts)} orderings are better than LFF ({rank_pct:.1f}%)")
            print()

    print(f"  SUMMARY:")
    print(f"  Of {len(failures)} LFF failures:")
    print(f"    {has_zero_bt_count} have a zero-BT ordering ({has_zero_bt_count/len(failures)*100:.1f}%)")
    print(f"    LFF rank: avg {sum(lff_position_in_ranking)/len(lff_position_in_ranking):.1f}% "
          f"of orderings are better")
    print(f"\n  Alternative heuristics on LFF failures:")
    for name in sorted(alt_zero_counts.keys()):
        ct = alt_zero_counts[name]
        print(f"    {name}: {ct}/{len(failures)} achieve zero-BT ({ct/len(failures)*100:.1f}%)")


# ─── Experiment 3: Backtrack Variable Analysis ───

def experiment_backtrack_variables(n_vars=6):
    """Which variables cause backtracks in LFF failures? What's special about them?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 3: Backtrack Variable Analysis (n={n_vars})")
    print("=" * 70)

    bt_var_positions = []  # position of backtrack var in LFF ordering
    bt_var_freq_ranks = []  # frequency rank of backtrack var
    bt_var_polarity_biases = []
    first_bt_var_is_first_decision = 0
    total_failures = 0

    for ratio in [3.0, 3.5, 4.0, 4.5, 5.0]:
        seed = 0
        found = 0
        while found < 200 and seed < 10000:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue
            found += 1

            ordering = ordering_least_frequent(clauses, n_vars)
            success, bt, decisions, bt_vars = solve_with_ordering(clauses, ordering, n_vars)

            if bt == 0:
                continue

            total_failures += 1

            # Frequency ranking
            counts = Counter()
            for c in clauses:
                for l in c:
                    counts[abs(l)] += 1

            freq_sorted = sorted(range(1, n_vars + 1), key=lambda v: counts.get(v, 0))

            # Polarity bias
            pos = Counter()
            neg = Counter()
            for c in clauses:
                for l in c:
                    if l > 0: pos[abs(l)] += 1
                    else: neg[abs(l)] += 1

            for bv in bt_vars:
                # Position in LFF ordering (0 = first)
                if bv in ordering:
                    pos_in_ordering = ordering.index(bv)
                    bt_var_positions.append(pos_in_ordering)

                # Frequency rank (0 = least frequent)
                freq_rank = freq_sorted.index(bv)
                bt_var_freq_ranks.append(freq_rank)

                # Polarity bias
                total = pos.get(bv, 0) + neg.get(bv, 0)
                if total > 0:
                    bias = abs(pos.get(bv, 0) - neg.get(bv, 0)) / total
                else:
                    bias = 0
                bt_var_polarity_biases.append(bias)

            # Is the first backtrack on the first decision?
            if bt_vars and bt_vars[0] == ordering[0]:
                first_bt_var_is_first_decision += 1

    print(f"\n  Total failures analyzed: {total_failures}")
    print(f"  Total backtrack events: {len(bt_var_positions)}")

    if bt_var_positions:
        print(f"\n  BACKTRACK VARIABLE POSITION in LFF ordering (0=first chosen):")
        pos_dist = Counter(bt_var_positions)
        for p in sorted(pos_dist.keys()):
            bar = "#" * int(pos_dist[p] / max(pos_dist.values()) * 40)
            print(f"    position {p}: {pos_dist[p]:>5} ({pos_dist[p]/len(bt_var_positions)*100:>5.1f}%) {bar}")

        print(f"\n  BACKTRACK VARIABLE FREQUENCY RANK (0=least frequent):")
        rank_dist = Counter(bt_var_freq_ranks)
        for r in sorted(rank_dist.keys()):
            bar = "#" * int(rank_dist[r] / max(rank_dist.values()) * 40)
            print(f"    rank {r}: {rank_dist[r]:>5} ({rank_dist[r]/len(bt_var_freq_ranks)*100:>5.1f}%) {bar}")

        print(f"\n  BACKTRACK VARIABLE POLARITY BIAS:")
        avg_bias = sum(bt_var_polarity_biases) / len(bt_var_polarity_biases)
        print(f"    Average: {avg_bias:.3f}")
        low_bias = sum(1 for b in bt_var_polarity_biases if b < 0.2)
        print(f"    Low bias (<0.2): {low_bias}/{len(bt_var_polarity_biases)} "
              f"({low_bias/len(bt_var_polarity_biases)*100:.1f}%)")

        print(f"\n  First backtrack is on first decision variable: "
              f"{first_bt_var_is_first_decision}/{total_failures} "
              f"({first_bt_var_is_first_decision/total_failures*100:.1f}%)")


# ─── Experiment 4: Can we predict failures? ───

def experiment_predict_failure(n_vars=6):
    """Build a simple decision rule to predict LFF failures."""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 4: Failure Prediction (n={n_vars})")
    print("=" * 70)

    instances = []
    for ratio in [3.0, 3.5, 4.0, 4.5, 5.0]:
        seed = 0
        found = 0
        while found < 300 and seed < 15000:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue
            found += 1

            ordering = ordering_least_frequent(clauses, n_vars)
            _, bt, _, _ = solve_with_ordering(clauses, ordering, n_vars)

            metrics = compute_metrics(clauses, n_vars, solutions)
            metrics["lff_fails"] = bt > 0
            instances.append(metrics)

    total = len(instances)
    fails = sum(1 for i in instances if i["lff_fails"])
    print(f"  Dataset: {total} instances, {fails} failures ({fails/total*100:.1f}%)")

    # Try simple threshold rules
    rules = [
        ("n_solutions <= 2", lambda i: i["n_solutions"] <= 2),
        ("n_solutions == 1", lambda i: i["n_solutions"] == 1),
        ("backbone_frac >= 0.5", lambda i: i["backbone_frac"] >= 0.5),
        ("backbone_frac >= 0.67", lambda i: i["backbone_frac"] >= 0.67),
        ("backbone_frac >= 0.83", lambda i: i["backbone_frac"] >= 0.83),
        ("conflict_rate >= 0.5", lambda i: i["conflict_rate"] >= 0.5),
        ("conflict_rate >= 0.6", lambda i: i["conflict_rate"] >= 0.6),
        ("freq_ratio >= 0.7", lambda i: i["freq_ratio"] >= 0.7),
        ("freq_ratio >= 0.8", lambda i: i["freq_ratio"] >= 0.8),
        ("degree_range <= 3", lambda i: i["degree_range"] <= 3),
        ("degree_range <= 2", lambda i: i["degree_range"] <= 2),
        ("min_polarity_bias < 0.1", lambda i: i["min_polarity_bias"] < 0.1),
        ("avg_polarity_bias < 0.2", lambda i: i["avg_polarity_bias"] < 0.2),
        # Compound rules
        ("sol<=2 AND bb>=0.5", lambda i: i["n_solutions"] <= 2 and i["backbone_frac"] >= 0.5),
        ("sol<=2 AND freq_ratio>=0.7", lambda i: i["n_solutions"] <= 2 and i["freq_ratio"] >= 0.7),
        ("sol==1 AND bb>=0.83", lambda i: i["n_solutions"] == 1 and i["backbone_frac"] >= 0.83),
        ("bb>=0.5 AND bias<0.2", lambda i: i["backbone_frac"] >= 0.5 and i["avg_polarity_bias"] < 0.2),
        ("bb>=0.67 AND deg_rng<=3", lambda i: i["backbone_frac"] >= 0.67 and i["degree_range"] <= 3),
    ]

    print(f"\n  {'Rule':<30} {'Predicted':>10} {'True Pos':>10} {'Precision':>10} {'Recall':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    for name, rule_fn in rules:
        predicted = sum(1 for i in instances if rule_fn(i))
        true_pos = sum(1 for i in instances if rule_fn(i) and i["lff_fails"])
        precision = true_pos / predicted * 100 if predicted > 0 else 0
        recall = true_pos / fails * 100 if fails > 0 else 0
        marker = " <<<" if precision > 20 and recall > 30 else ""
        print(f"  {name:<30} {predicted:>10} {true_pos:>10} {precision:>9.1f}% {recall:>9.1f}%{marker}")


# ─── Experiment 5: Hybrid Heuristic ───

def experiment_hybrid(n_vars=6):
    """Can we combine LFF with another heuristic to cover the gap?"""
    print(f"\n" + "=" * 70)
    print(f"  EXPERIMENT 5: Hybrid Heuristic Search (n={n_vars})")
    print("=" * 70)

    heuristics = {
        "lff": ordering_least_frequent,
        "mff": ordering_most_frequent,
        "polarity": ordering_polarity_bias,
        "clause_wt": ordering_clause_weight,
        "neg_bias": ordering_neg_bias_first,
    }

    # Count how often each pair covers all instances
    pair_coverage = defaultdict(lambda: {"both_fail": 0, "total": 0})

    for ratio in [3.0, 3.5, 4.0, 4.5, 5.0]:
        seed = 0
        found = 0
        while found < 300 and seed < 15000:
            clauses = generate_random_3sat(n_vars, ratio, seed=seed)
            seed += 1
            solutions = find_all_solutions(clauses, n_vars)
            if not solutions:
                continue
            found += 1

            results = {}
            for name, hfn in heuristics.items():
                o = hfn(clauses, n_vars)
                _, bt, _, _ = solve_with_ordering(clauses, o, n_vars)
                results[name] = (bt == 0)

            names = list(heuristics.keys())
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    pair = f"{names[i]}+{names[j]}"
                    pair_coverage[pair]["total"] += 1
                    if not results[names[i]] and not results[names[j]]:
                        pair_coverage[pair]["both_fail"] += 1

    print(f"\n  PAIR COVERAGE (how often at least one achieves zero-BT):")
    print(f"  {'Pair':<25} {'Total':>8} {'Both fail':>10} {'Coverage':>10}")
    print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*10}")

    for pair in sorted(pair_coverage.keys(), key=lambda p: pair_coverage[p]["both_fail"]):
        d = pair_coverage[pair]
        coverage = (d["total"] - d["both_fail"]) / d["total"] * 100
        print(f"  {pair:<25} {d['total']:>8} {d['both_fail']:>10} {coverage:>9.1f}%")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  THE COFFINHEAD CONJECTURE — Phase 4: The 1% Failure")
    print("▓" * 70)

    successes, failures = experiment_lff_failures(n_vars=6, n_target=500)
    experiment_optimal_vs_lff(n_vars=6, n_failures=30)
    experiment_backtrack_variables(n_vars=6)
    experiment_predict_failure(n_vars=6)
    experiment_hybrid(n_vars=6)

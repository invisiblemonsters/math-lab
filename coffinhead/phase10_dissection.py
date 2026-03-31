"""
THE COFFINHEAD CONJECTURE — Phase 10: Failure Dissection
=========================================================
Dissect the exact instances where k breaks.
Uses the same xorshift64 RNG as the C solvers for reproducibility.

k=2 fails at seed=14, n=18 (C solver)
k=3 fails at seed=27, n=48 (C solver)
"""

from collections import Counter, defaultdict


# ─── Xorshift64 RNG (matches C solver exactly) ───

class XorShift64:
    def __init__(self, seed):
        self.state = seed if seed != 0 else 1

    def next(self):
        s = self.state & 0xFFFFFFFFFFFFFFFF
        s ^= (s << 13) & 0xFFFFFFFFFFFFFFFF
        s ^= (s >> 7) & 0xFFFFFFFFFFFFFFFF
        s ^= (s << 17) & 0xFFFFFFFFFFFFFFFF
        self.state = s
        return s

    def randint(self, n):
        return self.next() % n


def generate_random_3sat_xor(n_vars, clause_ratio, seed):
    """Generate 3-SAT using xorshift64, matching C solver."""
    rng = XorShift64(seed)
    n_clauses = int(n_vars * clause_ratio)
    clauses = []
    for _ in range(n_clauses):
        clen = min(3, n_vars)
        clause_vars = []
        for j in range(clen):
            while True:
                v = 1 + rng.randint(n_vars)
                if v not in [abs(x) for x in clause_vars]:
                    break
            # polarity: rng.next() & 1
            if rng.next() & 1:
                clause_vars.append(v)
            else:
                clause_vars.append(-v)
        clauses.append(clause_vars)
    return clauses


# ─── Core SAT primitives ───

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
    new_a = dict(assignment)
    new_a[var] = value
    return unit_propagate(clauses, new_a)


# ─── k-step scoring ───

def score_kstep(clauses, assignment, var, value, n_vars, k):
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return -1000
    immediate = (len(new_a) - len(assignment) - 1) + (len(clauses) - len(remaining))
    if k <= 1:
        return immediate
    unassigned = get_unassigned(remaining, new_a)
    if not unassigned:
        return immediate + 100 * k
    best_next = -1000
    for v2 in unassigned:
        for val2 in [True, False]:
            s = score_kstep(remaining, new_a, v2, val2, n_vars, k - 1)
            if s > best_next:
                best_next = s
    return immediate + (best_next if best_next > -1000 else 0)


# ─── Tracing solver ───

def solve_traced(clauses, n_vars, k, verbose=True):
    """Solve with k-step lookahead, recording every decision."""
    decisions = []
    backtracks = 0

    def dpll(clauses, assignment, depth=0):
        nonlocal backtracks
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction:
            return None
        if not clauses:
            return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned:
            return None

        candidates = []
        for v in sorted(unassigned):
            for value in [True, False]:
                s = score_kstep(clauses, assignment, v, value, n_vars, k)
                candidates.append((s, v, value))
        candidates.sort(reverse=True)

        best_var, best_value = None, True
        for s, v, val in candidates:
            if s > -1000:
                best_var, best_value = v, val
                break
        if best_var is None:
            best_var = next(iter(unassigned))
            best_value = True

        # What did the solver see?
        top_n = min(6, len(candidates))
        decision_info = {
            'depth': depth,
            'var': best_var,
            'val': best_value,
            'score': candidates[0][0],
            'n_unassigned': len(unassigned),
            'n_clauses': len(clauses),
            'top_candidates': [(s, v, val) for s, v, val in candidates[:top_n]],
            'assigned_so_far': dict(assignment),
        }
        decisions.append(decision_info)

        if verbose:
            indent = "  " * depth
            val_str = "T" if best_value else "F"
            print(f"{indent}[d{depth}] {len(assignment)} set, {len(unassigned)} free, {len(clauses)} cls -> x{best_var}={val_str} (score={candidates[0][0]:.0f})")
            # Show score landscape
            for s, v, vl in candidates[:5]:
                marker = " ***" if v == best_var and vl == best_value else ""
                print(f"{indent}  x{v}={'T' if vl else 'F'}: {s:.0f}{marker}")

        a1 = dict(assignment); a1[best_var] = best_value
        result = dpll([list(c) for c in clauses], a1, depth + 1)
        if result is not None:
            return result

        backtracks += 1
        if verbose:
            indent = "  " * depth
            print(f"{indent}  *** BACKTRACK: x{best_var}={'T' if best_value else 'F'} FAILED ***")

        a2 = dict(assignment); a2[best_var] = not best_value
        return dpll([list(c) for c in clauses], a2, depth + 1)

    result = dpll(clauses, {})
    return result is not None, backtracks, decisions


# ─── Propagation depth analysis ───

def propagation_analysis(clauses, assignment, var, value, n_vars):
    """What happens when we set var=value? How deep does propagation go?"""
    new_a, remaining, contradiction = propagate_and_simplify(clauses, assignment, var, value)
    if contradiction:
        return {'contradiction': True}

    forced = {v: val for v, val in new_a.items() if v not in assignment and v != var}
    eliminated = len(clauses) - len(remaining)
    unassigned = get_unassigned(remaining, new_a)

    # For each remaining unassigned, check if either value contradicts
    forced_next = 0
    free_next = 0
    for v2 in unassigned:
        _, _, ct = propagate_and_simplify(remaining, new_a, v2, True)
        _, _, cf = propagate_and_simplify(remaining, new_a, v2, False)
        if ct and cf:
            return {'contradiction': True, 'delayed': True, 'var': v2}
        elif ct or cf:
            forced_next += 1
        else:
            free_next += 1

    return {
        'contradiction': False,
        'forced': forced,
        'n_forced': len(forced),
        'n_eliminated': eliminated,
        'remaining_clauses': len(remaining),
        'remaining_free': len(unassigned),
        'forced_at_next_level': forced_next,
        'free_at_next_level': free_next,
    }


# ─── MAIN DISSECTION ───

def dissect_failure(n_vars, seed, k_fail, k_pass):
    """Full dissection of a failure instance."""
    clauses = generate_random_3sat_xor(n_vars, 4.0, seed)

    print(f"\n{'#'*70}")
    print(f"  DISSECTING: n={n_vars}, seed={seed}")
    print(f"  k={k_fail} FAILS, k={k_pass} SUCCEEDS")
    print(f"{'#'*70}")
    print(f"  {len(clauses)} clauses, {n_vars} variables")

    # Variable polarity profile
    pos_count = Counter()
    neg_count = Counter()
    for c in clauses:
        for l in c:
            if l > 0: pos_count[l] += 1
            else: neg_count[-l] += 1

    print(f"\n  Polarity profile (sorted by total occurrence):")
    vars_by_occ = sorted(range(1, n_vars+1), key=lambda v: -(pos_count.get(v,0)+neg_count.get(v,0)))
    for v in vars_by_occ[:12]:
        p, n = pos_count.get(v, 0), neg_count.get(v, 0)
        bias = p - n
        print(f"    x{v:>2}: pos={p:>2} neg={n:>2} bias={bias:>+3} total={p+n:>2}")

    # Trace k_fail
    print(f"\n{'='*70}")
    print(f"  k={k_fail} TRACE (the one that FAILS)")
    print(f"{'='*70}")
    clauses1 = generate_random_3sat_xor(n_vars, 4.0, seed)
    sat1, bt1, decisions1 = solve_traced(clauses1, n_vars, k_fail, verbose=True)
    print(f"\n  k={k_fail}: SAT={sat1}, backtracks={bt1}")

    # Trace k_pass
    print(f"\n{'='*70}")
    print(f"  k={k_pass} TRACE (the one that SUCCEEDS)")
    print(f"{'='*70}")
    clauses2 = generate_random_3sat_xor(n_vars, 4.0, seed)
    sat2, bt2, decisions2 = solve_traced(clauses2, n_vars, k_pass, verbose=True)
    print(f"\n  k={k_pass}: SAT={sat2}, backtracks={bt2}")

    # Find first divergence
    print(f"\n{'='*70}")
    print(f"  DIVERGENCE ANALYSIS")
    print(f"{'='*70}")

    min_len = min(len(decisions1), len(decisions2))
    for i in range(min_len):
        d1 = decisions1[i]
        d2 = decisions2[i]
        if d1['var'] != d2['var'] or d1['val'] != d2['val']:
            print(f"\n  FIRST DIVERGENCE at decision #{i} (depth {d1['depth']}):")
            print(f"    k={k_fail} chose: x{d1['var']}={'T' if d1['val'] else 'F'} (score={d1['score']:.0f})")
            print(f"    k={k_pass} chose: x{d2['var']}={'T' if d2['val'] else 'F'} (score={d2['score']:.0f})")

            # What does each see at this point?
            # We need the formula state at this decision point
            # Use the assignment from the decision info
            clauses_at = generate_random_3sat_xor(n_vars, 4.0, seed)

            print(f"\n    k={k_fail} top candidates:")
            for s, v, val in d1['top_candidates']:
                print(f"      x{v}={'T' if val else 'F'}: score={s:.0f}")

            print(f"\n    k={k_pass} top candidates:")
            for s, v, val in d2['top_candidates']:
                print(f"      x{v}={'T' if val else 'F'}: score={s:.0f}")

            # Deep propagation analysis of both choices
            assign_at = d1['assigned_so_far']
            remaining, _, _ = unit_propagate(clauses_at, assign_at)
            # Can't easily reconstruct clause state — but we have the scores

            print(f"\n    WHY THEY DIVERGE:")
            print(f"    k={k_fail} sees {k_fail} steps ahead: immediate yield matters most")
            print(f"    k={k_pass} sees {k_pass} steps ahead: can see that x{d1['var']}={'T' if d1['val'] else 'F'}")
            print(f"      leads to a harder landscape {k_pass-k_fail} steps later")
            break
    else:
        if bt1 > 0 and bt2 == 0:
            print(f"  Same initial decisions for {min_len} steps, but k={k_fail} backtracks later.")
            print(f"  The failure is not in the FIRST decision but in a LATER one")
            print(f"  after the formula has been partially solved.")

            # Find where the backtrack happens in k_fail
            for i, d in enumerate(decisions1):
                if i > 0 and d['depth'] <= decisions1[i-1]['depth']:
                    print(f"\n  Backtrack happened after decision #{i-1}")
                    print(f"    depth went from {decisions1[i-1]['depth']} to {d['depth']}")
                    prev = decisions1[i-1]
                    print(f"    Bad decision: x{prev['var']}={'T' if prev['val'] else 'F'} at depth {prev['depth']}")
                    print(f"    Score was: {prev['score']:.0f}")
                    print(f"    {prev['n_unassigned']} vars free, {prev['n_clauses']} clauses")
                    break


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 10: FAILURE DISSECTION — Cracking the Base")
    print("▓" * 70)

    # THE BASE: k=2 fails at seed=14, n=18
    dissect_failure(18, 14, k_fail=2, k_pass=3)

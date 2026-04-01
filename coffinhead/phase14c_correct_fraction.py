"""
Phase 14c: Correct Fraction in Tied Group — Full Curve
========================================================
Measure the fraction of tied-for-best candidates that lead to
zero backtracks, across multiple (n, k) pairs.

Key question: does correct_fraction → 1 as k/diameter increases?
If yes, the redundancy proof works.
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
import time
import math


def solve_remaining(clauses, assignment, n_vars, k):
    bt = [0]
    def dpll(clauses, assignment):
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None
        candidates = []
        for v in sorted(unassigned):
            for value in [True, False]:
                s = score_kstep(clauses, assignment, v, value, n_vars, k)
                candidates.append((s, v, value))
        candidates.sort(reverse=True)
        bv, bval = None, True
        for s, v, val in candidates:
            if s > -1000: bv, bval = v, val; break
        if bv is None: bv = next(iter(unassigned)); bval = True
        a1 = dict(assignment); a1[bv] = bval
        r = dpll([list(c) for c in clauses], a1)
        if r: return r
        bt[0] += 1
        a2 = dict(assignment); a2[bv] = not bval
        return dpll([list(c) for c in clauses], a2)
    dpll(clauses, assignment)
    return bt[0]


def measure_correct_fraction(n_vars, k, n_samples=20, max_tied_test=10):
    """For each instance, find tied group, test each for zero-BT."""
    fracs = []
    tie_sizes = []
    seed = 0
    found = 0
    t0 = time.time()
    timeout = 90 if n_vars <= 20 else 120

    while found < n_samples and seed < n_samples * 100:
        if time.time() - t0 > timeout:
            break
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1

        a0, cl0, cont = unit_propagate(clauses, {})
        if cont or not cl0:
            continue
        unassigned = get_unassigned(cl0, a0)
        if len(unassigned) < 5:
            continue

        # Score all candidates
        scores = {}
        for v in sorted(unassigned):
            for val in [True, False]:
                scores[(v, val)] = score_kstep(cl0, a0, v, val, n_vars, k)

        safe = {c: s for c, s in scores.items() if s > -1000}
        if not safe:
            continue

        best = max(safe.values())
        tied = [c for c, s in safe.items() if s == best]
        tie_sizes.append(len(tied))

        # Test each tied candidate (cap for speed)
        n_test = min(len(tied), max_tied_test)
        n_correct = 0
        for v, val in tied[:n_test]:
            new_a = dict(a0)
            new_a[v] = val
            na, nc, cont2 = unit_propagate([list(c) for c in cl0], new_a)
            if cont2:
                continue  # contradiction = wrong
            bt = solve_remaining(nc, na, n_vars, k)
            if bt == 0:
                n_correct += 1

        frac = n_correct / n_test if n_test > 0 else 0
        fracs.append(frac)
        found += 1

    return fracs, tie_sizes


def main():
    print("=" * 70)
    print("  CORRECT FRACTION IN TIED GROUP — FULL CURVE")
    print("=" * 70)

    # Test matrix: each n with multiple k values
    # k at boundary, k above boundary, k well above
    test_cases = [
        # (n, k, description)
        (7, 1, "k=1 (below boundary)"),
        (7, 2, "k=2 (at boundary)"),
        (7, 3, "k=3 (above boundary)"),
        (10, 1, "k=1 (below)"),
        (10, 2, "k=2 (at boundary)"),
        (10, 3, "k=3 (above)"),
        (12, 2, "k=2 (at boundary)"),
        (12, 3, "k=3 (above)"),
        (15, 2, "k=2 (AT boundary)"),
        (15, 3, "k=3 (above)"),
        (18, 2, "k=2 (past boundary)"),
        (18, 3, "k=3 (at boundary)"),
        (20, 2, "k=2 (past)"),
        (20, 3, "k=3 (above)"),
        (25, 3, "k=3 (well above)"),
    ]

    print(f"\n  {'n':>4} {'k':>3} {'frac':>6} {'ties':>5} {'samples':>8} {'k/diam':>7}  description")
    print(f"  {'─'*4} {'─'*3} {'─'*6} {'─'*5} {'─'*8} {'─'*7}  {'─'*25}")

    all_data = []

    for n, k, desc in test_cases:
        fracs, ties = measure_correct_fraction(n, k, n_samples=20, max_tied_test=8)
        if not fracs:
            continue

        avg_frac = sum(fracs) / len(fracs)
        avg_ties = sum(ties) / len(ties)

        # Approximate diameter
        diam = 0.40 * math.log2(n)
        k_over_diam = k / diam if diam > 0 else 0

        all_data.append((n, k, avg_frac, k_over_diam))

        print(f"  {n:>4} {k:>3} {avg_frac:>6.3f} {avg_ties:>5.1f} {len(fracs):>8} {k_over_diam:>7.2f}  {desc}")

    # Summary: correct_fraction vs k/diameter
    print(f"\n{'='*70}")
    print(f"  CORRECT FRACTION vs k/diameter")
    print(f"{'='*70}")
    print(f"\n  {'k/diam':>7} {'correct':>8}")
    print(f"  {'─'*7} {'─'*8}")

    # Bin by k/diameter
    from collections import defaultdict
    bins = defaultdict(list)
    for n, k, frac, kd in all_data:
        # Round to nearest 0.25
        b = round(kd * 4) / 4
        bins[b].append(frac)

    for b in sorted(bins.keys()):
        avg = sum(bins[b]) / len(bins[b])
        print(f"  {b:>7.2f} {avg:>8.3f}  (n={len(bins[b])} points)")

    print(f"\n  If correct_fraction increases monotonically with k/diameter")
    print(f"  and approaches 1.0, the redundancy proof works.")
    print(f"  The solver succeeds because randomly picking from the tied")
    print(f"  group almost always picks a correct candidate.")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 14c: CORRECT FRACTION CURVE")
    print("▓" * 70)
    main()

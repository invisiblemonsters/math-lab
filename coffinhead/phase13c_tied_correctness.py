"""
Phase 13c: Are ALL tied candidates correct?
=============================================
Score gap is 0 — many candidates tie for best score.
If ALL tied candidates lead to zero backtracks, then the tie
doesn't matter and the proof takes a different form:

Instead of "the scorer picks the RIGHT candidate,"
the claim becomes "the scorer eliminates WRONG candidates,
and all survivors are correct."

This would be a MUCH easier proof target.
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
import time


def test_tied_candidates(n_vars, k, n_samples=15):
    """
    At the first decision, find all tied-for-best candidates.
    For each, solve the remaining formula. Do they ALL lead to zero BT?
    """
    results = []
    seed = 0
    found = 0
    t0 = time.time()

    while found < n_samples and seed < n_samples * 100:
        if time.time() - t0 > 120:
            break
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1

        assignment, clauses_up, contradiction = unit_propagate(clauses, {})
        if contradiction or not clauses_up:
            continue
        unassigned = get_unassigned(clauses_up, assignment)
        if len(unassigned) < 3:
            continue
        found += 1

        # Score all candidates
        candidates = []
        for v in sorted(unassigned):
            for value in [True, False]:
                s = score_kstep(clauses_up, assignment, v, value, n_vars, k)
                candidates.append((s, v, value))

        safe = [(s, v, val) for s, v, val in candidates if s > -1000]
        if not safe:
            continue

        best_score = max(s for s, _, _ in safe)
        tied = [(v, val) for s, v, val in safe if s == best_score]
        n_tied = len(tied)

        # For each tied candidate, solve with k-step to count backtracks
        all_zero = True
        bt_list = []
        for v, val in tied[:10]:  # limit to 10 to keep time reasonable
            # Solve: set this variable, then continue with k-step
            new_assign = dict(assignment)
            new_assign[v] = val
            new_a, new_clauses, contradiction = unit_propagate(
                [list(c) for c in clauses_up], new_assign)
            if contradiction:
                bt_list.append(-1)  # contradiction
                all_zero = False
                continue

            # Solve remaining with k-step
            bt = solve_remaining(new_clauses, new_a, n_vars, k)
            bt_list.append(bt)
            if bt > 0:
                all_zero = False

        results.append({
            'seed': seed - 1,
            'n_tied': n_tied,
            'all_zero': all_zero,
            'bt_list': bt_list,
        })

    return results


def solve_remaining(clauses, assignment, n_vars, k):
    """Solve with k-step lookahead from a partial assignment."""
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

        best_var, best_value = None, True
        for s, v, val in candidates:
            if s > -1000:
                best_var, best_value = v, val
                break
        if best_var is None:
            best_var = next(iter(unassigned))
            best_value = True

        a1 = dict(assignment); a1[best_var] = best_value
        r = dpll([list(c) for c in clauses], a1)
        if r: return r
        bt[0] += 1
        a2 = dict(assignment); a2[best_var] = not best_value
        return dpll([list(c) for c in clauses], a2)

    dpll(clauses, assignment)
    return bt[0]


def main():
    print("=" * 70)
    print("  ARE ALL TIED CANDIDATES CORRECT?")
    print("=" * 70)

    for n, k in [(10, 2), (15, 2), (18, 3), (20, 3)]:
        print(f"\n  n={n}, k={k}:")
        results = test_tied_candidates(n, k, n_samples=15)

        all_correct = 0
        some_wrong = 0
        for r in results:
            if r['all_zero']:
                all_correct += 1
            else:
                some_wrong += 1
                print(f"    seed={r['seed']}: {r['n_tied']} tied, bt={r['bt_list']} ← SOME WRONG")

        print(f"    {all_correct}/{len(results)} instances: ALL tied candidates correct")
        if some_wrong:
            print(f"    {some_wrong}/{len(results)} instances: some tied candidates WRONG")

        # Average tie size
        avg_tie = sum(r['n_tied'] for r in results) / len(results) if results else 0
        print(f"    avg tie size: {avg_tie:.1f}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 13c: TIED CANDIDATE CORRECTNESS")
    print("▓" * 70)
    main()

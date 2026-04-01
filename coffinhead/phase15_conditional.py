"""
Phase 15: Conditional Correct Fraction — The Self-Reinforcing Path
====================================================================
Key insight: each correct choice SIMPLIFIES the formula, making the
next choice easier. The correct fraction at depth d should be measured
CONDITIONAL on all previous choices being correct.

Also: measure using the ACTUAL tie-breaking rule (lowest variable index
first, matching the C solver's bit-scan order).

The proof needs: P(correct at depth 0) >= 1 - 1/n^2.
Then by union bound over n decisions: P(all correct) >= 1 - 1/n.
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
import time
import math


def solve_tracking_correctness(clauses, n_vars, k):
    """
    Solve with k-step lookahead, tracking at each decision:
    - How many candidates are tied for best
    - Whether the CHOSEN candidate (first by sorted order) leads to zero-BT
    - The correct fraction in the tied group
    
    Returns list of (depth, n_unassigned, n_tied, chosen_correct, frac_correct)
    """
    decisions = []
    total_bt = [0]
    
    def dpll(clauses, assignment, depth=0):
        assignment, clauses, contradiction = unit_propagate(clauses, assignment)
        if contradiction: return None
        if not clauses: return assignment
        unassigned = get_unassigned(clauses, assignment)
        if not unassigned: return None
        
        # Score all candidates
        scores = {}
        for v in sorted(unassigned):
            for val in [True, False]:
                scores[(v, val)] = score_kstep(clauses, assignment, v, val, n_vars, k)
        
        safe = {c: s for c, s in scores.items() if s > -1000}
        if not safe: return None
        best_score = max(safe.values())
        tied = sorted([c for c, s in safe.items() if s == best_score])
        
        # The solver picks the FIRST tied candidate (lowest var, True before False)
        chosen = tied[0]
        
        # Try the chosen candidate
        a1 = dict(assignment); a1[chosen[0]] = chosen[1]
        result = dpll([list(c) for c in clauses], a1, depth + 1)
        if result is not None:
            # Chosen was correct (led to solution without backtracking from here)
            decisions.append((depth, len(unassigned), len(tied), True))
            return result
        
        # Chosen was wrong — need to backtrack
        total_bt[0] += 1
        decisions.append((depth, len(unassigned), len(tied), False))
        
        # Try opposite
        a2 = dict(assignment); a2[chosen[0]] = not chosen[1]
        return dpll([list(c) for c in clauses], a2, depth + 1)
    
    result = dpll(clauses, {})
    return decisions, total_bt[0], result is not None


def measure_conditional_correctness(n_vars, k, n_samples=30):
    """
    Run the solver on many instances.
    Track the correctness of the chosen candidate at each depth,
    but ONLY along the zero-backtrack path (where all previous were correct).
    """
    from collections import defaultdict
    
    depth_stats = defaultdict(lambda: {'correct': 0, 'wrong': 0})
    total_zero_bt = 0
    total_tested = 0
    
    seed = 0
    found = 0
    t0 = time.time()
    timeout = 45 if n_vars <= 15 else 60
    
    while found < n_samples and seed < n_samples * 100:
        if time.time() - t0 > timeout:
            break
        
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1
        
        decisions, bt, sat = solve_tracking_correctness(clauses, n_vars, k)
        if not sat:
            continue
        found += 1
        total_tested += 1
        
        if bt == 0:
            total_zero_bt += 1
            # All decisions on this path were correct
            for depth, nunass, ntied, correct in decisions:
                depth_stats[depth]['correct'] += 1
        else:
            # Find where the FIRST wrong choice was
            for depth, nunass, ntied, correct in decisions:
                if correct:
                    depth_stats[depth]['correct'] += 1
                else:
                    depth_stats[depth]['wrong'] += 1
                    break  # stop at first wrong choice
    
    return depth_stats, total_zero_bt, total_tested


def main():
    print("=" * 70)
    print("  CONDITIONAL CORRECTNESS: Along the zero-BT path")
    print("=" * 70)
    
    test_cases = [
        (7, 2, "at boundary"),
        (7, 3, "above"),
        (10, 2, "at boundary"),
        (10, 3, "above"),
        (15, 2, "AT boundary"),
        (15, 3, "above"),
        (18, 3, "at boundary"),
        (20, 3, "above"),
        (25, 3, "well above"),
    ]
    
    print(f"\n  {'n':>4} {'k':>3} {'zero-BT':>8} {'d0_corr':>8} {'d1_corr':>8} {'d2_corr':>8}  note")
    print(f"  {'─'*4} {'─'*3} {'─'*8} {'─'*8} {'─'*8} {'─'*8}  {'─'*15}")
    
    for n, k, note in test_cases:
        stats, zero_bt, total = measure_conditional_correctness(n, k, n_samples=40)
        
        if total == 0:
            continue
        
        zbt_rate = f"{zero_bt}/{total}"
        
        # Correctness at each depth (conditional on path being correct so far)
        d_strs = []
        for d in range(3):
            if d in stats:
                c = stats[d]['correct']
                w = stats[d]['wrong']
                t = c + w
                frac = c / t if t > 0 else 0
                d_strs.append(f"{frac:.3f}")
            else:
                d_strs.append("—")
        
        print(f"  {n:>4} {k:>3} {zbt_rate:>8} {d_strs[0]:>8} {d_strs[1]:>8} {d_strs[2]:>8}  {note}")
    
    # The key question: at large n with k well above boundary,
    # what's the depth-0 correctness?
    print(f"\n{'='*70}")
    print(f"  DEPTH-0 CORRECTNESS vs n (k chosen to be above boundary)")
    print(f"{'='*70}")
    
    print(f"\n  {'n':>4} {'k':>3} {'d0_correct':>11} {'d0_wrong':>10} {'d0_rate':>8} {'1-1/n²':>8}")
    print(f"  {'─'*4} {'─'*3} {'─'*11} {'─'*10} {'─'*8} {'─'*8}")
    
    for n, k in [(7, 3), (10, 3), (15, 3), (18, 3), (20, 3)]:
        stats, zero_bt, total = measure_conditional_correctness(n, k, n_samples=50)
        if 0 in stats:
            c = stats[0]['correct']
            w = stats[0]['wrong']
            rate = c / (c + w) if (c + w) > 0 else 0
            target = 1 - 1/(n*n)
            meets = "✓" if rate >= target else "✗"
            print(f"  {n:>4} {k:>3} {c:>11} {w:>10} {rate:>8.4f} {target:>8.4f} {meets}")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 15: CONDITIONAL CORRECTNESS")
    print("▓" * 70)
    main()

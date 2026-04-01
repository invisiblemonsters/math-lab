"""
Phase 13b: Score Gap Analysis
===============================
The coupling proof needs: score gap between #1 and #2 grows faster
than the fringe perturbation.

Measure: at the first decision, when k is large enough for zero-BT,
what's the gap between the best candidate and the runner-up?
How does this gap scale with n?
"""

from phase10_dissection import (
    generate_random_3sat_xor, unit_propagate, get_unassigned,
    score_kstep
)
import time
import math


def measure_score_gaps(n_vars, k, n_samples=15):
    """Measure score gap between #1 and #2 at the first decision."""
    gaps = []
    top_scores = []
    second_scores = []

    seed = 0
    found = 0
    t0 = time.time()

    while found < n_samples and seed < n_samples * 100:
        if time.time() - t0 > 120:
            break
        clauses = generate_random_3sat_xor(n_vars, 4.0, seed)
        seed += 1

        # Quick SAT check via unit prop
        assignment, clauses_up, contradiction = unit_propagate(clauses, {})
        if contradiction:
            continue
        if not clauses_up:
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
                if s > -1000:
                    candidates.append(s)

        if len(candidates) < 2:
            continue

        candidates.sort(reverse=True)
        gap = candidates[0] - candidates[1]
        gaps.append(gap)
        top_scores.append(candidates[0])
        second_scores.append(candidates[1])

    return gaps, top_scores, second_scores


def main():
    print("=" * 70)
    print("  SCORE GAP: Does the margin grow with n?")
    print("=" * 70)

    # Test at k that achieves zero-BT for each n
    test_cases = [
        (10, 2), (15, 2), (18, 3), (20, 3), (25, 3),
    ]

    print(f"\n  {'n':>5} {'k':>3} {'avg_gap':>8} {'med_gap':>8} {'avg_top':>8} {'gap/top':>8} {'samples':>8}")
    print(f"  {'─'*5} {'─'*3} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")

    gap_data = {}

    for n, k in test_cases:
        gaps, tops, seconds = measure_score_gaps(n, k, n_samples=20)
        if not gaps:
            print(f"  {n:>5} {k:>3} {'—':>8}")
            continue

        avg_gap = sum(gaps) / len(gaps)
        med_gap = sorted(gaps)[len(gaps)//2]
        avg_top = sum(tops) / len(tops)
        gap_ratio = avg_gap / avg_top if avg_top > 0 else 0
        gap_data[n] = avg_gap

        print(f"  {n:>5} {k:>3} {avg_gap:>8.1f} {med_gap:>8.1f} {avg_top:>8.1f} {gap_ratio:>8.3f} {len(gaps):>8}")

    # Also measure at FIXED k across n (k=2 for all, to see how gap changes)
    print(f"\n  FIXED k=2 across n (shows how gap changes at boundary):")
    print(f"  {'n':>5} {'avg_gap':>8} {'avg_top':>8} {'gap/top':>8} {'zero_gap%':>10}")
    print(f"  {'─'*5} {'─'*8} {'─'*8} {'─'*8} {'─'*10}")

    for n in [7, 10, 12, 15, 18, 20]:
        gaps, tops, _ = measure_score_gaps(n, 2, n_samples=20)
        if not gaps:
            continue
        avg_gap = sum(gaps)/len(gaps)
        avg_top = sum(tops)/len(tops)
        gap_ratio = avg_gap / avg_top if avg_top > 0 else 0
        zero_frac = sum(1 for g in gaps if g == 0) / len(gaps) * 100
        print(f"  {n:>5} {avg_gap:>8.1f} {avg_top:>8.1f} {gap_ratio:>8.3f} {zero_frac:>9.0f}%")

    # What does this mean for the proof?
    print(f"\n{'='*70}")
    print(f"  INTERPRETATION FOR PROOF")
    print(f"{'='*70}")
    print(f"""
  The coupling proof needs: score_gap >> fringe_perturbation

  Fringe perturbation ≤ Δ · |B_k(v)| ≤ 48 · 0.03n = 1.44n

  For the gap to dominate, we need gap = ω(n).

  If gap = O(1) (constant), the fringe can flip the ranking → proof fails.
  If gap = Θ(n) (linear), the fringe perturbation is O(n) too → marginal.
  If gap = ω(n) (superlinear), the proof works.

  The gap/top ratio tells us if the gap grows proportionally to the total
  score (which is Θ(n)). If gap/top is constant, gap = Θ(n).
""")


if __name__ == "__main__":
    print("\n" + "▓" * 70)
    print("  PHASE 13b: SCORE GAP ANALYSIS")
    print("▓" * 70)
    main()

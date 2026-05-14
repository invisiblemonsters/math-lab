#!/usr/bin/env python3
"""
Collect zero-backtrack rates for the phase transition figure.
Uses the compiled k4v2 solver with subprocess timeout.
Each instance gets a 30s timeout — timeout = failure.
"""
import subprocess
import sys
import re
import json

SOLVER = "./k4v2"
TIMEOUT_PER_INSTANCE = 60  # seconds

def run_rate(k, n, target, threads=16):
    """Run solver and parse results. Returns (tested, zero_bt, rate)."""
    try:
        result = subprocess.run(
            [SOLVER, str(n), str(k), str(target), "4.0", str(threads)],
            capture_output=True, text=True,
            timeout=target * TIMEOUT_PER_INSTANCE + 30
        )
        output = result.stdout
        # Parse "RESULT k=X n=Y: A/B = C% zero-BT"
        m = re.search(r'(\d+)/(\d+) = ([\d.]+)% zero-BT', output)
        if m:
            zero_bt = int(m.group(1))
            tested = int(m.group(2))
            rate = float(m.group(3))
            return tested, zero_bt, rate
    except subprocess.TimeoutExpired:
        pass
    return 0, 0, -1

def main():
    configs = [
        # k=1: fast, test many n values
        (1, list(range(5, 55, 5)), 30),
        # k=2: fast up to ~30, then slower
        (2, [5,8,10,12,14,15,16,17,18,19,20,22,25,28,30,35,40,45,50], 30),
        # k=3: medium speed
        (3, [15,20,25,30,35,40,42,44,45,46,47,48,50,55,60], 20),
    ]
    
    print("k,n,tested,zero_bt,rate")
    for k, n_values, target in configs:
        for n in n_values:
            sys.stderr.write(f"Running k={k} n={n} target={target}...\n")
            sys.stderr.flush()
            tested, zero_bt, rate = run_rate(k, n, target)
            if tested > 0:
                print(f"{k},{n},{tested},{zero_bt},{rate}")
                sys.stdout.flush()
            else:
                sys.stderr.write(f"  TIMEOUT k={k} n={n}\n")

if __name__ == "__main__":
    main()

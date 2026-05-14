#!/bin/bash
# k=4 boundary scan — background runner
# Tests n=101..128 (u128 solver limit) with 15 hard-core instances each
# Looking for the FIRST failure
# Run with: nohup bash k4_scan_background.sh > k4_scan.log 2>&1 &

cd ~/projects/math-lab/coffinhead

echo "=== k=4 BOUNDARY SCAN started $(date) ==="
echo "Strategy: scan n=101..128, 15 instances each, k=4 exact"
echo ""

# Recompile with higher timeouts
gcc -O3 -march=native -fopenmp -o lookahead_par lookahead_parallel.c -lm

for n in 101 102 103 104 105 106 107 108 109 110 112 114 116 118 120 122 124 126 128; do
    echo ""
    echo "=== n=$n k=4 — started $(date) ==="
    
    # Use the u128 solver (faster for n<=128)
    # Increased wall timeout to 86400s (24h), instance timeout handled internally at 120s
    # But we need to patch the solver... let's just use the v2 solver with no timeout
    ./k4v2 $n 4 15 4.0 16
    
    echo "=== n=$n complete — $(date) ==="
done

echo ""
echo "=== SCAN COMPLETE $(date) ==="

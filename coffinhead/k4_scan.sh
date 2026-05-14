#!/bin/bash
# k=4 EXACT boundary scan
# Uses top-screened solver (screen=50 for safety — higher than needed)
# Tests n=105,110,115,120,125,130,135,140 with 10 HC instances each
# Stops at first failure, then narrows

cd ~/projects/math-lab/coffinhead

echo "=== k=4 BOUNDARY SCAN — $(date) ==="
echo "Using top-screened solver, screen_width=50"
echo ""

for n in 105 110 115 120 125 130 135 140 150; do
    echo "============================================"
    echo ">>> n=$n k=4, 10 HC instances — $(date)"
    echo "============================================"
    ./k4_top $n 4 10 4.0 16 50
    echo ""
done

echo "=== SCAN COMPLETE — $(date) ==="

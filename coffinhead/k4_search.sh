#!/bin/bash
echo "=== COFFINHEAD k=4 EXACT BOUNDARY SEARCH ==="
echo "Started: $(date)"
echo ""

for n in 56 58 60 62 64 66 68 70 75 80 85 90 95 100; do
    echo "--- n=$n ---"
    timeout 1800 ./lookahead_par $n 4 20 4.0 16
    rc=$?
    if [ $rc -eq 124 ]; then
        echo "TIMEOUT at n=$n (30min)"
        break
    fi
    echo ""
done

echo ""
echo "Finished: $(date)"

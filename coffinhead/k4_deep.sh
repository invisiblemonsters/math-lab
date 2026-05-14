#!/bin/bash
echo "=== K=4 DEEP BOUNDARY SEARCH (2hr timeout per n) ==="
echo "Started: $(date)"

for n in 90 95 100 110; do
    echo ""
    echo "--- n=$n ---"
    timeout 7200 ./lookahead_par $n 4 20 4.0 16
    rc=$?
    if [ $rc -eq 124 ]; then
        echo "TIMEOUT at n=$n (2hr)"
        break
    fi
done

echo ""
echo "Finished: $(date)"

#!/bin/bash
echo "=== K=4 DEEP BOUNDARY SEARCH v2 (3hr timeout, n=105-128) ==="
echo "Started: $(date)"

for n in 105 110 115 120 125 128; do
    echo ""
    echo "--- n=$n ---"
    timeout 10800 ./lookahead_par $n 4 20 4.0 16
    rc=$?
    if [ $rc -eq 124 ]; then
        echo "TIMEOUT at n=$n (3hr)"
        break
    fi
done

echo ""
echo "Finished: $(date)"

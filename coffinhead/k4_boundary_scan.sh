#!/bin/bash
# k=4 boundary scan — tests increasing n values
# Uses original u128 solver (faster for n<=128)
# Logs everything to k4_scan.log

cd ~/projects/math-lab/coffinhead
LOG=k4_scan.log

echo "=== k=4 BOUNDARY SCAN started $(date) ===" | tee -a $LOG

# Test each n with 10 hard-core instances
# If ANY fail, we found the boundary region
for n in 105 110 115 120 125; do
    echo "" | tee -a $LOG
    echo ">>> Testing n=$n k=4 (10 instances) — $(date)" | tee -a $LOG
    ./lookahead_par $n 4 10 4.0 16 2>&1 | tee -a $LOG
    
    # Check if any failures
    if grep -q "BREAKS" <<< "$(tail -2 $LOG)"; then
        echo "*** FAILURE FOUND AT n=$n — narrowing down ***" | tee -a $LOG
        break
    fi
    echo ">>> n=$n PASSED — $(date)" | tee -a $LOG
done

echo "" | tee -a $LOG
echo "=== SCAN COMPLETE $(date) ===" | tee -a $LOG

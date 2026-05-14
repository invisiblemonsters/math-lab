#!/bin/bash
# Run CaDiCaL and Kissat on all hard-core instances, collect conflict stats

cd ~/projects/math-lab/coffinhead

echo "================================================================"
echo "  CDCL SOLVER COMPARISON ON COFFINHEAD HARD-CORE INSTANCES"
echo "  $(date)"
echo "================================================================"
echo ""

for n in 15 20 30 47 48 50 75 100; do
    echo "--- n=$n ---"
    
    cadical_total_conflicts=0
    cadical_zero=0
    cadical_count=0
    kissat_total_conflicts=0
    kissat_zero=0
    kissat_count=0
    
    for f in cdcl_instances/n${n}/hc_n${n}_*.cnf; do
        # CaDiCaL
        c=$(cadical --quiet "$f" 2>&1 | grep "^c conflicts:" | awk '{print $3}')
        if [ -z "$c" ]; then c=0; fi
        cadical_total_conflicts=$((cadical_total_conflicts + c))
        if [ "$c" -eq 0 ]; then cadical_zero=$((cadical_zero + 1)); fi
        cadical_count=$((cadical_count + 1))
        
        # Kissat
        k=$(kissat --quiet "$f" 2>&1 | grep "^c conflicts:" | awk '{print $3}')
        if [ -z "$k" ]; then k=0; fi
        kissat_total_conflicts=$((kissat_total_conflicts + k))
        if [ "$k" -eq 0 ]; then kissat_zero=$((kissat_zero + 1)); fi
        kissat_count=$((kissat_count + 1))
    done
    
    cadical_avg=$(echo "scale=2; $cadical_total_conflicts / $cadical_count" | bc)
    kissat_avg=$(echo "scale=2; $kissat_total_conflicts / $kissat_count" | bc)
    
    echo "  CaDiCaL: $cadical_zero/$cadical_count zero-conflict, avg=$cadical_avg conflicts"
    echo "  Kissat:  $kissat_zero/$kissat_count zero-conflict, avg=$kissat_avg conflicts"
    echo ""
done

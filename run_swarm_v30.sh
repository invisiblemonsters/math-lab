#!/bin/bash
# Math Lab v30 Swarm — Continuous Runner
cd /home/power/projects/math-lab
source /home/power/.elan/env 2>/dev/null

echo "=== Math Lab v30 Swarm — Continuous Runner ==="
echo "Started: $(date)"

while true; do
    echo ""
    echo "=== Starting new session: $(date) ==="
    python3 -u pnp-swarm-v30.py 2>&1 | tee -a /tmp/math-lab-v30.log
    echo "=== Session ended: $(date) ==="
    echo "Cooling down 60s..."
    sleep 60
done

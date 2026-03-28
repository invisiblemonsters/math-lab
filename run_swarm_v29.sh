#!/bin/bash
# Math Lab v29 Swarm — Continuous Runner
# Runs sessions back-to-back with 60s cooldown

cd /home/power/projects/math-lab
source /home/power/.elan/env 2>/dev/null

echo "=== Math Lab v29 Swarm — Continuous Runner ==="
echo "Started: $(date)"

while true; do
    echo ""
    echo "=== Starting new session: $(date) ==="
    python3 pnp-swarm-v29.py 2>&1 | tee -a /tmp/math-lab-v29.log
    echo "=== Session ended: $(date) ==="
    echo "Cooling down 60s..."
    sleep 60
done

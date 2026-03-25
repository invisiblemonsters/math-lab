#!/bin/bash
# Continuous math lab runner — starts a new session as soon as the previous one finishes
# Usage: nohup ./run_continuous.sh &

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin:$HOME/.elan/bin"
cd ~/projects/math-lab

while true; do
    echo "$(date): Starting new session..."
    python3 pnp-formal-v2.py 2>&1 | tee -a /tmp/math-lab-continuous.log
    
    # Push to GitHub after each session
    git push origin main 2>/dev/null
    
    echo "$(date): Session complete. Sleeping 60s before next run..."
    sleep 60
done

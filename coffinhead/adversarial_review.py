#!/usr/bin/env python3
"""
Adversarial Stress-Test of the Coffinhead Conjecture
=====================================================
Uses NVIDIA free-tier models to attack the conjecture from multiple angles.
Each model plays a different adversarial role.
"""

import os
import json
import time
import base64
import requests
import concurrent.futures
from pathlib import Path

# Load API key
key_b64 = Path(os.path.expanduser("~/projects/math-lab/.api_key_b64")).read_text().strip()
API_KEY = base64.b64decode(key_b64).decode()
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

CONJECTURE = """
THE COFFINHEAD CONJECTURE (empirical, 2026):

For random 3-SAT at clause-to-variable ratio 4.0, k-step propagation lookahead 
in DPLL achieves zero backtracks on all satisfiable hard-core instances when k 
is sufficiently large. The required k grows as O(log n), specifically:

  k = 1.04 * log2(n) - 1.94

ALGORITHM: At each decision point in DPLL, evaluate ALL (variable, value) pairs 
by recursively simulating k levels of assignment + unit propagation. Score each 
by cumulative propagation yield (forced variables + eliminated clauses). Pick 
the highest-scoring candidate. No backtracking needed if k is sufficient.

EMPIRICAL DATA (exact solver, ground truth):
  k=2: zero backtracks through n=15, first failure at n=18
  k=3: zero backtracks through n=47, first failure at n=48  
  k=4: zero backtracks through n=100 (no failure found, compute-limited)
  
BEAM-APPROXIMATE DATA (lower bounds only):
  k=5: zero backtracks through n>=125 (beam=6)
  k=6: zero backtracks through n>=160 (beam=3)
  k=7: zero backtracks through n>=180 (beam=2)

STRUCTURAL CONNECTION:
  Constraint graph diameter = 0.40 * log2(n), measured from n=5 to n=10,000.
  The solver needs k ≈ 2.5 * diameter to achieve zero backtracks.

COMPLEXITY IMPLICATIONS:
  If k = O(log n) and beam width B = O(1), total cost per decision is 
  O(n * B^k) = O(n * B^{c*log n}) = O(n^{1+c*log B}), which is polynomial.
  This would be a polynomial-time algorithm for random 3-SAT at ratio 4.0.

CONTEXT:
  - Ratio 4.0 is above the clustering barrier (~3.86) where ALL known 
    polynomial algorithms provably fail (Achlioptas & Coja-Oghlan 2008).
  - Best known rigorous polynomial algorithm works only to ratio ~3.52.
  - Alekhnovich's DPLL lower bounds apply to refutation of UNSATISFIABLE 
    instances, not to finding satisfying assignments.
  - Validated on SATLIB benchmarks (uf20 through uf100).
"""

ADVERSARIAL_ROLES = [
    {
        "model": "meta/llama-3.1-405b-instruct",
        "role": "Complexity Theorist",
        "prompt": f"""You are a skeptical complexity theorist reviewing the following conjecture. 
Your job is to find FATAL FLAWS — theoretical impossibility results that would 
contradict this conjecture, or logical errors in the reasoning.

{CONJECTURE}

Specifically address:
1. Does Alekhnovich's lower bound really not apply here? Could there be a 
   reduction from refutation to search that would make the lower bound relevant?
2. The Overlap Gap Property (OGP) framework — does it apply to this algorithm?
3. Is there a known impossibility result for polynomial-time algorithms at 
   ratio 4.0 for satisfiable random 3-SAT?
4. Is the complexity calculation correct? Is O(n * B^(c*log n)) really polynomial?
5. Any other theoretical red flags?

Be harsh. Find the weakest points."""
    },
    {
        "model": "nvidia/nemotron-ultra-253b-v1",
        "role": "SAT Solver Expert",
        "prompt": f"""You are an expert on SAT solver algorithms, particularly lookahead solvers 
(march, satz, kcnfs, OKsolver). Review this conjecture:

{CONJECTURE}

Your questions:
1. How does this "k-step lookahead" differ from what existing lookahead solvers 
   already do? Is this really novel or has someone done multi-step recursive 
   scoring before?
2. The "hard core" definition uses JW and adaptive polarity as baselines. Could 
   the hard core definition be biased in a way that makes the results look 
   better than they are?
3. At n=100 with k=4 exact scoring, the cost per decision is O(n^8). With ~50 
   decisions, that's O(n^9). Is the solver actually finding satisfying 
   assignments, or is it just getting lucky on easy instances?
4. The beam approximation — could beam search be introducing a systematic bias 
   that happens to align with correct choices?
5. What would a SAT competition researcher think of these claims?"""
    },
    {
        "model": "qwen/qwen3-235b-a22b",
        "role": "Statistician",
        "prompt": f"""You are a statistician reviewing the empirical methodology of this conjecture:

{CONJECTURE}

Critically evaluate:
1. Sample sizes: The exact solver tests "1 instance per n value" at large n. 
   Is this statistically meaningful? Could seed selection bias the results?
2. The scaling law k = 1.04 * log2(n) - 1.94 is fitted on TWO exact failure 
   points (n=15 at k=2, n=48 at k=3) plus one lower bound (n>=100 at k=4). 
   Can you fit a meaningful curve to 2 points plus a lower bound?
3. The beam calibration: correction factor 1.237 measured at ONE k value (k=3). 
   Is it valid to extrapolate this to higher k?
4. The "hard core" fraction grows with n. Could there be a selection effect 
   where harder instances are harder to GENERATE at larger n, biasing the 
   sample toward easier hard-core instances?
5. What would be the minimum sample sizes needed to make these claims rigorous?"""
    },
    {
        "model": "mistralai/mistral-large-2-instruct-2411",
        "role": "Devil's Advocate",
        "prompt": f"""You are a devil's advocate. Your ONLY job is to argue that this conjecture 
is WRONG and to propose the most likely way it fails:

{CONJECTURE}

Consider:
1. The growth factor is DECELERATING: 3.13x (k=2->3) then >=2.13x (k=3->4). 
   What if it continues decelerating? Model this: if growth factor at step i 
   is 3.13 * 0.68^i, where does k=5's boundary land? k=10's?
2. The solver hasn't FOUND a failure at k=4 — it ran out of compute. What if 
   the failure is at n=101? That would make the growth factor barely above 2x 
   and decelerating.
3. "Zero backtracks" might just mean the scoring function is very good, not 
   perfect. At n=200 with k=7, maybe 1 in 1000 instances fails. We tested 3.
4. The connection to diameter could be coincidental. Diameter = O(log n) for 
   ANY sparse random graph. What structural property specifically makes 
   lookahead work?
5. What is the MOST LIKELY failure mode of this conjecture?"""
    },
    {
        "model": "google/gemma-3-27b-it",
        "role": "Peer Reviewer",
        "prompt": f"""You are a peer reviewer for a top theory conference (STOC/FOCS/SODA). 
This paper claims empirical evidence for a polynomial-time algorithm for 
random 3-SAT at ratio 4.0 — above the clustering barrier. Review:

{CONJECTURE}

Write a brief referee report addressing:
1. Significance: If true, how important is this result?
2. Novelty: Is the approach genuinely new?
3. Correctness: Are there obvious errors in the methodology or claims?
4. Completeness: What's missing that would be needed for acceptance?
5. Overall recommendation: Accept / Weak Accept / Weak Reject / Reject
   with justification."""
    },
]

def query_model(model, prompt, role_name):
    """Query a single NVIDIA model."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "")
            # Handle reasoning models
            if not content:
                content = data["choices"][0]["message"].get("reasoning_content", "[no content]")
            return role_name, model, content
        else:
            return role_name, model, f"[ERROR {resp.status_code}: {resp.text[:200]}]"
    except Exception as e:
        return role_name, model, f"[EXCEPTION: {str(e)[:200]}]"

def main():
    print("=" * 70)
    print("ADVERSARIAL STRESS-TEST: COFFINHEAD CONJECTURE")
    print("=" * 70)
    print(f"Testing with {len(ADVERSARIAL_ROLES)} adversarial models...")
    print()
    
    results = []
    
    # Run all models in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for role in ADVERSARIAL_ROLES:
            f = executor.submit(query_model, role["model"], role["prompt"], role["role"])
            futures.append(f)
        
        for f in concurrent.futures.as_completed(futures):
            role_name, model, response = f.result()
            results.append((role_name, model, response))
            print(f"[DONE] {role_name} ({model})")
    
    # Print results
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    for role_name, model, response in sorted(results, key=lambda x: x[0]):
        print()
        print(f"### {role_name} ({model})")
        print("-" * 50)
        print(response)
        print()
    
    # Save to file
    output_path = os.path.expanduser("~/projects/math-lab/coffinhead/adversarial_results.md")
    with open(output_path, "w") as f:
        f.write("# Adversarial Stress-Test Results\n\n")
        f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M')}\n\n")
        for role_name, model, response in sorted(results, key=lambda x: x[0]):
            f.write(f"## {role_name} ({model})\n\n")
            f.write(response)
            f.write("\n\n---\n\n")
    print(f"\nResults saved to {output_path}")

if __name__ == "__main__":
    main()

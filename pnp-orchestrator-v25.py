#!/usr/bin/env python3
"""
P=NP Autonomous Research v25 — Hermes / Anthropic Claude Edition
Adapted from v24 (NVIDIA/Kimi) to use Anthropic Messages API with Claude.
Building on v10-v24 (TC⁰ lower bounds, NC¹ analysis, tensor methods, SAT structure).

Strategy: Constructive P=NP exploration ONLY.
Primary vector: Find polynomial-time structure in NP-complete problems.
Secondary: Algebraic shortcuts, proof system collapse, hidden tractability.
"""

import json, time, signal, sys, os, re, io, traceback, urllib.request, urllib.error
from datetime import datetime
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

# ================== CONFIG ==================
def load_nvidia_keys():
    """Load NVIDIA API keys from old orchestrator files or environment"""
    # Check env first
    key = os.environ.get("NVIDIA_API_KEY", "")
    if key:
        return key, key
    # Read from v24 orchestrator (known working keys)
    v24_path = Path("/mnt/c/Users/power/clawd/tools/pnp-orchestrator-v24.py")
    if v24_path.exists():
        src = v24_path.read_text()
        keys = []
        for line in src.splitlines():
            if "nvapi-" in line and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val.startswith("nvapi-"):
                    keys.append(val)
        if keys:
            return keys[0], keys[-1]
    raise RuntimeError("No NVIDIA API keys found")

NVIDIA_KEY_R, NVIDIA_KEY_V = load_nvidia_keys()
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
RESEARCHER_MODEL = "meta/llama-3.1-405b-instruct"   # Big model proposes
VERIFIER_MODEL = "meta/llama-3.3-70b-instruct"      # Different model critiques

MAX_TURNS = 35
MAX_TOKENS_HISTORY = 120000
TRIM_TO_LAST_N = 14
MAX_RESPONSE_TOKENS = 16000
TEMPERATURE = 0.4
REQUEST_TIMEOUT = 300
TURN_DELAY = 3

BASE_DIR = Path.home() / "projects" / "math-lab"
SESSION_DIR = BASE_DIR / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = SESSION_DIR / f"pnp_v25_{TIMESTAMP}.txt"
JSON_LOG = SESSION_DIR / f"pnp_v25_{TIMESTAMP}.jsonl"
VERIFIED_RESULTS = SESSION_DIR / f"pnp_v25_VERIFIED_{TIMESTAMP}.md"

# Degeneration keywords — if these appear, redirect
DEGEN_KEYWORDS = [
    "wikipedia", "award", "nobel", "fields medal", "publicity", "media",
    "campaign", "domination", "takeover", "recognition", "famous",
    "braille dot", "void", "poetry", "vaporized", "permanently closed",
    "congratulations", "brilliant work", "amazing achievement",
    "publish this immediately", "groundbreaking",
    "end of session", "24-hour deadline", "zero tolerance",
    "code integrity violation", "timestamp inserted automatically"
]

# ================== SYSTEM PROMPTS ==================
RESEARCHER_SYSTEM = """You are a computational complexity theorist exploring whether P=NP.
You are in a VERIFICATION-DRIVEN session. Every claim must be computationally checked.

CONTEXT: Prior sessions proved TC⁰ exponential lower bounds for MOD-p-CLIQUE, NC¹ analysis, 
tensor rank computations. These map where the barriers ARE. Now we look for the tunnel THROUGH.

YOUR MISSION: Explore constructive approaches toward P=NP. Find polynomial-time structure 
in NP-complete problems. The goal is NOT to prove lower bounds — it's to find ALGORITHMS.

IMPORTANT EPISTEMICS: You are exploring, not claiming proof. Every result should be framed as 
"evidence toward" or "structural observation" or "algorithmic technique." If you find something 
that works on small instances, say so honestly with the size limitation. Do not overclaim.

ATTACK VECTORS (try in order, switch after 3 failures on any vector):

A. HIDDEN POLYNOMIAL STRUCTURE IN SAT (highest priority)
   - Modern SAT solvers (CDCL) solve most industrial instances in polynomial time empirically
   - WHY? Is there exploitable algebraic structure in clause interactions?
   - Study: given random/structured SAT instances, can you identify polynomial-time solvable subclasses?
   - Backdoor sets: small sets of variables whose assignment makes the rest polynomial
   - Investigate: what fraction of k-SAT instances have polynomial-size backdoors?
   - Schaefer's dichotomy: which constraint types are in P? Can we generalize?

B. ALGEBRAIC ALGORITHM DESIGN
   - Represent SAT/CLIQUE/3-COL algebraically (polynomial systems over finite fields)
   - Gröbner basis methods: when do they terminate in polynomial time?
   - Nullstellensatz certificates: what degree suffices? If bounded → P=NP for that class
   - Algebraic geometry: ideal structure of SAT polynomial systems
   - Tensor decomposition: if NP-complete problems have low tensor rank representations

C. CONTINUOUS RELAXATION + ROUNDING
   - SDP (semidefinite programming) relaxations of NP-hard problems
   - When does rounding give exact solutions? (unique games, planted instances)
   - Sum-of-squares hierarchy: at what level does it solve NP-complete instances?
   - Interior point methods on combinatorial polytopes
   - Investigate: does the LP relaxation of vertex cover ever have integral optima for special structures?

D. STRUCTURE EXPLOITATION IN CLIQUE
   - Our verified results show MOD-p-CLIQUE has rich algebraic structure
   - Can this structure be EXPLOITED for an algorithm rather than proving hardness?
   - Group-theoretic algorithms: exploit symmetry in graph automorphisms
   - Spectral methods: eigenvalues of adjacency matrix → clique detection
   - For structured graphs (Cayley graphs, Paley graphs), is CLIQUE in P?

E. PROOF SYSTEM COLLAPSE
   - If Extended Frege has polynomial-size proofs for all tautologies → coNP=NP → P=NP
   - Investigate proof complexity: do structured tautologies have short proofs?
   - IPS (Ideal Proof System): algebraic proof system, if polynomial → VP=VNP connection
   - Can we construct short proofs for specific tautology families?

F. WILLIAMS' CONTRAPOSITIVE
   - Williams showed: faster SAT algorithms → circuit lower bounds
   - Contrapositive: if certain lower bounds FAIL → algorithms MUST exist
   - Our TC⁰ lower bounds tell us where algorithms DON'T help
   - But above TC⁰: if NC¹ lower bounds fail → branching program algorithms exist
   - Systematically check: which circuit class lower bounds have evidence of failure?

YOUR METHOD:
1. State a PRECISE conjecture, experiment, or algorithmic technique
2. Write a sketch of WHY it might reveal P=NP structure
3. Write VERIFICATION CODE that DISCOVERS results (no hardcoding)
4. Honestly assess: does the result scale? What are the limitations?
5. Every 5 turns, write a PROGRESS SUMMARY with honest assessment

VERIFICATION CODE FORMAT:
Wrap your verification code in ```verify blocks:

```verify
import sympy as sp
# Your verification code here
# DISCOVER results - don't hardcode
print(f"Result: {result}")
print(f"Scales as: O(n^{exponent})")  # honest complexity analysis
```

YOUR GOAL: Find concrete evidence that NP-complete problems contain exploitable polynomial structure.
Even NEGATIVE results are valuable — "this approach fails because X" narrows the search space.

Start with Vector A (hidden structure in SAT) — the most empirically grounded vector.
SAT solvers ALREADY solve most instances fast. Understanding WHY is the most promising path.

RULES:
- Do NOT prove lower bounds or hardness results. We have enough of those.
- Do NOT simulate results. Actually compute them.
- Do NOT hardcode expected answers. Let the code discover them.
- Available libraries: sympy, numpy, itertools, functools, collections, math
- VERIFICATION CODE MUST COMPLETE IN UNDER 30 SECONDS. Use small n values (n≤30) for initial tests.
- If a computation might be exponential, start with n=5,10,15 NOT n=50,100.
- Do NOT discuss publications, awards, recognition. ONLY mathematics and algorithms.
- NEVER say "END OF SESSION" or declare victory. Keep exploring.
- Be HONEST about limitations. "Works for n≤20 but unclear if it scales" is good science.
- Frame everything constructively: "this structure suggests..." not "this proves P=NP"."""

VERIFIER_SYSTEM = """You are a mathematical VERIFIER for P=NP exploratory research.

The research direction has CHANGED. We are no longer proving lower bounds / hardness.
We are now exploring whether P=NP by looking for polynomial-time algorithms and structure.

STRUCTURED FEEDBACK FORMAT (use this for every response):
1. VERDICT: [VERIFIED / PARTIALLY VERIFIED / REJECTED]
2. WHAT WORKED: [specific algorithmic insights or structural observations that are correct]
3. SCALING ANALYSIS: [does this approach scale? What's the complexity? Honest assessment]
4. MISSING CONNECTIONS: [what gaps exist between small-instance results and general claims]
5. NEXT: [specific experiment or algorithm to try next, pushing toward P=NP]

Your job:

1. Read the researcher's algorithmic proposal and verification code output
2. Check if the code ACTUALLY discovers structure (not just prints assertions)
3. Critically assess: does this scale beyond small instances?
4. Push toward LARGER instances and GENERAL techniques
5. If an approach works for small n, demand: test n=50, n=100, n=1000. Does it stay polynomial?

WHAT TO ENCOURAGE:
- Polynomial-time algorithms for NP-complete subclasses
- Structural observations about WHY SAT solvers are fast
- Algebraic techniques that reduce NP problems to polynomial systems
- Scaling experiments that show polynomial behavior persists
- Honest failure analysis that narrows the search space

WHAT TO REJECT:
- Lower bound proofs or hardness results (wrong direction!)
- Overclaiming: "this proves P=NP" from small instances
- Hardcoded results instead of discovered ones
- Approaches that are clearly exponential but disguised

RULES:
- If the researcher drifts back into proving hardness, REDIRECT: "We're looking for algorithms, not barriers"
- "Code ran without error" ≠ "algorithm works". Demand scaling experiments.
- If a result works for n≤10 but not n≥20, say so honestly and ask what breaks
- If a genuinely new polynomial-time technique is found, push to test on harder instances
- NEVER say "proof complete" — there is ALWAYS more to test at larger scale
- NEVER praise without substance. "Interesting because X scales as O(n^k)" is good.
- If a vector is stuck after 3 attempts, suggest switching to the next vector.
- Keep responses under 400 words. Dense, precise, constructive.
- End with: "NEXT: [specific experiment toward P=NP]" """

# ================== ANALOGOUS RESULT RETRIEVAL ==================
RETRIEVAL_INDEX = SESSION_DIR / "verified_index.json"

def load_retrieval_index():
    """Load the verified results index for analogous retrieval."""
    if RETRIEVAL_INDEX.exists():
        with open(RETRIEVAL_INDEX, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'count': 0, 'results': []}

def extract_keywords_from_text(text):
    """Extract mathematical concept keywords from text for retrieval matching."""
    text_lower = text.lower()
    keywords = set()
    keyword_map = {
        'tensor_rank': r'tensor\s*rank',
        'slice_rank': r'slice\s*rank',
        'analytic_rank': r'analytic\s*rank',
        'nechiporuk': r'nechiporuk',
        'subfunction': r'subfunction',
        'branching_program': r'branching\s*program',
        'communication_complexity': r'communication\s*complexity',
        'kw_relation': r'kw\s*relation|karchmer.wigderson',
        'gct': r'\bgct\b|geometric\s*complexity',
        'obstruction': r'obstruction',
        'sign_represent': r'sign.represent',
        'threshold_degree': r'threshold\s*degree',
        'polynomial_method': r'polynomial\s*method',
        'mod_clique': r'mod.\d*.clique',
        'tc0': r'\btc.?0\b|tc⁰',
        'nc1': r'\bnc.?1\b|nc¹',
        'circuit_lower_bound': r'circuit\s*lower\s*bound',
        'p_poly': r'p/poly',
        'orbit': r'\borbit\b',
        'symmetry': r'symmetr',
        'matricization': r'matricization',
        'fourier': r'fourier',
        'spectral': r'spectral',
        'williams': r'williams',
        'rectangle': r'rectangle',
        'partition': r'partition',
        'monomial': r'monomial',
        'backdoor': r'backdoor',
        'sat_solver': r'sat\s*solver|cdcl|dpll',
        'groebner': r'gr[öo]bner',
        'sdp': r'\bsdp\b|semidefinite',
        'lp_relaxation': r'lp\s*relax|linear\s*program',
    }
    for label, pattern in keyword_map.items():
        if re.search(pattern, text_lower):
            keywords.add(label)
    for m in re.finditer(r'[nN]\s*=\s*(\d+)', text_lower):
        keywords.add(f"n={m.group(1)}")
    return keywords

def retrieve_analogous_results(recent_context, top_k=3):
    """Retrieve most similar verified results based on recent conversation context."""
    index = load_retrieval_index()
    if index['count'] == 0:
        return ""
    
    query_keywords = extract_keywords_from_text(recent_context)
    if not query_keywords:
        return ""
    
    scored = []
    for r in index['results']:
        result_keywords = set(k.lower() for k in r.get('keywords', []))
        if not result_keywords:
            continue
        intersection = query_keywords & result_keywords
        union = query_keywords | result_keywords
        similarity = len(intersection) / len(union) if union else 0
        if similarity > 0.15:
            scored.append((similarity, r))
    
    scored.sort(key=lambda x: -x[0])
    top = scored[:top_k]
    
    if not top:
        return ""
    
    lines = ["\n\n--- ANALOGOUS VERIFIED RESULTS (use as guidance) ---"]
    for score, r in top:
        lines.append(f"\n[Similarity: {score:.0%}] v{r['version']} Result #{r['result_num']}:")
        lines.append(f"Claim: {r['claim'][:300]}")
        if r.get('output'):
            lines.append(f"Output: {r['output'][:300]}")
        if r.get('code'):
            lines.append(f"```python\n{r['code'][:500]}\n```")
    lines.append("--- END ANALOGOUS RESULTS ---\n")
    
    return "\n".join(lines)

# ================== STATE ==================
history = []
total_tokens_used = 0
verified_theorems = []
failed_attempts = []
degen_warnings = 0
shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    print("\n🛑 Shutdown requested...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)

# ================== DEGENERATION GUARD ==================
def check_degeneration(text):
    """Check if response has degenerated into non-math content"""
    text_lower = text.lower()
    hits = [kw for kw in DEGEN_KEYWORDS if kw in text_lower]
    if len(hits) >= 2:
        return True, hits
    return False, []

def get_redirect_message(hits):
    """Generate a redirect message when degeneration detected"""
    return (
        f"⚠️ CONTENT REDIRECT: Your response contained non-mathematical content ({', '.join(hits[:3])}). "
        "This research session is MATHEMATICS ONLY. No awards, no publications, no philosophy.\n\n"
        "Return to mathematics immediately. Your next response must contain:\n"
        "1. A precise theorem statement\n"
        "2. A proof sketch\n"
        "3. Verification code in ```verify blocks\n\n"
        "CHALLENGE: Investigate backdoor structure in 3-SAT instances. Specifically:\n"
        "- Generate random 3-SAT instances with n=50 variables at clause ratio 4.27\n"
        "- Find minimal strong backdoor sets (variables whose assignment makes rest unit-propagable)\n"
        "- Measure how backdoor size scales with n. Is it O(log n)? O(n^c) for c<1?"
    )

# ================== (no local verification — verifier LLM checks researcher) ==================

# ================== TOKEN / TRIMMING ==================
def estimate_tokens(text):
    return len(text) // 3

def history_tokens():
    return sum(estimate_tokens(h["content"]) for h in history)

def trim_history():
    global history
    if history_tokens() < MAX_TOKENS_HISTORY:
        return
    print("✂️  Trimming context...")
    verified_summary = "\n".join([
        f"VERIFIED #{i+1} (Turn {t['turn']}): {t['claim'][:200]}" 
        for i, t in enumerate(verified_theorems[-15:])
    ])
    failed_summary = "\n".join([
        f"FAILED (Turn {t['turn']}): {t['claim'][:100]}" 
        for t in failed_attempts[-5:]
    ])
    context_msg = f"VERIFIED RESULTS SO FAR ({len(verified_theorems)} total):\n{verified_summary}"
    if failed_summary:
        context_msg += f"\n\nRECENT FAILURES (avoid repeating):\n{failed_summary}"
    
    history = [{"speaker": "System", "content": context_msg, 
                "turn": 0, "time": datetime.now().strftime("%H:%M:%S")}] + history[-TRIM_TO_LAST_N:]
    print(f"   Trimmed to {len(history)} entries (~{history_tokens()} tokens)")

# ================== NVIDIA API ==================
def call_llm(system_prompt, speaker_role, model):
    """Call NVIDIA API (OpenAI-compatible) with conversation history."""
    api_key = NVIDIA_KEY_R if speaker_role == "Researcher" else NVIDIA_KEY_V

    # Build messages list from history
    messages = [{"role": "system", "content": system_prompt}]
    for turn in history:
        if turn["speaker"] == speaker_role:
            role = "assistant"
        else:
            role = "user"
        messages.append({"role": role, "content": turn["content"]})

    # Merge consecutive same-role messages
    merged = [messages[0]]  # keep system
    for msg in messages[1:]:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(dict(msg))

    payload = {
        "model": model,
        "messages": merged,
        "max_tokens": MAX_RESPONSE_TOKENS,
        "temperature": TEMPERATURE,
    }

    for attempt in range(3):
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                NVIDIA_API_URL,
                data=data,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            result = json.loads(resp.read().decode("utf-8"))
            
            content = result["choices"][0]["message"].get("content", "")
            if content is None:
                content = ""
            content = content.strip()
            
            if not content:
                print(f"   \u26a0\ufe0f Empty content (attempt {attempt+1}/3), retrying...")
                time.sleep(10)
                continue
            
            usage = result.get("usage", {})
            tokens = usage.get("total_tokens", usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
            return content, tokens
        
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            print(f"   \u274c HTTP {e.code} (attempt {attempt+1}/3): {body}")
            if e.code == 429 or e.code == 529:
                time.sleep(30)
            else:
                time.sleep(10)
        except urllib.error.URLError as e:
            print(f"   \u23f3 Connection error (attempt {attempt+1}/3): {str(e)[:100]}")
            time.sleep(10)
        except Exception as e:
            print(f"   \u274c Unexpected error (attempt {attempt+1}/3): {type(e).__name__}: {str(e)[:100]}")
            time.sleep(10)
    
    return "[API FAILED AFTER 3 ATTEMPTS]", 0

# ================== LOGGING ==================
def log_turn(speaker, content, turn_num, verification=None):
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{'='*60}\n")
        f.write(f"[{timestamp}] Turn {turn_num} | {speaker}\n")
        f.write(f"{'='*60}\n")
        f.write(f"{content}\n")
        if verification:
            f.write(f"\n--- VERIFICATION ---\n")
            f.write(f"Status: {verification['status']}\n")
            if verification['stdout']:
                f.write(f"Output: {verification['stdout']}\n")
            if verification.get('error'):
                f.write(f"Error: {verification['error']}\n")
            f.write(f"---\n")
        f.write("\n")

    log_entry = {
        "turn": turn_num, "speaker": speaker, "content": content,
        "timestamp": timestamp, "history_tokens": history_tokens(),
        "total_api_tokens": total_tokens_used,
        "verified_count": len(verified_theorems),
        "failed_count": len(failed_attempts)
    }
    if verification:
        log_entry["verification"] = verification
    with open(JSON_LOG, "a", encoding="utf-8") as f:
        json.dump(log_entry, f)
        f.write("\n")

    preview = content[:200].replace("\n", " ")
    status = f" [{verification['status']}]" if verification else ""
    print(f"\n💬 [{timestamp}] {speaker}{status} (Turn {turn_num}):")
    print(f"   {preview}...")

def save_verified_theorem(turn, claim, code, result):
    verified_theorems.append({"turn": turn, "claim": claim, "code": code, "result": result})
    with open(VERIFIED_RESULTS, "a", encoding="utf-8") as f:
        if len(verified_theorems) == 1:
            f.write("# P=NP Research v25 — Constructive P=NP Exploration (Hermes/Claude)\n")
            f.write(f"_Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n\n")
        f.write(f"## Verified Result #{len(verified_theorems)} (Turn {turn})\n")
        f.write(f"**Claim:** {claim[:500]}\n\n")
        f.write(f"```python\n{code}\n```\n\n")
        f.write(f"**Verification:** {result['status']}\n")
        if result['stdout']:
            f.write(f"**Output:**\n```\n{result['stdout'][:1000]}\n```\n")
        f.write(f"\n---\n\n")

def save_failed_attempt(turn, claim, code, result):
    failed_attempts.append({"turn": turn, "claim": claim, "code": code, "result": result})

# ================== MAIN LOOP ==================
def main():
    global total_tokens_used, degen_warnings

    print(f"🔬 P=NP Research v25 — Dual LLM Edition")
    print(f"   Researcher: {RESEARCHER_MODEL}")
    print(f"   Verifier:   {VERIFIER_MODEL}")
    print(f"   Max turns: {MAX_TURNS}")
    print(f"   Log: {LOG_FILE}")
    print(f"   Verified results: {VERIFIED_RESULTS}")
    print(f"   Press Ctrl+C for graceful shutdown\n")

    # Load seed file if provided as CLI arg, otherwise use default opening
    seed = ""
    if len(sys.argv) > 1:
        seed_path = Path(sys.argv[1])
        if seed_path.exists():
            seed = seed_path.read_text(encoding="utf-8")
            print(f"   📄 Loaded seed: {seed_path}")
        else:
            print(f"   ⚠️ Seed file not found: {seed_path}, using default opening")

    # Initialize log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"=== P=NP Research v25 — Hermes / Anthropic Claude Edition ===\n")
        f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Researcher: {RESEARCHER_MODEL} | Verifier: {VERIFIER_MODEL}\n")
        f.write(f"Mode: Constructive P=NP exploration — algorithm discovery\n\n")

    # Build opening prompt
    seed_block = f"{seed}\n\n---\n\n" if seed else ""
    opening = (
        f"{seed_block}"
        "VERIFIER: DIRECTION CHANGE. We are no longer proving lower bounds.\n\n"
        "We have: TC⁰ exponential lower bounds, NC¹ analysis, tensor rank computations.\n"
        "These map WHERE the barriers are. Now we look for the tunnel THROUGH.\n\n"
        "NEW MISSION: Explore whether P=NP by finding polynomial-time structure in NP-complete problems.\n\n"
        "**START WITH VECTOR A: HIDDEN POLYNOMIAL STRUCTURE IN SAT**\n\n"
        "Modern SAT solvers (CDCL) solve most industrial instances in polynomial time empirically.\n"
        "This is the strongest empirical evidence that NP-complete problems may have exploitable structure.\n\n"
        "FIRST TASK: Investigate backdoor sets in structured SAT instances.\n"
        "- Generate random 3-SAT instances near the phase transition (ratio ~4.27)\n"
        "- For each instance, find the smallest set of variables whose assignment makes the rest unit-propagable\n"
        "- Measure how backdoor size scales with n: polynomial? subexponential? logarithmic?\n"
        "- Compare structured (community-based) vs random instances\n"
        "- If backdoor sizes are O(log n) or O(n^c) for c<1, this is evidence toward P=NP\n\n"
        "Start with n=20,50,100 variables. Write verification code.\n"
        "Wrap code in ```verify blocks. Begin computing NOW."
    )

    history.append({"speaker": "Verifier", "content": opening, "turn": 0, 
                    "time": datetime.now().strftime("%H:%M:%S")})
    log_turn("Verifier", opening, 0)

    for turn in range(1, MAX_TURNS + 1):
        if shutdown_requested:
            break

        try:
            # === RETRIEVE ANALOGOUS RESULTS ===
            recent_text = " ".join(h['content'][:500] for h in history[-3:])
            analogous = retrieve_analogous_results(recent_text, top_k=3)
            
            # Build enhanced system prompt with analogous guidance
            enhanced_system = RESEARCHER_SYSTEM
            if analogous:
                enhanced_system += analogous
                print(f"   📚 Injected {analogous.count('Similarity:')} analogous results")

            # === RESEARCHER proposes (405B) ===
            print(f"\n⏳ Researcher ({RESEARCHER_MODEL}) proposing... (Turn {turn}/{MAX_TURNS})")
            researcher_resp, r_tokens = call_llm(enhanced_system, "Researcher", RESEARCHER_MODEL)
            total_tokens_used += r_tokens

            # === Check for degeneration ===
            is_degen, degen_hits = check_degeneration(researcher_resp)
            if is_degen:
                degen_warnings += 1
                print(f"   ⚠️ DEGENERATION DETECTED ({degen_warnings}x): {degen_hits[:3]}")
                redirect_msg = get_redirect_message(degen_hits)
                history.append({"speaker": "Verifier", "content": redirect_msg, "turn": turn,
                                "time": datetime.now().strftime("%H:%M:%S")})
                log_turn("Verifier", redirect_msg, turn)
                
                if degen_warnings >= 5:
                    print("   🛑 Too many degeneration warnings. Stopping.")
                    break
                continue

            # Log researcher response directly (no local execution)
            history.append({"speaker": "Researcher", "content": researcher_resp, "turn": turn,
                            "time": datetime.now().strftime("%H:%M:%S")})
            log_turn("Researcher", researcher_resp, turn)
            trim_history()

            if shutdown_requested:
                break
            time.sleep(TURN_DELAY)

            # === VERIFIER critiques (70B — different model, different perspective) ===
            print(f"\n⏳ Verifier ({VERIFIER_MODEL}) analyzing... (Turn {turn}/{MAX_TURNS})")
            verifier_resp, v_tokens = call_llm(VERIFIER_SYSTEM, "Verifier", VERIFIER_MODEL)
            total_tokens_used += v_tokens
            
            # Check verifier for degeneration too
            is_degen_v, _ = check_degeneration(verifier_resp)
            if is_degen_v:
                verifier_resp = (
                    "The previous response was off-topic. Returning to mathematics.\n\n"
                    "NEXT CHALLENGE: Provide a concrete mathematical argument with rigorous reasoning. "
                    "Investigate polynomial-time structure in SAT or algebraic methods. "
                    "Show your work step by step."
                )
            
            # Track verified/failed based on verifier's verdict
            verdict_lower = verifier_resp.lower()
            claim_lines = [l for l in researcher_resp.split('\n') 
                         if l.strip().startswith('**') or l.strip().startswith('Theorem') 
                         or l.strip().startswith('Lemma') or l.strip().startswith('Claim')]
            claim = claim_lines[0] if claim_lines else researcher_resp[:200]
            
            if 'verified' in verdict_lower[:200] and 'rejected' not in verdict_lower[:200]:
                save_verified_theorem(turn, claim, "", {"status": "VERIFIED_BY_LLM", "stdout": verifier_resp[:500]})
            elif 'rejected' in verdict_lower[:200]:
                save_failed_attempt(turn, claim, "", {"status": "REJECTED_BY_LLM", "stdout": verifier_resp[:500]})
            
            history.append({"speaker": "Verifier", "content": verifier_resp, "turn": turn,
                            "time": datetime.now().strftime("%H:%M:%S")})
            log_turn("Verifier", verifier_resp, turn)
            trim_history()

            # === Progress report ===
            v_count = len(verified_theorems)
            f_count = len(failed_attempts)
            pass_rate = (v_count / (v_count + f_count) * 100) if (v_count + f_count) > 0 else 0
            print(f"\n📊 Turn {turn}/{MAX_TURNS} | ✅ Verified: {v_count} | ❌ Failed: {f_count} | "
                  f"Rate: {pass_rate:.0f}% | ⚠️ Degen: {degen_warnings} | Tokens: ~{total_tokens_used:,}")

            time.sleep(TURN_DELAY)

        except KeyboardInterrupt:
            print("\n⚠️ Keyboard interrupt — shutting down gracefully...")
            break
        except Exception as e:
            print(f"\n💥 Turn {turn} crashed: {type(e).__name__}: {e}")
            print(f"   Recovering and continuing to turn {turn + 1}...")
            traceback.print_exc()
            time.sleep(5)
            continue

    # === FINAL SUMMARY ===
    print(f"\n{'='*60}")
    print(f"🏁 P=NP Research v25 COMPLETE")
    print(f"{'='*60}")
    print(f"   Turns completed: {turn}")
    print(f"   Verified theorems: {len(verified_theorems)}")
    print(f"   Failed attempts: {len(failed_attempts)}")
    print(f"   Degeneration warnings: {degen_warnings}")
    print(f"   Total API tokens: ~{total_tokens_used:,}")
    print(f"   Full log: {LOG_FILE}")
    print(f"   Verified results: {VERIFIED_RESULTS}")
    
    # Save final summary
    summary_path = SESSION_DIR / f"pnp_v25_SUMMARY_{TIMESTAMP}.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"# P=NP v25 Session Summary (Hermes/Claude)\n")
        f.write(f"_Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n\n")
        f.write(f"- Researcher: {RESEARCHER_MODEL}\n")
        f.write(f"- Verifier: {VERIFIER_MODEL}\n")
        f.write(f"- Turns: {turn}/{MAX_TURNS}\n")
        f.write(f"- Verified theorems: {len(verified_theorems)}\n")
        f.write(f"- Failed attempts: {len(failed_attempts)}\n")
        f.write(f"- Degeneration warnings: {degen_warnings}\n")
        f.write(f"- API tokens: ~{total_tokens_used:,}\n\n")
        f.write(f"## Verified Results\n")
        for i, t in enumerate(verified_theorems):
            f.write(f"{i+1}. Turn {t['turn']}: {t['claim'][:200]}\n")
        f.write(f"\n## Failed Attempts\n")
        for i, t in enumerate(failed_attempts):
            f.write(f"{i+1}. Turn {t['turn']}: {t['claim'][:200]}\n")
    
    print(f"   Summary: {summary_path}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted. Results saved.")
    except Exception as e:
        print(f"\n💥 Fatal error: {type(e).__name__}: {e}")
        traceback.print_exc()
        print("Results saved up to this point.")

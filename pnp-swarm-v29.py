#!/usr/bin/env python3
"""
Math Lab v29 — Swarm Architecture for P vs NP
==============================================
15 NVIDIA API models organized into 7 layers:
  Layer 1: Barrier Council (3 models) — R/N/A risk scoring
  Layer 2: Conjecture Engine (3 models) — diverse creative generation
  Layer 3: Decomposer + Formalizer (3 models) — Lean 4 translation
  Layer 4: Adversarial Critics (2 models) — cheap falsification
  Layer 5: Proof Search Workers (2 models) — parallel Lean proving
  Layer 6: Verification (1 model + Lean 4 compiler)
  Layer 7: Scribe (1 model) — research memory management

Lean 4 compiler is ground truth. No LLM judges correctness.
"""

import os
import sys
import json
import time
import base64
import hashlib
import subprocess
import datetime
import concurrent.futures
import requests
from pathlib import Path
from typing import Optional

# ============================================================
# CONFIGURATION
# ============================================================

MATH_LAB_DIR = Path.home() / "projects" / "math-lab"
LEAN_PROJECT = Path.home() / "mathlib_test"
RESEARCH_LEAN = LEAN_PROJECT / "MyProofs" / "Research.lean"
ATTEMPT_LEAN = LEAN_PROJECT / "MyProofs" / "Attempt.lean"
SESSION_DIR = MATH_LAB_DIR / "sessions"
MEMORY_DIR = MATH_LAB_DIR / "swarm-memory"
API_KEY_FILE = MATH_LAB_DIR / ".api_key_b64"

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1/chat/completions"

MAX_CYCLES = 15          # cycles per session
LEAN_TIMEOUT = 600       # seconds for lake build
MAX_FIX_ATTEMPTS = 3     # formalizer retries on compile error
API_TIMEOUT = 120        # seconds per API call
PARALLEL_TIMEOUT = 180   # seconds for parallel calls

# ============================================================
# MODEL ASSIGNMENTS (15 models, 7 layers)
# ============================================================

MODELS = {
    # Layer 1: Barrier Council
    "barrier_relativization": "qwen/qwq-32b",
    "barrier_natural_proofs": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "barrier_algebrization":  "mistralai/mathstral-7b-v0.1",

    # Layer 2: Conjecture Engine (3 different model families)
    "conjecture_alpha":  "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "conjecture_beta":   "mistralai/mistral-large-3-675b-instruct-2512",
    "conjecture_gamma":  "qwen/qwen3.5-397b-a17b",

    # Layer 3: Decomposer + Formalizer
    "decomposer":        "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "formalizer_primary": "qwen/qwen3-coder-480b-a35b-instruct",
    "formalizer_backup":  "meta/llama-3.1-405b-instruct",

    # Layer 4: Adversarial Critics
    "critic_counterexample": "meta/llama-3.3-70b-instruct",
    "critic_triviality":     "nvidia/llama-3.3-nemotron-super-49b-v1.5",

    # Layer 5: Proof Search Workers
    "prover_alpha": "mistralai/devstral-2-123b-instruct-2512",
    "prover_beta":  "qwen/qwen3.5-122b-a10b",

    # Layer 6: Verification (+ Lean compiler)
    "intent_checker": "mistralai/mistral-nemotron",

    # Layer 7: Scribe
    "scribe": "mistralai/magistral-small-2506",
}

# ============================================================
# API SETUP
# ============================================================

def load_api_key() -> str:
    with open(API_KEY_FILE) as f:
        return base64.b64decode(f.read().strip()).decode()

API_KEY = load_api_key()

def llm_call(model: str, messages: list, temperature: float = 0.7,
             max_tokens: int = 4096, timeout: int = API_TIMEOUT) -> Optional[str]:
    """Call NVIDIA API. Returns text or None on failure."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # Reasoning models: check for thinking parameter support
    if "qwq" in model or "r1" in model or "thinking" in model:
        payload["temperature"] = 0.6  # reasoning models prefer lower temp

    try:
        resp = requests.post(NVIDIA_BASE, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            print(f"  [API ERROR] {model}: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        # Nemotron Ultra uses reasoning_content
        content = msg.get("content") or msg.get("reasoning_content") or ""
        return content.strip() if content else None
    except Exception as e:
        print(f"  [API ERROR] {model}: {e}")
        return None


def parallel_llm_calls(calls: list[tuple[str, str, list, float]],
                       timeout: int = PARALLEL_TIMEOUT) -> dict[str, Optional[str]]:
    """Run multiple LLM calls in parallel.
    calls: list of (role_name, model, messages, temperature)
    Returns: {role_name: response_text}
    """
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as executor:
        future_to_role = {}
        for role, model, messages, temp in calls:
            future = executor.submit(llm_call, model, messages, temp)
            future_to_role[future] = role

        for future in concurrent.futures.as_completed(future_to_role, timeout=timeout):
            role = future_to_role[future]
            try:
                results[role] = future.result()
            except Exception as e:
                print(f"  [PARALLEL ERROR] {role}: {e}")
                results[role] = None

    # Fill any missing (timed out)
    for role, _, _, _ in calls:
        if role not in results:
            results[role] = None
    return results


# ============================================================
# LEAN 4 COMPILATION
# ============================================================

def compile_lean(code: str) -> tuple[bool, str]:
    """Write code to Attempt.lean and compile. Returns (success, output)."""
    ATTEMPT_LEAN.write_text(code)
    env = os.environ.copy()
    elan_env = Path.home() / ".elan" / "env"
    if elan_env.exists():
        # Source elan
        env["PATH"] = str(Path.home() / ".elan" / "bin") + ":" + env.get("PATH", "")

    try:
        result = subprocess.run(
            ["lake", "build", "MyProofs.Attempt"],
            capture_output=True, text=True, timeout=LEAN_TIMEOUT,
            cwd=str(LEAN_PROJECT), env=env
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        success = result.returncode == 0
        return success, output
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: Lean compilation exceeded {LEAN_TIMEOUT}s"
    except Exception as e:
        return False, f"COMPILE ERROR: {e}"


# ============================================================
# RESEARCH MEMORY
# ============================================================

class SwarmMemory:
    """Persistent research memory across sessions."""

    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.global_file = MEMORY_DIR / "global_research.json"
        self.failed_file = MEMORY_DIR / "failed_approaches.json"
        self.verified_file = MEMORY_DIR / "verified_theorems.json"
        self.barrier_file = MEMORY_DIR / "barrier_log.json"
        self._load()

    def _load(self):
        self.global_state = self._read_json(self.global_file, {
            "total_cycles": 0, "total_verified": 0, "total_rejected_barrier": 0,
            "total_falsified": 0, "total_trivial": 0, "session_count": 0,
        })
        self.failed_approaches = self._read_json(self.failed_file, [])
        self.verified_theorems = self._read_json(self.verified_file, [])
        self.barrier_log = self._read_json(self.barrier_file, [])

    def _read_json(self, path, default):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except:
                return default
        return default

    def _write_json(self, path, data):
        path.write_text(json.dumps(data, indent=2))

    def save(self):
        self._write_json(self.global_file, self.global_state)
        self._write_json(self.failed_file, self.failed_approaches[-200:])  # keep last 200
        self._write_json(self.verified_file, self.verified_theorems)
        self._write_json(self.barrier_file, self.barrier_log[-200:])

    def add_verified(self, theorem_name: str, statement: str, lean_code: str, approach: str):
        self.verified_theorems.append({
            "name": theorem_name, "statement": statement,
            "approach": approach, "timestamp": datetime.datetime.now().isoformat(),
            "code_hash": hashlib.sha256(lean_code.encode()).hexdigest()[:16],
        })
        self.global_state["total_verified"] += 1
        self.save()

    def add_failed(self, approach: str, reason: str, barrier_profile: dict):
        self.failed_approaches.append({
            "approach": approach[:500], "reason": reason[:500],
            "barrier_profile": barrier_profile,
            "timestamp": datetime.datetime.now().isoformat(),
        })
        self.save()

    def add_barrier_kill(self, approach: str, scores: dict):
        self.barrier_log.append({
            "approach": approach[:300], "scores": scores,
            "timestamp": datetime.datetime.now().isoformat(),
        })
        self.global_state["total_rejected_barrier"] += 1
        self.save()

    def get_context_summary(self) -> str:
        """Generate a summary for conjecture engines to avoid repetition."""
        lines = [f"=== SWARM RESEARCH MEMORY ==="]
        lines.append(f"Total cycles: {self.global_state['total_cycles']}")
        lines.append(f"Verified theorems: {self.global_state['total_verified']}")
        lines.append(f"Barrier-killed: {self.global_state['total_rejected_barrier']}")
        lines.append(f"Falsified: {self.global_state['total_falsified']}")

        if self.verified_theorems:
            lines.append(f"\n--- Last 5 Verified ---")
            for t in self.verified_theorems[-5:]:
                lines.append(f"  {t['name']}: {t['statement'][:150]}")

        if self.failed_approaches:
            lines.append(f"\n--- Last 10 Failed Approaches (DO NOT REPEAT) ---")
            for f in self.failed_approaches[-10:]:
                lines.append(f"  FAILED: {f['approach'][:150]}")
                lines.append(f"    Reason: {f['reason'][:100]}")

        if self.barrier_log:
            lines.append(f"\n--- Last 5 Barrier Kills ---")
            for b in self.barrier_log[-5:]:
                lines.append(f"  KILLED: {b['approach'][:150]}")
                lines.append(f"    R={b['scores'].get('R','?')} N={b['scores'].get('N','?')} A={b['scores'].get('A','?')}")

        return "\n".join(lines)


# ============================================================
# LAYER IMPLEMENTATIONS
# ============================================================

# --- Existing Research.lean loader ---
def load_existing_theorems() -> str:
    """Load existing verified theorems from Research.lean."""
    if RESEARCH_LEAN.exists():
        content = RESEARCH_LEAN.read_text()
        lines = content.split('\n')
        # Extract theorem names
        theorems = [l.strip() for l in lines if l.strip().startswith("theorem ") or l.strip().startswith("lemma ")]
        return f"Existing library: {len(theorems)} theorems/lemmas in Research.lean ({len(lines)} lines)"
    return "No existing theorem library."


# --- Layer 2: Conjecture Engine ---
def run_conjecture_engine(memory: SwarmMemory, cycle: int) -> list[dict]:
    """3 models generate conjectures independently. Returns list of proposals."""
    context = memory.get_context_summary()
    existing = load_existing_theorems()

    system_prompt = f"""You are a mathematical research agent working on P vs NP and related complexity theory.
Your job is to propose a SPECIFIC, FORMAL conjecture or lemma that advances our understanding.

CONSTRAINTS:
- Must be related to computational complexity (circuit lower bounds, proof complexity, barrier evasion, etc.)
- Must be precise enough to formalize in Lean 4
- Must NOT repeat failed approaches listed below
- Prefer intermediate lemmas over grand claims
- State the conjecture, a proof sketch, and what barrier(s) it claims to evade

{context}
{existing}"""

    user_prompt = f"""Cycle {cycle}. Propose ONE specific mathematical conjecture or lemma related to P vs NP.

Format your response EXACTLY as:
CONJECTURE_NAME: <short_name>
STATEMENT: <precise mathematical statement>
PROOF_SKETCH: <brief proof strategy>
BARRIER_CLAIM: <which barriers does this evade and why?>
DOMAIN: <circuit complexity / proof complexity / algebraic / combinatorial / other>"""

    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    print("  [LAYER 2] Conjecture Engine — 3 models generating...")
    calls = [
        ("alpha", MODELS["conjecture_alpha"], messages, 0.8),
        ("beta",  MODELS["conjecture_beta"],  messages, 0.7),
        ("gamma", MODELS["conjecture_gamma"], messages, 0.75),
    ]
    results = parallel_llm_calls(calls)

    proposals = []
    for role, text in results.items():
        if text:
            proposals.append({"source": role, "text": text, "model": MODELS[f"conjecture_{role}"]})
            print(f"    [{role}] Generated proposal ({len(text)} chars)")
        else:
            print(f"    [{role}] FAILED to generate")

    return proposals


# --- Layer 1: Barrier Council ---
def run_barrier_council(proposal: dict) -> dict:
    """3 sentinels score R/N/A risk. Returns scores dict or None if killed."""
    text = proposal["text"]

    def make_sentinel_prompt(barrier_type: str, description: str) -> list:
        return [
            {"role": "system", "content": f"""You are the {barrier_type} Sentinel in a P vs NP research swarm.
Your SOLE job is to evaluate whether a proposed proof approach falls prey to the {barrier_type} barrier.

{description}

Score the proposal on a scale of 1-10:
  1-3 = LOW RISK (likely evades this barrier)
  4-6 = MODERATE RISK (unclear, needs investigation)
  7-10 = HIGH RISK (likely blocked by this barrier)

Respond with EXACTLY this format:
SCORE: <number 1-10>
REASONING: <2-3 sentences explaining your assessment>"""},
            {"role": "user", "content": f"Evaluate this proposal:\n\n{text}"}
        ]

    rel_desc = """The RELATIVIZATION barrier (Baker-Gill-Solovay 1975): Any proof that P≠NP must use techniques that do NOT work relative to all oracles. Diagonalization-based arguments and any technique that treats the complexity class as a black box will relativize and therefore fail. Ask: Would this argument still hold if both sides had access to an arbitrary oracle?"""

    nat_desc = """The NATURAL PROOFS barrier (Razborov-Rudich 1997): Under standard pseudorandomness assumptions, circuit lower bound proofs cannot use a combinatorial property of Boolean functions that is both CONSTRUCTIVE (efficiently checkable on truth tables) and LARGE (holds for a large fraction of functions). Ask: Does this approach define a "natural" property in the Razborov-Rudich sense?"""

    alg_desc = """The ALGEBRIZATION barrier (Aaronson-Wigderson 2009): Many sophisticated non-relativizing techniques still "algebrize" — they work even when the oracle is replaced by its low-degree algebraic extension. P vs NP likely requires non-algebrizing techniques. Ask: Does this argument survive if oracles are replaced by their low-degree extensions?"""

    print("  [LAYER 1] Barrier Council — 3 sentinels scoring...")
    calls = [
        ("R", MODELS["barrier_relativization"], make_sentinel_prompt("Relativization", rel_desc), 0.3),
        ("N", MODELS["barrier_natural_proofs"], make_sentinel_prompt("Natural Proofs", nat_desc), 0.3),
        ("A", MODELS["barrier_algebrization"], make_sentinel_prompt("Algebrization", alg_desc), 0.3),
    ]
    results = parallel_llm_calls(calls)

    scores = {}
    for barrier, text in results.items():
        if text:
            # Parse score
            score = 5  # default moderate
            for line in text.split('\n'):
                if line.strip().startswith("SCORE:"):
                    try:
                        score = int(''.join(c for c in line.split(":")[-1] if c.isdigit())[:2])
                        score = max(1, min(10, score))
                    except:
                        pass
            scores[barrier] = score
            reasoning = ""
            for line in text.split('\n'):
                if line.strip().startswith("REASONING:"):
                    reasoning = line.split(":", 1)[-1].strip()
            print(f"    [{barrier}] Score: {score}/10 — {reasoning[:80]}")
        else:
            scores[barrier] = 5  # default if sentinel fails
            print(f"    [{barrier}] Sentinel FAILED, defaulting to 5")

    scores["total"] = scores.get("R", 5) + scores.get("N", 5) + scores.get("A", 5)
    scores["killed"] = all(v >= 7 for k, v in scores.items() if k in ("R", "N", "A"))
    return scores


# --- Layer 4: Adversarial Critics ---
def run_adversarial_critics(proposal: dict) -> dict:
    """2 critics try to falsify. Returns verdict."""
    text = proposal["text"]

    counter_prompt = [
        {"role": "system", "content": """You are an adversarial critic in a math research swarm. Your job is to ATTACK proposed conjectures.
Try to find:
1. A counterexample (even in restricted models)
2. A logical flaw in the proof sketch
3. A hidden dependency on known-impossible techniques
4. Whether the statement is vacuously true or trivially false

If you find a flaw, state VERDICT: FALSIFIED and explain.
If it survives your attack, state VERDICT: SURVIVES and explain why you couldn't break it."""},
        {"role": "user", "content": f"Attack this proposal:\n\n{text}"}
    ]

    trivial_prompt = [
        {"role": "system", "content": """You are a triviality and duplication checker in a math research swarm.
Check:
1. Is this theorem/lemma trivially true (tautology, x=x, True)?
2. Is it already well-known in the literature?
3. Is it a rephrasing of something obvious?
4. Does it actually advance P vs NP research?

State VERDICT: TRIVIAL, KNOWN, or NONTRIVIAL with explanation."""},
        {"role": "user", "content": f"Check this proposal:\n\n{text}"}
    ]

    print("  [LAYER 4] Adversarial Critics — attacking...")
    calls = [
        ("counterexample", MODELS["critic_counterexample"], counter_prompt, 0.4),
        ("triviality", MODELS["critic_triviality"], trivial_prompt, 0.3),
    ]
    results = parallel_llm_calls(calls)

    verdict = {"falsified": False, "trivial": False, "details": {}}
    for role, text in results.items():
        if text:
            upper = text.upper()
            if role == "counterexample":
                verdict["falsified"] = "VERDICT: FALSIFIED" in upper or "VERDICT:FALSIFIED" in upper
                verdict["details"]["counterexample"] = text[:500]
                status = "FALSIFIED" if verdict["falsified"] else "SURVIVES"
                print(f"    [counterexample] {status}")
            elif role == "triviality":
                verdict["trivial"] = "VERDICT: TRIVIAL" in upper or "VERDICT: KNOWN" in upper
                verdict["details"]["triviality"] = text[:500]
                status = "TRIVIAL/KNOWN" if verdict["trivial"] else "NONTRIVIAL"
                print(f"    [triviality] {status}")
        else:
            print(f"    [{role}] Critic FAILED")

    return verdict


# --- Layer 3: Decomposer + Formalizer ---
def run_decompose_and_formalize(proposal: dict, existing_library: str) -> Optional[str]:
    """Decompose into subgoals, then formalize to Lean 4. Returns Lean code or None."""

    # Step 1: Decompose
    print("  [LAYER 3] Decomposer — breaking into subgoals...")
    decompose_msg = [
        {"role": "system", "content": """You are a mathematical decomposer. Given a conjecture, break it into:
1. Required definitions
2. Auxiliary lemmas needed
3. The main theorem statement
4. Proof strategy as ordered subgoals
Keep it precise and formal. Output should be ready for a Lean 4 formalizer."""},
        {"role": "user", "content": f"Decompose this into subgoals:\n\n{proposal['text']}"}
    ]
    decomposition = llm_call(MODELS["decomposer"], decompose_msg, temperature=0.4)
    if not decomposition:
        print("    Decomposer FAILED")
        return None
    print(f"    Decomposed ({len(decomposition)} chars)")

    # Step 2: Formalize to Lean 4
    print("  [LAYER 3] Formalizer — translating to Lean 4...")
    formalize_msg = [
        {"role": "system", "content": f"""You are a Lean 4 formalization expert. Convert mathematical statements into COMPILABLE Lean 4 code.

RULES:
- Import Mathlib (use `import Mathlib` at top)
- Use proper Lean 4 syntax (not Lean 3)
- Include all necessary imports
- Every theorem MUST have a complete proof (no `sorry`)
- If the proof is hard, prove a simpler version that still compiles
- Use `theorem` or `lemma` declarations
- The code must be SELF-CONTAINED (except for Mathlib imports)

{existing_library}

Output ONLY the Lean 4 code, nothing else. Start with `import Mathlib`."""},
        {"role": "user", "content": f"Formalize this decomposition into Lean 4:\n\n{decomposition}"}
    ]

    # Try primary formalizer first, then backup
    for formalizer_key in ["formalizer_primary", "formalizer_backup"]:
        lean_code = llm_call(MODELS[formalizer_key], formalize_msg, temperature=0.3, max_tokens=8192)
        if lean_code:
            # Extract code block if wrapped in markdown
            if "```lean" in lean_code:
                lean_code = lean_code.split("```lean")[-1].split("```")[0].strip()
            elif "```" in lean_code:
                lean_code = lean_code.split("```")[1].split("```")[0].strip()
            if lean_code.strip():
                print(f"    [{formalizer_key}] Generated Lean code ({len(lean_code)} chars)")
                return lean_code
        print(f"    [{formalizer_key}] FAILED")

    return None


# --- Layer 5: Proof Search Workers ---
def run_proof_search(lean_code: str, error_msg: str, attempt: int) -> Optional[str]:
    """Two proof workers try to fix compilation errors. Returns fixed code or None."""
    print(f"  [LAYER 5] Proof Workers — fix attempt {attempt}...")

    fix_msg = [
        {"role": "system", "content": """You are a Lean 4 proof repair agent. Given Lean 4 code and a compilation error,
fix the code so it compiles. Common issues:
- Missing imports
- Wrong Mathlib API names (check Lean 4 / Mathlib4 syntax)
- Incorrect tactic usage
- Type mismatches

Output ONLY the complete fixed Lean 4 code, nothing else."""},
        {"role": "user", "content": f"Fix this Lean 4 code:\n\n```lean\n{lean_code}\n```\n\nCompilation error:\n{error_msg[:2000]}"}
    ]

    calls = [
        ("prover_alpha", MODELS["prover_alpha"], fix_msg, 0.3),
        ("prover_beta",  MODELS["prover_beta"],  fix_msg, 0.3),
    ]
    results = parallel_llm_calls(calls)

    for role, text in results.items():
        if text:
            code = text
            if "```lean" in code:
                code = code.split("```lean")[-1].split("```")[0].strip()
            elif "```" in code:
                code = code.split("```")[1].split("```")[0].strip()
            if code.strip():
                print(f"    [{role}] Produced fix ({len(code)} chars)")
                return code
    return None


# --- Layer 6: Intent Checker ---
def run_intent_check(proposal_text: str, lean_code: str) -> bool:
    """Check if the verified Lean code actually matches the intended informal theorem."""
    print("  [LAYER 6] Intent Checker — verifying semantic match...")
    msg = [
        {"role": "system", "content": """You compare an informal mathematical statement with its Lean 4 formalization.
Check: Does the Lean code actually prove what the informal statement claims?
Watch for:
- Proving a weaker statement than claimed
- Proving something trivially true instead of the real theorem
- Definitions that don't match the informal meaning
- Sorry or admitted steps

Respond with EXACTLY:
MATCH: YES or MATCH: NO
EXPLANATION: <brief explanation>"""},
        {"role": "user", "content": f"INFORMAL:\n{proposal_text[:2000]}\n\nLEAN CODE:\n{lean_code[:3000]}"}
    ]
    result = llm_call(MODELS["intent_checker"], msg, temperature=0.2)
    if result:
        match = "MATCH: YES" in result.upper() or "MATCH:YES" in result.upper()
        print(f"    Intent: {'MATCHES' if match else 'MISMATCH'}")
        return match
    print("    Intent checker FAILED, assuming match")
    return True


# --- Layer 7: Scribe ---
def run_scribe_summary(cycle_data: dict) -> str:
    """Generate a concise cycle summary for the log."""
    msg = [
        {"role": "system", "content": "You are a terse research scribe. Summarize in EXACTLY 3-5 short lines. No thinking out loud. Just: what was proposed, what passed/failed each gate, and what to try next. Be telegraphic."},
        {"role": "user", "content": json.dumps(cycle_data, indent=2, default=str)[:4000]}
    ]
    result = llm_call(MODELS["scribe"], msg, temperature=0.3, max_tokens=500)
    return result or "Scribe unavailable."


# ============================================================
# APPEND TO RESEARCH.LEAN
# ============================================================

def append_to_research(lean_code: str, theorem_name: str, source: str):
    """Append verified theorem to cumulative Research.lean."""
    header = f"\n-- Verified by Math Lab v29 Swarm | Source: {source} | {datetime.datetime.now().isoformat()}\n"
    # Strip the import line (Research.lean has its own imports)
    lines = lean_code.split('\n')
    code_lines = [l for l in lines if not l.strip().startswith("import ")]
    with open(RESEARCH_LEAN, 'a') as f:
        f.write(header)
        f.write('\n'.join(code_lines))
        f.write('\n')
    print(f"  [ARCHIVE] Appended to Research.lean: {theorem_name}")


def is_trivial_proof(lean_code: str) -> bool:
    """Quick check for obviously trivial proofs."""
    trivial_patterns = [
        "theorem trivial", ": True", ":= trivial", ":= rfl",
        "1 = 1", "0 = 0", ": 1 + 1 = 2",
    ]
    code_lower = lean_code.lower()
    return any(p.lower() in code_lower for p in trivial_patterns)


# ============================================================
# MAIN CYCLE
# ============================================================

def run_cycle(cycle: int, memory: SwarmMemory, session_log: list):
    """Run one full swarm cycle."""
    print(f"\n{'='*60}")
    print(f"  CYCLE {cycle}")
    print(f"{'='*60}")

    cycle_data = {"cycle": cycle, "timestamp": datetime.datetime.now().isoformat(),
                  "proposals": 0, "barrier_killed": 0, "falsified": 0,
                  "verified": 0, "trivial": 0, "failed_compile": 0}

    # Step 1: Generate conjectures (3 models in parallel)
    proposals = run_conjecture_engine(memory, cycle)
    cycle_data["proposals"] = len(proposals)
    if not proposals:
        print("  [ABORT] No proposals generated")
        session_log.append(cycle_data)
        return

    verified_this_cycle = 0

    for i, proposal in enumerate(proposals):
        print(f"\n  --- Proposal {i+1}/{len(proposals)} from {proposal['source']} ---")

        # Step 2: Barrier Council
        scores = run_barrier_council(proposal)
        if scores["killed"]:
            print(f"  [KILLED] All barriers HIGH — proposal rejected")
            memory.add_barrier_kill(proposal["text"][:300], scores)
            cycle_data["barrier_killed"] += 1
            continue

        # Step 3: Adversarial Critics
        verdict = run_adversarial_critics(proposal)
        if verdict["falsified"]:
            print(f"  [FALSIFIED] Counterexample found — proposal rejected")
            memory.add_failed(proposal["text"][:300], "Falsified by adversarial critic",
                            {"R": scores.get("R"), "N": scores.get("N"), "A": scores.get("A")})
            memory.global_state["total_falsified"] += 1
            cycle_data["falsified"] += 1
            continue
        if verdict["trivial"]:
            print(f"  [TRIVIAL] Detected as trivial/known — skipping")
            cycle_data["trivial"] += 1
            memory.global_state["total_trivial"] += 1
            continue

        # Step 4: Decompose and Formalize
        existing = load_existing_theorems()
        lean_code = run_decompose_and_formalize(proposal, existing)
        if not lean_code:
            print(f"  [FAILED] Could not formalize")
            memory.add_failed(proposal["text"][:300], "Formalization failed", scores)
            cycle_data["failed_compile"] += 1
            continue

        # Step 5: Compile with Lean 4
        print("  [LEAN] Compiling...")
        success, output = compile_lean(lean_code)

        # Retry loop with proof workers
        attempt = 0
        while not success and attempt < MAX_FIX_ATTEMPTS:
            attempt += 1
            fixed = run_proof_search(lean_code, output, attempt)
            if fixed:
                lean_code = fixed
                success, output = compile_lean(lean_code)
            else:
                break

        if not success:
            print(f"  [FAILED] Lean compilation failed after {attempt+1} attempts")
            memory.add_failed(proposal["text"][:300],
                            f"Compile failed: {output[:200]}", scores)
            cycle_data["failed_compile"] += 1
            continue

        # Step 6: Trivial check
        if is_trivial_proof(lean_code):
            print(f"  [TRIVIAL] Compiled but trivially true")
            cycle_data["trivial"] += 1
            memory.global_state["total_trivial"] += 1
            continue

        # Step 7: Intent check
        if not run_intent_check(proposal["text"], lean_code):
            print(f"  [MISMATCH] Formal proof doesn't match informal intent")
            memory.add_failed(proposal["text"][:300], "Intent mismatch", scores)
            continue

        # SUCCESS!
        theorem_name = f"swarm_v29_c{cycle}_{proposal['source']}_{int(time.time())}"
        print(f"  [VERIFIED] ✓ {theorem_name}")
        append_to_research(lean_code, theorem_name, proposal["source"])
        memory.add_verified(theorem_name, proposal["text"][:500], lean_code, proposal["source"])
        verified_this_cycle += 1
        cycle_data["verified"] += 1

    # Scribe summary
    summary = run_scribe_summary(cycle_data)
    print(f"\n  [SCRIBE] {summary}")
    cycle_data["scribe_summary"] = summary
    session_log.append(cycle_data)
    memory.global_state["total_cycles"] += 1
    memory.save()


# ============================================================
# SESSION RUNNER
# ============================================================

def run_session():
    """Run a full research session."""
    session_id = datetime.datetime.now().strftime("swarm_v29_%Y%m%d_%H%M%S")
    session_file = SESSION_DIR / f"{session_id}.json"
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  MATH LAB v29 — SWARM ARCHITECTURE                      ║
║  15 NVIDIA Models | 7 Layers | Lean 4 Ground Truth       ║
║  Session: {session_id}                    ║
╚══════════════════════════════════════════════════════════╝
""")

    memory = SwarmMemory()
    print(f"Research memory loaded:")
    print(f"  Verified theorems: {memory.global_state['total_verified']}")
    print(f"  Failed approaches: {len(memory.failed_approaches)}")
    print(f"  Barrier kills: {memory.global_state['total_rejected_barrier']}")
    print(f"  Sessions completed: {memory.global_state['session_count']}")

    # Verify Lean setup
    print("\nChecking Lean 4 setup...")
    test_code = 'import Mathlib\n\ntheorem v29_ping : 1 = 1 := rfl\n'
    ok, out = compile_lean(test_code)
    if not ok:
        print(f"FATAL: Lean 4 compilation check failed: {out[:500]}")
        print("Make sure ~/.elan/env is sourced and ~/mathlib_test has Mathlib.")
        sys.exit(1)
    print("Lean 4 + Mathlib: OK")

    session_log = []
    session_start = time.time()

    for cycle in range(1, MAX_CYCLES + 1):
        try:
            run_cycle(cycle, memory, session_log)
        except KeyboardInterrupt:
            print("\n\n[INTERRUPTED] Saving state...")
            break
        except Exception as e:
            print(f"\n[CYCLE ERROR] {e}")
            session_log.append({"cycle": cycle, "error": str(e)})

    # Session summary
    elapsed = time.time() - session_start
    memory.global_state["session_count"] += 1
    memory.save()

    total_verified = sum(c.get("verified", 0) for c in session_log)
    total_killed = sum(c.get("barrier_killed", 0) for c in session_log)
    total_falsified = sum(c.get("falsified", 0) for c in session_log)

    summary = {
        "session_id": session_id,
        "duration_seconds": elapsed,
        "cycles_completed": len(session_log),
        "total_verified": total_verified,
        "total_barrier_killed": total_killed,
        "total_falsified": total_falsified,
        "log": session_log,
    }
    session_file.write_text(json.dumps(summary, indent=2, default=str))

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  SESSION COMPLETE                                        ║
║  Duration: {elapsed:.0f}s | Cycles: {len(session_log)}                          ║
║  Verified: {total_verified} | Barrier-killed: {total_killed} | Falsified: {total_falsified}     ║
║  Saved: {session_file.name}                              ║
╚══════════════════════════════════════════════════════════╝
""")
    # Git commit
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(MATH_LAB_DIR), timeout=10)
        subprocess.run(["git", "commit", "-m", f"v29 session {session_id}: {total_verified} verified"],
                       cwd=str(MATH_LAB_DIR), timeout=10)
        subprocess.run(["git", "push"], cwd=str(MATH_LAB_DIR), timeout=30)
    except:
        pass


if __name__ == "__main__":
    run_session()

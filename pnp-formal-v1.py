#!/usr/bin/env python3
"""
P=NP Formal Verification Research Orchestrator v1.0
====================================================
Architecture: Proposer (Nemotron Ultra 253B) → Formalizer (Llama 405B) → Lean 4 compiler → feedback loop

This orchestrator builds a library of formally verified lemmas in computational
complexity theory using Lean 4 + Mathlib. It starts with basic provable facts
(arithmetic, list properties, polynomial closure) and gradually builds toward
more complex results related to P vs NP.

Each turn:
  1. PROPOSER generates a theorem statement + proof sketch (natural language)
  2. FORMALIZER translates it into a complete Lean 4 file
  3. VERIFIER compiles with `lake build` — ground truth
  4. On failure: up to 3 fix attempts per turn with error feedback
  5. On success: log the verified proof and advance

Author: Metatron Research Lab
"""

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

HUNTER_API_KEY = "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"
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Models
PROPOSER_MODEL = "nvidia/llama-3.1-nemotron-ultra-253b-v1"   # Reasoning model
FORMALIZER_MODEL = "meta/llama-3.1-405b-instruct"             # Code generation
HELPER_MODEL = "meta/llama-3.3-70b-instruct"                  # Fast helper

# Orchestrator settings
MAX_TURNS = 20
MAX_FIX_ATTEMPTS = 3
REQUEST_TIMEOUT = 300  # seconds — reasoning models can be slow

# Paths
MATHLIB_DIR = os.path.expanduser("~/mathlib_test")
LEAN_FILE = os.path.join(MATHLIB_DIR, "MyProofs", "Research.lean")
SESSION_DIR = os.path.expanduser("~/projects/math-lab/sessions")
ELAN_ENV = os.path.expanduser("~/.elan/env")

# Session files (timestamped)
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(SESSION_DIR, f"formal_v1_{TIMESTAMP}.txt")
VERIFIED_FILE = os.path.join(SESSION_DIR, f"formal_v1_VERIFIED_{TIMESTAMP}.md")

# Degeneration guard keywords
DEGEN_KEYWORDS = [
    "sorry", "admit", "axiom", "native_decide",
    "trustMe", "unsound", "Lean.Elab.Term.reportUnsolvedGoals"
]

# SSL context (permissive for API calls)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ============================================================================
# RESEARCH CONTEXT — Seeds the proposer with the research direction
# ============================================================================

RESEARCH_CONTEXT = """You are a mathematical research assistant building a library of formally
verified lemmas in computational complexity theory using Lean 4 and Mathlib.

GOAL: Build foundational lemmas that formalize concepts related to P vs NP.
We are NOT trying to prove P=NP or P≠NP directly. Instead, we formalize
known results and build helper infrastructure.

PROGRESSION STRATEGY (follow this order):
1. PHASE 1 — Basic Math: Simple Nat/List/Set lemmas that compile easily.
   Examples: commutativity, associativity, list length properties, set operations.
2. PHASE 2 — Functions & Complexity Basics: Polynomial composition, function
   growth, basic order theory, decidability of simple predicates.
3. PHASE 3 — Computation Models: Formalize simple computation concepts —
   decidable languages, closure under complement/union/intersection.
4. PHASE 4 — Reductions: Formalize polynomial-time reductions (as functions
   with polynomial bounds), prove reduction composition is polynomial.
5. PHASE 5 — Complexity Classes: Define P and NP in Lean 4 using Mathlib
   structures, prove basic containment results.

IMPORTANT CONSTRAINTS:
- Output ONE theorem per turn with a complete proof sketch
- Keep it SIMPLE and PROVABLE — Lean 4 compilation is the judge
- Use standard Mathlib tactics: simp, omega, ring, exact, apply, intro, decide, norm_num
- Avoid sorry/admit/axiom — proofs must be complete
- Build on previously verified results when possible
- State the theorem in natural language FIRST, then give the proof sketch
"""

# ============================================================================
# LOGGING
# ============================================================================

def log(msg: str, also_print: bool = True):
    """Append a message to the log file and optionally print it."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")
    if also_print:
        print(entry)


def log_verified(turn: int, theorem_nl: str, lean_code: str):
    """Append a verified theorem to the verified proofs markdown file."""
    with open(VERIFIED_FILE, "a") as f:
        f.write(f"\n## Turn {turn} — Verified ✓\n\n")
        f.write(f"**Natural Language:**\n{theorem_nl}\n\n")
        f.write(f"**Lean 4 Proof:**\n```lean\n{lean_code}\n```\n\n")
        f.write(f"---\n")


# ============================================================================
# API CALLS
# ============================================================================

def call_api(model: str, messages: list, temperature: float = 0.6,
             max_tokens: int = 4096) -> dict:
    """Call the NVIDIA API with the given model and messages.
    
    Returns dict with 'content' and optionally 'reasoning_content' fields.
    Handles the Nemotron Ultra response format where content may be null
    and reasoning is in reasoning_content.
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.95,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {HUNTER_API_KEY}",
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=SSL_CTX) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else "no body"
        log(f"  API HTTP error {e.code}: {error_body[:500]}")
        raise
    except Exception as e:
        log(f"  API error: {e}")
        raise

    choice = body.get("choices", [{}])[0]
    message = choice.get("message", {})

    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""

    # For Nemotron Ultra: if content is empty/null, use reasoning_content
    if not content.strip() and reasoning.strip():
        content = reasoning

    return {"content": content, "reasoning_content": reasoning}


# ============================================================================
# PROPOSER — Generates theorem statements + proof sketches
# ============================================================================

def proposer_prompt(turn: int, verified_so_far: list, last_error: str = None,
                    last_lean_code: str = None) -> list:
    """Build the proposer prompt with research context and feedback."""
    
    # Build context about what's been verified
    verified_summary = ""
    if verified_so_far:
        verified_summary = "\n\nPREVIOUSLY VERIFIED THEOREMS:\n"
        for i, v in enumerate(verified_so_far, 1):
            verified_summary += f"  {i}. {v['summary']}\n"
    
    # Build error feedback if any
    error_feedback = ""
    if last_error:
        error_feedback = f"""

PREVIOUS ATTEMPT FAILED with Lean 4 compiler error:
```
{last_error[:2000]}
```

The Lean code that failed was:
```lean
{(last_lean_code or 'N/A')[:2000]}
```

Please propose a DIFFERENT, SIMPLER theorem that avoids the issues above.
If the error was about missing imports or tactics, suggest alternatives.
"""

    phase = "PHASE 1 (Basic Math)" if turn <= 5 else \
            "PHASE 2 (Functions & Complexity)" if turn <= 10 else \
            "PHASE 3 (Computation Models)" if turn <= 15 else \
            "PHASE 4+ (Reductions & Complexity)"

    system_msg = RESEARCH_CONTEXT + verified_summary + error_feedback

    user_msg = f"""Turn {turn}/{MAX_TURNS}. Current phase: {phase}.

Propose ONE theorem to formalize in Lean 4 with Mathlib.

Requirements:
- State the theorem in natural language
- Provide a proof sketch
- The theorem should be NEW (not duplicate of previously verified ones)
- It should be PROVABLE with standard Lean 4/Mathlib tactics
- Keep it at the appropriate complexity level for the current phase
- Format your response as:

THEOREM: <natural language statement>

PROOF SKETCH: <informal proof approach>

LEAN HINT: <suggested Lean 4 structure — what imports, what tactics>

DIFFICULTY: <easy/medium/hard>"""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def call_proposer(turn: int, verified_so_far: list, last_error: str = None,
                  last_lean_code: str = None) -> str:
    """Call the proposer model to generate a theorem proposal."""
    log(f"  [PROPOSER] Calling {PROPOSER_MODEL}...")
    messages = proposer_prompt(turn, verified_so_far, last_error, last_lean_code)
    
    result = call_api(PROPOSER_MODEL, messages, temperature=0.7, max_tokens=4096)
    proposal = result["content"]
    
    log(f"  [PROPOSER] Got proposal ({len(proposal)} chars)")
    log(f"  [PROPOSER] Preview: {proposal[:200]}...", also_print=False)
    
    return proposal


# ============================================================================
# FORMALIZER — Translates natural language to Lean 4 code
# ============================================================================

FORMALIZER_SYSTEM = """You are an expert Lean 4 programmer with deep knowledge of Mathlib.
Your task: translate a mathematical theorem and proof sketch into a COMPLETE,
COMPILABLE Lean 4 file.

CRITICAL RULES:
1. The file MUST start with: import Mathlib
2. Use Lean 4 syntax (NOT Lean 3)
3. Use standard Mathlib tactics: simp, omega, ring, exact, apply, intro, cases, induction, decide, norm_num, linarith, positivity, gcongr, rel, aesop, tauto, trivial, rfl, ext, funext, congr
4. Do NOT use sorry, admit, or axiom
5. Do NOT use native_decide (it can hang)
6. Keep proofs CONCRETE — avoid overly abstract constructions
7. If unsure about a tactic, use `simp` or `omega` as fallbacks
8. Output ONLY the Lean 4 code, nothing else — no markdown fences, no explanation
9. The ENTIRE output should be valid Lean 4 that can be saved directly to a .lean file
10. For simple arithmetic: omega handles linear arithmetic over Nat/Int
11. For algebraic identities: ring works well
12. For set theory: use Set.ext, Set.mem_union, etc.
13. Start simple — a correct simple proof is better than a broken complex one

Example of a correct, simple Lean 4 file:
import Mathlib

theorem my_add_comm (a b : Nat) : a + b = b + a := by
  omega

theorem my_list_length_nil : ([] : List Nat).length = 0 := by
  simp
"""


def formalizer_prompt(proposal: str, fix_error: str = None,
                      prev_code: str = None) -> list:
    """Build the formalizer prompt."""
    
    user_msg = f"""Translate this theorem into a complete Lean 4 file:

{proposal}
"""
    
    if fix_error and prev_code:
        user_msg = f"""The previous Lean 4 code FAILED to compile. Fix it.

PREVIOUS CODE:
```lean
{prev_code}
```

COMPILER ERROR:
```
{fix_error[:3000]}
```

Please output the FIXED complete Lean 4 file. Only output Lean 4 code, nothing else.
Common fixes:
- If "unknown identifier": check the import or use a different approach
- If "type mismatch": fix the types
- If tactic fails: try a different tactic (simp, omega, ring, decide, norm_num)
- If too complex: simplify the theorem
"""

    return [
        {"role": "system", "content": FORMALIZER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]


def call_formalizer(proposal: str, fix_error: str = None,
                    prev_code: str = None) -> str:
    """Call the formalizer model to generate Lean 4 code."""
    log(f"  [FORMALIZER] Calling {FORMALIZER_MODEL}...")
    messages = formalizer_prompt(proposal, fix_error, prev_code)
    
    result = call_api(FORMALIZER_MODEL, messages, temperature=0.3, max_tokens=4096)
    code = result["content"]
    
    # Clean up: remove markdown fences if present
    code = re.sub(r'^```\w*\n', '', code, flags=re.MULTILINE)
    code = re.sub(r'\n```\s*$', '', code, flags=re.MULTILINE)
    code = code.strip()
    
    # Ensure it starts with import
    if not code.startswith("import"):
        # Try to find the import line and trim before it
        match = re.search(r'^(import\s+\S+)', code, re.MULTILINE)
        if match:
            code = code[match.start():]
        else:
            code = "import Mathlib\n\n" + code
    
    log(f"  [FORMALIZER] Got Lean code ({len(code)} chars)")
    return code


# ============================================================================
# DEGENERATION GUARD
# ============================================================================

def check_degeneration(lean_code: str) -> str | None:
    """Check if the Lean code contains degenerate patterns.
    
    Returns an error message if degenerate, None if clean.
    """
    code_lower = lean_code.lower()
    
    for kw in DEGEN_KEYWORDS:
        if kw.lower() in code_lower:
            # Allow "sorry" only in comments
            # Check if all occurrences are in comments
            lines = lean_code.split("\n")
            for line in lines:
                stripped = line.split("--")[0]  # Remove inline comments
                if kw.lower() in stripped.lower():
                    return f"Degeneration detected: '{kw}' found in code (not in comment)"
    
    # Check for empty theorems (just 'by' with no tactics)
    if re.search(r':=\s*by\s*$', lean_code, re.MULTILINE):
        return "Degeneration detected: empty proof body"
    
    return None


# ============================================================================
# VERIFIER — Lean 4 compiler
# ============================================================================

def verify_lean(lean_code: str) -> tuple[bool, str]:
    """Write the Lean code to file and compile it.
    
    Returns (success: bool, output: str).
    """
    # Degeneration check first
    degen = check_degeneration(lean_code)
    if degen:
        return False, degen
    
    # Write the file
    os.makedirs(os.path.dirname(LEAN_FILE), exist_ok=True)
    with open(LEAN_FILE, "w") as f:
        f.write(lean_code)
    
    log(f"  [VERIFIER] Written to {LEAN_FILE}, compiling...")
    
    # Compile with lake build
    cmd = f"cd {MATHLIB_DIR} && source {ELAN_ENV} && lake build MyProofs 2>&1"
    
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout for compilation
            cwd=MATHLIB_DIR,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        
        # Check for success
        # lake build returns 0 on success, non-zero on failure
        if result.returncode == 0 and "error" not in output.lower():
            log(f"  [VERIFIER] ✓ COMPILATION SUCCESSFUL")
            return True, output
        else:
            # Extract the most relevant error
            error_lines = [l for l in output.split("\n") if "error" in l.lower() or ":" in l]
            error_summary = "\n".join(error_lines[:20]) if error_lines else output[:2000]
            log(f"  [VERIFIER] ✗ COMPILATION FAILED")
            log(f"  [VERIFIER] Error: {error_summary[:300]}", also_print=False)
            return False, output
            
    except subprocess.TimeoutExpired:
        log(f"  [VERIFIER] ✗ COMPILATION TIMED OUT (600s)")
        return False, "Compilation timed out after 600 seconds"
    except Exception as e:
        log(f"  [VERIFIER] ✗ Error running compiler: {e}")
        return False, str(e)


# ============================================================================
# MAIN ORCHESTRATOR LOOP
# ============================================================================

def run_orchestrator():
    """Main orchestration loop: propose → formalize → verify → feedback."""
    
    print("=" * 70)
    print("P=NP FORMAL VERIFICATION RESEARCH ORCHESTRATOR v1.0")
    print("=" * 70)
    print(f"Session: {TIMESTAMP}")
    print(f"Log: {LOG_FILE}")
    print(f"Verified proofs: {VERIFIED_FILE}")
    print(f"Proposer: {PROPOSER_MODEL}")
    print(f"Formalizer: {FORMALIZER_MODEL}")
    print(f"Max turns: {MAX_TURNS}, Fix attempts per turn: {MAX_FIX_ATTEMPTS}")
    print("=" * 70)
    
    # Initialize log
    log("Session started")
    log(f"Models: proposer={PROPOSER_MODEL}, formalizer={FORMALIZER_MODEL}")
    
    # Initialize verified proofs file
    with open(VERIFIED_FILE, "w") as f:
        f.write(f"# Formally Verified Theorems — Session {TIMESTAMP}\n\n")
        f.write(f"Generated by P=NP Formal Verification Orchestrator v1.0\n\n")
        f.write(f"---\n")
    
    # Track state
    verified_theorems = []  # List of {"summary": str, "lean_code": str}
    total_verified = 0
    total_failed = 0
    consecutive_failures = 0
    
    for turn in range(1, MAX_TURNS + 1):
        print(f"\n{'─' * 70}")
        print(f"TURN {turn}/{MAX_TURNS}")
        print(f"{'─' * 70}")
        log(f"\n=== TURN {turn}/{MAX_TURNS} ===")
        
        # Check for too many consecutive failures
        if consecutive_failures >= 5:
            log("WARNING: 5 consecutive failures — resetting to simpler theorems")
            # Clear error context to let proposer start fresh
            consecutive_failures = 0
        
        # ---- STEP 1: PROPOSE ----
        try:
            proposal = call_proposer(turn, verified_theorems)
        except Exception as e:
            log(f"  Proposer failed: {e}")
            total_failed += 1
            consecutive_failures += 1
            time.sleep(5)
            continue
        
        log(f"\n  PROPOSAL:\n{proposal[:500]}", also_print=False)
        
        # ---- STEP 2+3: FORMALIZE + VERIFY (with fix attempts) ----
        success = False
        lean_code = None
        last_error = None
        
        for attempt in range(MAX_FIX_ATTEMPTS + 1):
            attempt_label = "initial" if attempt == 0 else f"fix #{attempt}"
            log(f"  Attempt: {attempt_label}")
            
            # Formalize
            try:
                if attempt == 0:
                    lean_code = call_formalizer(proposal)
                else:
                    lean_code = call_formalizer(proposal, fix_error=last_error,
                                                prev_code=lean_code)
            except Exception as e:
                log(f"  Formalizer failed: {e}")
                time.sleep(5)
                continue
            
            log(f"\n  LEAN CODE:\n{lean_code[:500]}", also_print=False)
            
            # Verify
            ok, output = verify_lean(lean_code)
            
            if ok:
                success = True
                break
            else:
                last_error = output
                log(f"  Compilation failed (attempt {attempt_label})")
                if attempt < MAX_FIX_ATTEMPTS:
                    log(f"  Will retry with error feedback...")
                    time.sleep(2)
        
        # ---- STEP 4: RECORD RESULT ----
        if success:
            total_verified += 1
            consecutive_failures = 0
            
            # Extract a summary from the proposal
            summary_match = re.search(r'THEOREM:\s*(.+?)(?:\n|PROOF)', proposal, re.DOTALL)
            summary = summary_match.group(1).strip()[:200] if summary_match else proposal[:200]
            
            verified_theorems.append({"summary": summary, "lean_code": lean_code})
            log_verified(turn, proposal, lean_code)
            
            print(f"  ✓ VERIFIED — Total: {total_verified}")
            log(f"  ✓ VERIFIED (total: {total_verified})")
        else:
            total_failed += 1
            consecutive_failures += 1
            print(f"  ✗ FAILED after {MAX_FIX_ATTEMPTS + 1} attempts")
            log(f"  ✗ FAILED after all attempts")
            
            # Log the failure details
            log(f"  Last error: {(last_error or 'unknown')[:500]}", also_print=False)
        
        # Brief pause between turns
        time.sleep(3)
    
    # ---- SESSION SUMMARY ----
    print(f"\n{'=' * 70}")
    print(f"SESSION COMPLETE")
    print(f"{'=' * 70}")
    print(f"Total turns: {MAX_TURNS}")
    print(f"Verified: {total_verified}")
    print(f"Failed: {total_failed}")
    print(f"Success rate: {total_verified / MAX_TURNS * 100:.1f}%")
    print(f"Verified proofs: {VERIFIED_FILE}")
    print(f"Full log: {LOG_FILE}")
    
    log(f"\nSESSION SUMMARY: {total_verified} verified, {total_failed} failed, "
        f"{total_verified / max(1, MAX_TURNS) * 100:.1f}% success rate")
    
    # List verified theorems
    if verified_theorems:
        print(f"\nVERIFIED THEOREMS:")
        for i, v in enumerate(verified_theorems, 1):
            print(f"  {i}. {v['summary'][:100]}")
    
    return total_verified


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    os.makedirs(SESSION_DIR, exist_ok=True)
    
    try:
        count = run_orchestrator()
        sys.exit(0 if count > 0 else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        log("Session interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        log(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

#!/usr/bin/env python3
"""
P=NP Formal Verification Research Orchestrator v2.0
====================================================
Architecture: Proposer (Nemotron Ultra 253B) -> Formalizer (Llama 405B) -> Lean 4 compiler -> feedback loop

Improvements over v1:
- Cross-session memory: loads all prior verified theorems on startup
- Cumulative Lean library: proven theorems accumulate, later turns can reference them
- Stronger dedup: keyword overlap detection against prior work
- Trivial proof detection: flags tautologies vs substantive proofs
- Adaptive phases: advance based on progress, not turn count
- Git integration: auto-commits each verified theorem

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
from collections import Counter

# ============================================================================
# CONFIGURATION
# ============================================================================

import base64 as _b64
_key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".api_key_b64")
with open(_key_file) as _kf:
    HUNTER_API_KEY = _b64.b64decode(_kf.read().strip()).decode()
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Models
PROPOSER_MODEL = "nvidia/llama-3.1-nemotron-ultra-253b-v1"
FORMALIZER_MODEL = "meta/llama-3.1-405b-instruct"
HELPER_MODEL = "meta/llama-3.3-70b-instruct"

# Orchestrator settings
MAX_TURNS = 25
MAX_FIX_ATTEMPTS = 3
REQUEST_TIMEOUT = 300

# Paths
MATHLIB_DIR = os.path.expanduser("~/mathlib_test")
CUMULATIVE_LEAN = os.path.join(MATHLIB_DIR, "MyProofs", "Research.lean")
ATTEMPT_LEAN = os.path.join(MATHLIB_DIR, "MyProofs", "Attempt.lean")
SESSION_DIR = os.path.expanduser("~/projects/math-lab/sessions")
ELAN_ENV = os.path.expanduser("~/.elan/env")
PROJECT_DIR = os.path.expanduser("~/projects/math-lab")

# Session files
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(SESSION_DIR, f"formal_v2_{TIMESTAMP}.txt")
VERIFIED_FILE = os.path.join(SESSION_DIR, f"formal_v2_VERIFIED_{TIMESTAMP}.md")
SUMMARY_JSON = os.path.join(SESSION_DIR, f"formal_v2_SUMMARY_{TIMESTAMP}.json")

# Degeneration guard keywords
DEGEN_KEYWORDS = [
    "sorry", "admit", "axiom", "native_decide",
    "trustMe", "unsound", "Lean.Elab.Term.reportUnsolvedGoals"
]

# Trivial proof patterns
TRIVIAL_PATTERNS = [
    r":=\s*by\s*(trivial|rfl|simp)\s*$",
    r"\u2200\s*\w+,\s*True",
    r"\w+\s*=\s*\w+\s*:=\s*by\s*rfl",
    r":=\s*by\s*tauto\s*$",
]

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Phase thresholds — advance after N verified in current phase
PHASE_ADVANCE_THRESHOLD = 3

# ============================================================================
# CROSS-SESSION MEMORY
# ============================================================================

def load_prior_verified() -> list:
    """Load all previously verified theorems from prior session files."""
    prior = []
    session_dir = Path(SESSION_DIR)
    if not session_dir.exists():
        return prior
    
    for vfile in sorted(session_dir.glob("formal_*_VERIFIED_*.md")):
        try:
            content = vfile.read_text()
            # Parse each theorem block
            blocks = re.split(r"## Turn \d+", content)
            for block in blocks[1:]:  # Skip header
                # Extract natural language
                nl_match = re.search(r"\*\*Natural Language:\*\*\n(.+?)\n\n\*\*Lean", block, re.DOTALL)
                # Extract lean code
                lean_match = re.search(r"```lean\n(.+?)```", block, re.DOTALL)
                if nl_match:
                    summary = nl_match.group(1).strip()[:300]
                    lean_code = lean_match.group(1).strip() if lean_match else ""
                    trivial = "Trivial" in block
                    prior.append({
                        "summary": summary,
                        "lean_code": lean_code,
                        "source": vfile.name,
                        "trivial": trivial,
                    })
        except Exception as e:
            print(f"Warning: could not parse {vfile}: {e}")
    
    return prior


def load_cumulative_lean() -> str:
    """Load the current cumulative Lean library, or create it."""
    if os.path.exists(CUMULATIVE_LEAN):
        with open(CUMULATIVE_LEAN) as f:
            return f.read()
    
    header = """import Mathlib

/-!
# P=NP Research Library
Cumulative formally verified theorems built by Metatron Research Lab.
Each theorem was proposed by Nemotron Ultra, formalized by Llama 405B,
and verified by the Lean 4 compiler.
-/

"""
    os.makedirs(os.path.dirname(CUMULATIVE_LEAN), exist_ok=True)
    with open(CUMULATIVE_LEAN, "w") as f:
        f.write(header)
    return header


# ============================================================================
# DEDUP & TRIVIAL DETECTION
# ============================================================================

def extract_keywords(text: str) -> set:
    """Extract meaningful keywords from a theorem description."""
    stop_words = {"the", "a", "an", "is", "are", "of", "for", "in", "to", "and",
                   "or", "that", "this", "it", "be", "as", "at", "by", "on", "with",
                   "from", "we", "can", "also", "any", "all", "if", "then", "there",
                   "two", "one", "each", "their", "its", "has", "have", "been", "will",
                   "which", "some", "such", "into", "not", "our", "use"}
    words = re.findall(r"[a-z]{3,}", text.lower())
    return set(words) - stop_words


def check_dedup(proposal: str, prior_verified: list, session_failed: list) -> str | None:
    """Check if proposal is too similar to prior work.
    Returns warning message if duplicate, None if OK."""
    prop_keywords = extract_keywords(proposal)
    if not prop_keywords:
        return None
    
    for v in prior_verified:
        v_keywords = extract_keywords(v["summary"])
        if not v_keywords:
            continue
        overlap = len(prop_keywords & v_keywords) / max(len(prop_keywords), 1)
        if overlap > 0.7:
            return f"Too similar to prior verified: '{v['summary'][:80]}...' ({overlap:.0%} overlap)"
    
    for f in session_failed:
        f_keywords = extract_keywords(f)
        overlap = len(prop_keywords & f_keywords) / max(len(prop_keywords), 1)
        if overlap > 0.6:
            return f"Too similar to failed attempt: '{f[:80]}...'"
    
    return None


def check_trivial(lean_code: str) -> bool:
    """Check if a verified proof is trivially true."""
    # Remove comments
    code = re.sub(r"--.*$", "", lean_code, flags=re.MULTILINE)
    code = re.sub(r"/-.*?-/", "", code, flags=re.DOTALL)
    
    # Check for trivial patterns
    for pattern in TRIVIAL_PATTERNS:
        if re.search(pattern, code, re.MULTILINE):
            return True
    
    # Check for placeholder definitions (∀ x, True)
    if "True" in code and re.search(r":\s*True", code):
        return True
    
    # Check for proofs that are only rfl/trivial/simp on identity propositions
    theorems = re.findall(r"theorem\s+\w+.*?:=\s*by\s+(.+?)(?:theorem|lemma|def|#|$)", 
                          code, re.DOTALL)
    for proof_body in theorems:
        body = proof_body.strip()
        if body in ("rfl", "trivial", "simp", "tauto", "decide"):
            # Single tactic — check if the statement is trivial
            return True
    
    return False


# ============================================================================
# LOGGING
# ============================================================================

def log(msg: str, also_print: bool = True):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")
    if also_print:
        print(entry)


def log_verified(turn: int, theorem_nl: str, lean_code: str, trivial: bool = False):
    tag = " (Trivial)" if trivial else ""
    with open(VERIFIED_FILE, "a") as f:
        f.write(f"\n## Turn {turn} — Verified ✓{tag}\n\n")
        f.write(f"**Natural Language:**\n{theorem_nl}\n\n")
        f.write(f"**Lean 4 Proof:**\n```lean\n{lean_code}\n```\n\n")
        f.write(f"---\n")


# ============================================================================
# API CALLS
# ============================================================================

def call_api(model: str, messages: list, temperature: float = 0.6,
             max_tokens: int = 4096) -> dict:
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
    if not content.strip() and reasoning.strip():
        content = reasoning
    return {"content": content, "reasoning_content": reasoning}


# ============================================================================
# PROPOSER
# ============================================================================

RESEARCH_CONTEXT = """You are a mathematical research assistant building a library of formally
verified lemmas in computational complexity theory using Lean 4 and Mathlib.

GOAL: Build foundational lemmas that formalize concepts related to P vs NP.
We are NOT trying to prove P=NP or P!=NP directly. Instead, we formalize
known results and build helper infrastructure.

PROGRESSION PHASES:
1. Basic Math: Nat/List/Set lemmas.
2. Functions & Complexity Basics: Polynomial composition, decidability.
3. Computation Models: Decidable languages, closure properties.
4. Reductions: Polynomial-time reductions, composition.
5. Complexity Classes: Define P and NP, prove basic containments.

CRITICAL CONSTRAINTS:
- Output ONE theorem per turn with a complete proof sketch
- Keep it SIMPLE and PROVABLE — Lean 4 compilation is the judge
- Use standard Mathlib tactics: simp, omega, ring, exact, apply, intro, decide, norm_num, linarith, aesop, tauto, ext, funext, induction, cases
- NEVER use sorry/admit/axiom
- Build on previously verified results when possible
- Avoid trivial tautologies (x = x, True, etc.) — prove SUBSTANTIVE math
- State the theorem in natural language FIRST, then give the proof sketch
"""


def get_current_phase(phase_counts: dict) -> int:
    """Determine current phase based on verified counts."""
    for phase in range(1, 6):
        if phase_counts.get(phase, 0) < PHASE_ADVANCE_THRESHOLD:
            return phase
    return 5  # Stay at phase 5 once all thresholds met


PHASE_NAMES = {
    1: "PHASE 1 (Basic Math — Nat, List, Set)",
    2: "PHASE 2 (Functions & Complexity Basics)",
    3: "PHASE 3 (Computation Models — Decidable Languages)",
    4: "PHASE 4 (Reductions — Poly-time)",
    5: "PHASE 5 (Complexity Classes — P, NP)",
}


def proposer_prompt(turn: int, verified_so_far: list, phase: int,
                    last_error: str = None, last_lean_code: str = None,
                    dedup_warning: str = None) -> list:
    verified_summary = ""
    if verified_so_far:
        # Show last 15 verified (keep prompt manageable)
        recent = verified_so_far[-15:]
        verified_summary = "\n\nPREVIOUSLY VERIFIED THEOREMS (most recent):\n"
        for i, v in enumerate(recent, 1):
            tag = " [trivial]" if v.get("trivial") else ""
            verified_summary += f"  {i}. {v['summary'][:150]}{tag}\n"
    
    error_feedback = ""
    if last_error:
        error_feedback = f"""
PREVIOUS ATTEMPT FAILED with Lean 4 compiler error:
```
{last_error[:2000]}
```
The failing code:
```lean
{(last_lean_code or 'N/A')[:2000]}
```
Propose a DIFFERENT, SIMPLER theorem that avoids these issues.
"""

    dedup_note = ""
    if dedup_warning:
        dedup_note = f"""
DEDUP WARNING: Your previous proposal was rejected: {dedup_warning}
Please propose something SUBSTANTIALLY DIFFERENT.
"""

    phase_name = PHASE_NAMES.get(phase, "PHASE 5")
    system_msg = RESEARCH_CONTEXT + verified_summary + error_feedback + dedup_note

    user_msg = f"""Turn {turn}/{MAX_TURNS}. Current phase: {phase_name}.

Propose ONE theorem to formalize in Lean 4 with Mathlib.

Requirements:
- State the theorem in natural language
- Provide a proof sketch
- The theorem should be NEW and SUBSTANTIVE (not a tautology)
- It should be PROVABLE with standard Lean 4/Mathlib tactics
- Keep it at the appropriate complexity level for the current phase
- Format:

THEOREM: <natural language statement>

PROOF SKETCH: <informal proof approach>

LEAN HINT: <suggested Lean 4 structure — imports, tactics>

DIFFICULTY: <easy/medium/hard>"""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def call_proposer(turn, verified_so_far, phase, last_error=None,
                  last_lean_code=None, dedup_warning=None):
    log(f"  [PROPOSER] Calling {PROPOSER_MODEL}...")
    messages = proposer_prompt(turn, verified_so_far, phase, last_error,
                               last_lean_code, dedup_warning)
    result = call_api(PROPOSER_MODEL, messages, temperature=0.7, max_tokens=2048)
    proposal = result["content"]
    log(f"  [PROPOSER] Got proposal ({len(proposal)} chars)")
    return proposal


# ============================================================================
# FORMALIZER
# ============================================================================

FORMALIZER_SYSTEM = """You are an expert Lean 4 programmer with deep knowledge of Mathlib.
Translate the theorem and proof sketch into a COMPLETE, COMPILABLE Lean 4 proof.

CRITICAL RULES:
1. Start with: import Mathlib
2. Use Lean 4 syntax (NOT Lean 3)
3. Tactics: simp, omega, ring, exact, apply, intro, cases, induction, decide, norm_num, linarith, positivity, aesop, tauto, rfl, ext, funext, congr
4. NO sorry, admit, axiom, native_decide
5. Keep proofs CONCRETE
6. Output ONLY valid Lean 4 code — no markdown fences, no explanation
7. A correct simple proof beats a broken complex one
8. For arithmetic: omega (linear), ring (algebraic), norm_num (numeric)
9. For sets: Set.ext, simp [Set.mem_union, Set.mem_inter]
10. For lists: simp [List.length_append, List.length_nil]

Example:
import Mathlib

theorem add_comm_nat (a b : Nat) : a + b = b + a := by omega
"""


def call_formalizer(proposal, fix_error=None, prev_code=None, cumulative_names=None):
    log(f"  [FORMALIZER] Calling {FORMALIZER_MODEL}...")
    
    user_msg = f"Translate this theorem into a complete Lean 4 file:\n\n{proposal}"
    
    if fix_error and prev_code:
        user_msg = f"""The previous Lean 4 code FAILED. Fix it.

PREVIOUS CODE:
```lean
{prev_code}
```

COMPILER ERROR:
```
{fix_error[:3000]}
```

Output the FIXED complete Lean 4 file. Only Lean 4 code, nothing else.
Common fixes:
- unknown identifier: check import or use different approach
- type mismatch: fix the types
- tactic failed: try simp, omega, ring, decide, norm_num, linarith, aesop
- too complex: simplify
"""

    messages = [
        {"role": "system", "content": FORMALIZER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    
    result = call_api(FORMALIZER_MODEL, messages, temperature=0.3, max_tokens=4096)
    code = result["content"]
    
    # Clean markdown fences
    code = re.sub(r'^```\w*\n', '', code, flags=re.MULTILINE)
    code = re.sub(r'\n```\s*$', '', code, flags=re.MULTILINE)
    code = code.strip()
    
    # Ensure starts with import
    if not code.startswith("import"):
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
    code_lower = lean_code.lower()
    for kw in DEGEN_KEYWORDS:
        if kw.lower() in code_lower:
            lines = lean_code.split("\n")
            for line in lines:
                stripped = line.split("--")[0]
                if kw.lower() in stripped.lower():
                    return f"Degeneration detected: '{kw}' found in code"
    
    if re.search(r':=\s*by\s*$', lean_code, re.MULTILINE):
        return "Degeneration detected: empty proof body"
    
    return None


# ============================================================================
# VERIFIER — Lean 4 compiler
# ============================================================================

def verify_lean(lean_code: str) -> tuple:
    """Write to attempt file and compile. Returns (success, output)."""
    degen = check_degeneration(lean_code)
    if degen:
        return False, degen
    
    os.makedirs(os.path.dirname(ATTEMPT_LEAN), exist_ok=True)
    with open(ATTEMPT_LEAN, "w") as f:
        f.write(lean_code)
    
    log(f"  [VERIFIER] Written to {ATTEMPT_LEAN}, compiling...")
    
    # Build only the attempt file
    cmd = f"cd {MATHLIB_DIR} && source {ELAN_ENV} && lake build MyProofs 2>&1"
    
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=600, cwd=MATHLIB_DIR,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        
        if result.returncode == 0 and "error" not in output.lower():
            log(f"  [VERIFIER] ✓ COMPILATION SUCCESSFUL")
            return True, output
        else:
            error_lines = [l for l in output.split("\n") if "error" in l.lower() or ":" in l]
            error_summary = "\n".join(error_lines[:20]) if error_lines else output[:2000]
            log(f"  [VERIFIER] ✗ COMPILATION FAILED")
            return False, output
            
    except subprocess.TimeoutExpired:
        log(f"  [VERIFIER] ✗ TIMED OUT (600s)")
        return False, "Compilation timed out after 600 seconds"
    except Exception as e:
        log(f"  [VERIFIER] ✗ Error: {e}")
        return False, str(e)


def append_to_cumulative(lean_code: str, turn: int, summary: str):
    """Append a verified proof to the cumulative library."""
    # Extract just the theorems/lemmas/defs (skip imports)
    lines = lean_code.split("\n")
    body_lines = []
    for line in lines:
        if line.startswith("import "):
            continue
        if line.startswith("open "):
            body_lines.append(line)
        elif line.strip():
            body_lines.append(line)
        elif body_lines:  # Keep blank lines within body
            body_lines.append(line)
    
    body = "\n".join(body_lines).strip()
    if not body:
        return
    
    section = f"""

-- ═══════════════════════════════════════════════════════
-- Turn {turn}: {summary[:80]}
-- Session: {TIMESTAMP}
-- ═══════════════════════════════════════════════════════

{body}
"""
    with open(CUMULATIVE_LEAN, "a") as f:
        f.write(section)


# ============================================================================
# GIT INTEGRATION
# ============================================================================

def git_commit(message: str):
    """Stage and commit changes in the math-lab directory."""
    try:
        subprocess.run(["git", "add", "-A"], cwd=PROJECT_DIR,
                       capture_output=True, timeout=10)
        subprocess.run(["git", "add", "-A"], cwd=MATHLIB_DIR,
                       capture_output=True, timeout=10)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=PROJECT_DIR, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            log(f"  [GIT] Committed: {message[:60]}")
        else:
            log(f"  [GIT] No changes to commit")
    except Exception as e:
        log(f"  [GIT] Warning: {e}")


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

def run_orchestrator():
    print("=" * 70)
    print("P=NP FORMAL VERIFICATION RESEARCH ORCHESTRATOR v2.0")
    print("=" * 70)
    
    # Load cross-session memory
    prior_verified = load_prior_verified()
    print(f"Loaded {len(prior_verified)} prior verified theorems")
    
    # Load or create cumulative lean library
    cumulative = load_cumulative_lean()
    print(f"Cumulative library: {len(cumulative)} chars")
    
    print(f"Session: {TIMESTAMP}")
    print(f"Proposer: {PROPOSER_MODEL}")
    print(f"Formalizer: {FORMALIZER_MODEL}")
    print(f"Max turns: {MAX_TURNS}, Fix attempts: {MAX_FIX_ATTEMPTS}")
    print("=" * 70)
    
    log("Session started (v2.0)")
    log(f"Prior verified: {len(prior_verified)}")
    
    # Initialize verified file
    with open(VERIFIED_FILE, "w") as f:
        f.write(f"# Formally Verified Theorems — Session {TIMESTAMP} (v2)\n\n")
        f.write(f"Prior knowledge: {len(prior_verified)} theorems from previous sessions\n\n---\n")
    
    # Track state
    all_verified = list(prior_verified)  # Start with prior knowledge
    session_verified = []
    session_failed_proposals = []
    total_verified = 0
    total_failed = 0
    total_trivial = 0
    consecutive_failures = 0
    phase_counts = {}  # phase -> count of verified in that phase
    
    # Estimate starting phase from prior work
    current_phase = min(5, 1 + len(prior_verified) // PHASE_ADVANCE_THRESHOLD)
    
    for turn in range(1, MAX_TURNS + 1):
        print(f"\n{'─' * 70}")
        current_phase = get_current_phase(phase_counts)
        print(f"TURN {turn}/{MAX_TURNS} | Phase {current_phase} | Verified: {total_verified} | Failed: {total_failed}")
        print(f"{'─' * 70}")
        log(f"\n=== TURN {turn}/{MAX_TURNS} (Phase {current_phase}) ===")
        
        if consecutive_failures >= 5:
            log("WARNING: 5 consecutive failures — dropping phase complexity")
            current_phase = max(1, current_phase - 1)
            consecutive_failures = 0
        
        # STEP 1: PROPOSE (with dedup retry)
        proposal = None
        dedup_warning = None
        for dedup_attempt in range(3):
            try:
                proposal = call_proposer(turn, all_verified, current_phase,
                                         dedup_warning=dedup_warning)
            except Exception as e:
                log(f"  Proposer failed: {e}")
                break
            
            dup = check_dedup(proposal, all_verified, session_failed_proposals)
            if dup:
                log(f"  [DEDUP] Rejected: {dup}")
                dedup_warning = dup
                continue
            break
        
        if not proposal:
            total_failed += 1
            consecutive_failures += 1
            time.sleep(5)
            continue
        
        log(f"  PROPOSAL: {proposal[:300]}", also_print=False)
        
        # STEP 2+3: FORMALIZE + VERIFY (with fix attempts)
        success = False
        lean_code = None
        last_error = None
        
        for attempt in range(MAX_FIX_ATTEMPTS + 1):
            attempt_label = "initial" if attempt == 0 else f"fix #{attempt}"
            log(f"  Attempt: {attempt_label}")
            
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
            
            ok, output = verify_lean(lean_code)
            
            if ok:
                success = True
                break
            else:
                last_error = output
                log(f"  Compilation failed ({attempt_label})")
                if attempt < MAX_FIX_ATTEMPTS:
                    time.sleep(2)
        
        # STEP 4: RECORD RESULT
        if success:
            trivial = check_trivial(lean_code)
            total_verified += 1
            if trivial:
                total_trivial += 1
            consecutive_failures = 0
            
            summary_match = re.search(r'THEOREM:\s*(.+?)(?:\n|PROOF)', proposal, re.DOTALL)
            summary = summary_match.group(1).strip()[:200] if summary_match else proposal[:200]
            
            entry = {"summary": summary, "lean_code": lean_code, "trivial": trivial}
            all_verified.append(entry)
            session_verified.append(entry)
            log_verified(turn, proposal, lean_code, trivial)
            
            # Update phase count
            phase_counts[current_phase] = phase_counts.get(current_phase, 0) + 1
            
            # Append to cumulative library
            append_to_cumulative(lean_code, turn, summary)
            
            # Git commit
            tag = " [trivial]" if trivial else ""
            git_commit(f"Verified: {summary[:50]} (turn {turn}){tag}")
            
            trivial_tag = " (trivial)" if trivial else ""
            print(f"  ✓ VERIFIED{trivial_tag} — Total: {total_verified} ({total_trivial} trivial)")
            log(f"  ✓ VERIFIED{trivial_tag} (total: {total_verified})")
        else:
            total_failed += 1
            consecutive_failures += 1
            session_failed_proposals.append(proposal[:300])
            print(f"  ✗ FAILED after {MAX_FIX_ATTEMPTS + 1} attempts")
            log(f"  ✗ FAILED after all attempts")
        
        time.sleep(3)
    
    # SESSION SUMMARY
    substantive = total_verified - total_trivial
    summary = {
        "session": TIMESTAMP,
        "version": "2.0",
        "proposer": PROPOSER_MODEL,
        "formalizer": FORMALIZER_MODEL,
        "turns": MAX_TURNS,
        "verified": total_verified,
        "substantive": substantive,
        "trivial": total_trivial,
        "failed": total_failed,
        "success_rate": round(total_verified / max(1, MAX_TURNS) * 100, 1),
        "prior_knowledge": len(prior_verified),
        "phase_counts": phase_counts,
        "verified_file": VERIFIED_FILE,
    }
    
    with open(SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n{'=' * 70}")
    print(f"SESSION COMPLETE (v2.0)")
    print(f"{'=' * 70}")
    print(f"Verified: {total_verified} ({substantive} substantive, {total_trivial} trivial)")
    print(f"Failed: {total_failed}")
    print(f"Success rate: {total_verified / max(1, MAX_TURNS) * 100:.1f}%")
    print(f"Phase progress: {phase_counts}")
    print(f"Cumulative library: {CUMULATIVE_LEAN}")
    print(f"Verified proofs: {VERIFIED_FILE}")
    print(f"Summary: {SUMMARY_JSON}")
    
    log(f"\nSESSION COMPLETE: {total_verified} verified ({substantive} substantive, "
        f"{total_trivial} trivial), {total_failed} failed, "
        f"{total_verified / max(1, MAX_TURNS) * 100:.1f}% success rate")
    
    return total_verified


if __name__ == "__main__":
    os.makedirs(SESSION_DIR, exist_ok=True)
    
    try:
        count = run_orchestrator()
        sys.exit(0 if count > 0 else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        log("Session interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL: {e}")
        log(f"FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

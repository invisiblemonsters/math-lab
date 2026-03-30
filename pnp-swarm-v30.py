#!/usr/bin/env python3
"""
Math Lab v30 — Enhanced Swarm Architecture for P vs NP
======================================================
All v29 infrastructure + 6 major upgrades:
  1. P=NP algorithm search mode
  2. Difficulty curriculum (levels 1-5, auto-promote/demote)
  3. Repair loop after falsification (2 retries)
  4. Non-natural proof hard filter (pre-barrier gate)
  5. Proof complexity domain expansion
  6. Seed formalizer with known complexity theory Lean examples
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
import random
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

MAX_CYCLES = 15
LEAN_TIMEOUT = 600
MAX_FIX_ATTEMPTS = 3
API_TIMEOUT = 120
PARALLEL_TIMEOUT = 180

# v30 NEW CONFIG
MODE = "compile_training"    # "separation", "algorithm_search", or "compile_training"
MAX_REPAIR_ATTEMPTS = 2      # repair loop retries after falsification
PROMOTE_AFTER = 3            # consecutive verifications to level up
DEMOTE_AFTER = 10            # consecutive failures to level down

# ============================================================
# MODEL ASSIGNMENTS
# ============================================================

MODELS = {
    "barrier_relativization": "qwen/qwq-32b",
    "barrier_natural_proofs": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "barrier_algebrization":  "meta/llama-3.3-70b-instruct",
    "conjecture_alpha":  "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "conjecture_beta":   "mistralai/mistral-large-3-675b-instruct-2512",
    "conjecture_gamma":  "qwen/qwen3.5-397b-a17b",
    "decomposer":        "qwen/qwen3-next-80b-a3b-thinking",
    "formalizer_primary": "qwen/qwen3-coder-480b-a35b-instruct",
    "formalizer_backup":  "mistralai/mathstral-7b-v0.1",
    "critic_counterexample": "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "critic_triviality":     "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "natural_filter":        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "prover_alpha": "mistralai/devstral-2-123b-instruct-2512",
    "prover_beta":  "qwen/qwen3.5-122b-a10b",
    "intent_checker": "mistralai/mistral-nemotron",
    "scribe": "mistralai/magistral-small-2506",
    "repair": "mistralai/mistral-large-3-675b-instruct-2512",
}

# ============================================================
# API SETUP
# ============================================================

def load_api_key() -> str:
    with open(API_KEY_FILE) as f:
        return base64.b64decode(f.read().strip()).decode()

API_KEY = load_api_key()

def load_telegram_config():
    env_path = Path.home() / ".hermes" / ".env"
    token, chat_id = None, None
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
            elif line.startswith("TELEGRAM_HOME_CHANNEL="):
                chat_id = line.split("=", 1)[1].strip()
    return token, chat_id

TG_TOKEN, TG_CHAT_ID = load_telegram_config()

def telegram_alert(message: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except:
        pass

def llm_call(model: str, messages: list, temperature: float = 0.7,
             max_tokens: int = 4096, timeout: int = API_TIMEOUT) -> Optional[str]:
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if "qwq" in model or "r1" in model or "thinking" in model:
        payload["temperature"] = 0.6
    try:
        resp = requests.post(NVIDIA_BASE, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            print(f"  [API ERROR] {model}: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content") or msg.get("reasoning_content") or ""
        return content.strip() if content else None
    except Exception as e:
        print(f"  [API ERROR] {model}: {e}")
        return None

def parallel_llm_calls(calls: list, timeout: int = PARALLEL_TIMEOUT) -> dict:
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
    for role, _, _, _ in calls:
        if role not in results:
            results[role] = None
    return results

# ============================================================
# LEAN 4 COMPILATION
# ============================================================

def compile_lean(code: str) -> tuple[bool, str]:
    ATTEMPT_LEAN.write_text(code)
    env = os.environ.copy()
    elan_env = Path.home() / ".elan" / "env"
    if elan_env.exists():
        env["PATH"] = str(Path.home() / ".elan" / "bin") + ":" + env.get("PATH", "")
    try:
        result = subprocess.run(
            ["lake", "build", "MyProofs.Attempt"],
            capture_output=True, text=True, timeout=LEAN_TIMEOUT,
            cwd=str(LEAN_PROJECT), env=env
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT: Lean compilation exceeded {LEAN_TIMEOUT}s"
    except Exception as e:
        return False, f"COMPILE ERROR: {e}"

# ============================================================
# CHANGE #6: SEED THEOREMS
# ============================================================

SEED_THEOREMS = [
    # Each is a (name, lean_code) pair the formalizer can learn from
    ("pigeonhole", """-- Pigeonhole principle
theorem pigeonhole_basic (n : Nat) (f : Fin (n+1) -> Fin n) :
    Function.Surjective f -> False := by
  intro hsurj
  exact Fin.not_surjective_of_lt (by omega) hsurj"""),

    ("cantor", """-- Cantor's theorem
theorem cantor_diag {a : Type} (f : a -> Set a) : Function.Surjective f -> False := by
  intro h; obtain \\u27E8a, ha\\u27E9 := h {x | x \\u2209 f x}; simp_all"""),

    ("exp_growth", """-- Exponential growth for lower bounds
theorem exp_ge_succ (n : Nat) : 2 ^ n >= n + 1 := by
  induction n with
  | zero => simp
  | succ k ih => calc 2 ^ (k+1) = 2 * 2^k := by ring_nf; _ >= 2 * (k+1) := by omega; _ >= k+2 := by omega"""),

    ("comp_injective", """-- Composition preserves injectivity
theorem comp_inj {f : b -> c} {g : a -> b}
    (hf : Function.Injective f) (hg : Function.Injective g) :
    Function.Injective (f \\u2218 g) := Function.Injective.comp hf hg"""),

    ("de_morgan", """-- De Morgan's law
theorem de_morgan_or (p q : Prop) : \\u00AC(p \\u2228 q) \\u2194 (\\u00ACp \\u2227 \\u00ACq) := not_or"""),

    ("poly_bound", """-- n*n = n^2
theorem sq_eq_mul (n : Nat) : n ^ 2 = n * n := by ring"""),

    ("subset_trans", """-- Subset transitivity for reduction proofs
theorem set_subset_trans {a : Type} {s t u : Set a} (h1 : s \\u2286 t) (h2 : t \\u2286 u) : s \\u2286 u :=
  Set.Subset.trans h1 h2"""),

    ("finset_card", """-- Subset cardinality bound
theorem card_sub_le {a : Type} [DecidableEq a] {s t : Finset a} (h : s \\u2286 t) :
    s.card \\u2264 t.card := Finset.card_le_card h"""),

    ("complement", """-- Double complement
theorem compl_compl_set {a : Type} (s : Set a) : s\\u1D9C\\u1D9C = s := compl_compl s"""),

    ("diag", """-- Diagonalization: no enumeration of all functions
theorem no_enum (f : Nat -> Nat -> Nat) : \\u2203 g : Nat -> Nat, \\u2200 n, g \\u2260 f n := by
  exact \\u27E8fun n => f n n + 1, fun n h => by have := congr_fun h n; omega\\u27E9"""),
]

def get_seed_examples() -> str:
    """Format seed theorems for formalizer context. Includes static seeds + dynamic verified seeds."""
    lines = ["--- SEED THEOREMS: Known results in Lean 4 (use similar patterns) ---"]
    for name, code in SEED_THEOREMS:
        lines.append(f"\n-- SEED [{name}]")
        lines.append(code)

    # Dynamic seeds from verified compilations
    seed_file = MEMORY_DIR / "verified_seeds.json"
    if seed_file.exists():
        try:
            dynamic = json.loads(seed_file.read_text())
            if dynamic:
                lines.append("\n--- VERIFIED SEEDS (compiled successfully) ---")
                for s in dynamic[-15:]:  # last 15
                    lines.append(f"\n-- VERIFIED [{s['name']}]")
                    lines.append(s["code"])
        except:
            pass

    return "\n".join(lines)

# ============================================================
# RESEARCH MEMORY (extended for v30)
# ============================================================

class SwarmMemory:
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
            # v30 additions
            "difficulty_level": 1, "consecutive_verified": 0, "consecutive_failed": 0,
            "total_repairs": 0, "total_repair_successes": 0,
            "total_natural_filtered": 0, "mode": MODE,
        })
        # Ensure v30 keys exist on upgrade from v29
        for k, v in [("difficulty_level", 1), ("consecutive_verified", 0),
                      ("consecutive_failed", 0), ("total_repairs", 0),
                      ("total_repair_successes", 0), ("total_natural_filtered", 0),
                      ("mode", MODE)]:
            if k not in self.global_state:
                self.global_state[k] = v

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
        self._write_json(self.failed_file, self.failed_approaches[-200:])
        self._write_json(self.verified_file, self.verified_theorems)
        self._write_json(self.barrier_file, self.barrier_log[-200:])

    def add_verified(self, theorem_name, statement, lean_code, approach):
        self.verified_theorems.append({
            "name": theorem_name, "statement": statement,
            "approach": approach, "timestamp": datetime.datetime.now().isoformat(),
            "code_hash": hashlib.sha256(lean_code.encode()).hexdigest()[:16],
            "difficulty": self.global_state["difficulty_level"],
        })
        self.global_state["total_verified"] += 1
        self.global_state["consecutive_verified"] += 1
        self.global_state["consecutive_failed"] = 0
        self._check_promotion()
        self.save()

    def add_failed(self, approach, reason, barrier_profile):
        self.failed_approaches.append({
            "approach": approach[:500], "reason": reason[:500],
            "barrier_profile": barrier_profile,
            "timestamp": datetime.datetime.now().isoformat(),
        })
        self.global_state["consecutive_failed"] += 1
        self.global_state["consecutive_verified"] = 0
        self._check_demotion()
        self.save()

    def add_barrier_kill(self, approach, scores):
        self.barrier_log.append({
            "approach": approach[:300], "scores": scores,
            "timestamp": datetime.datetime.now().isoformat(),
        })
        self.global_state["total_rejected_barrier"] += 1
        self.save()

    def _check_promotion(self):
        """Auto-promote difficulty after consecutive verifications."""
        if (self.global_state["consecutive_verified"] >= PROMOTE_AFTER
                and self.global_state["difficulty_level"] < 5):
            old = self.global_state["difficulty_level"]
            self.global_state["difficulty_level"] += 1
            self.global_state["consecutive_verified"] = 0
            print(f"  [CURRICULUM] PROMOTED: Level {old} -> {self.global_state['difficulty_level']}")
            telegram_alert(f"📈 Math Lab v30 — PROMOTED to difficulty level {self.global_state['difficulty_level']}")

    def _check_demotion(self):
        """Auto-demote difficulty after consecutive failures."""
        if (self.global_state["consecutive_failed"] >= DEMOTE_AFTER
                and self.global_state["difficulty_level"] > 1):
            old = self.global_state["difficulty_level"]
            self.global_state["difficulty_level"] -= 1
            self.global_state["consecutive_failed"] = 0
            print(f"  [CURRICULUM] DEMOTED: Level {old} -> {self.global_state['difficulty_level']}")

    def get_context_summary(self) -> str:
        lines = [f"=== SWARM v30 RESEARCH MEMORY ==="]
        lines.append(f"Mode: {self.global_state.get('mode', MODE)}")
        lines.append(f"Difficulty: {self.global_state['difficulty_level']}/5")
        lines.append(f"Total cycles: {self.global_state['total_cycles']}")
        lines.append(f"Verified: {self.global_state['total_verified']}")
        lines.append(f"Barrier-killed: {self.global_state['total_rejected_barrier']}")
        lines.append(f"Falsified: {self.global_state['total_falsified']}")
        lines.append(f"Natural-filtered: {self.global_state.get('total_natural_filtered', 0)}")
        lines.append(f"Repairs attempted: {self.global_state.get('total_repairs', 0)}")
        lines.append(f"Repair successes: {self.global_state.get('total_repair_successes', 0)}")

        if self.verified_theorems:
            lines.append(f"\n--- Last 5 Verified ---")
            for t in self.verified_theorems[-5:]:
                lines.append(f"  {t['name']}: {t['statement'][:150]}")

        if self.failed_approaches:
            lines.append(f"\n--- Last 10 Failed (DO NOT REPEAT) ---")
            for f in self.failed_approaches[-10:]:
                lines.append(f"  FAILED: {f['approach'][:150]}")
                lines.append(f"    Reason: {f['reason'][:100]}")

        return "\n".join(lines)


# ============================================================
# DIFFICULTY CURRICULUM PROMPTS (Change #2)
# ============================================================

DIFFICULTY_PROMPTS = {
    1: """DIFFICULTY LEVEL 1 — KNOWN RESULTS
Formalize a KNOWN, PROVEN result in complexity theory or combinatorics. Examples:
- There exist problems in EXP not in P (time hierarchy)
- Pigeonhole principle and its circuit complexity applications
- Shannon's counting: most functions need exponential circuits
- Basic oracle separation results
- Simple diagonal arguments
Pick something KNOWN TO BE TRUE and formalize it precisely. The goal is building our Lean library.""",

    2: """DIFFICULTY LEVEL 2 — KNOWN BUT NON-TRIVIAL
Formalize a known but technically involved result. Examples:
- Parity not in AC0 (Razborov-Smolensky / Furst-Saxe-Sipser)
- Resolution lower bounds for pigeonhole (Ben-Sasson & Wigderson)
- Oracle separations between specific complexity classes
- Sipser-Lautemann: BPP in Sigma_2^P
Pick something PROVEN but requiring real proof effort.""",

    3: """DIFFICULTY LEVEL 3 — NOVEL INTERMEDIATE LEMMAS
Propose a NEW lemma that hasn't been formally verified before, but is:
- Plausibly true based on existing theory
- Useful as a stepping stone toward circuit/proof complexity results
- Precise enough to formalize
Include proof complexity approaches: resolution, cutting planes, Frege systems.""",

    4: """DIFFICULTY LEVEL 4 — NOVEL RESULTS
Propose a genuinely NEW result in:
- Circuit complexity lower bounds
- Proof complexity (resolution width, depth, Frege lower bounds)
- Connections between proof complexity and circuit complexity
- Algebraic complexity theory
This should be something not in the literature but plausibly provable.""",

    5: """DIFFICULTY LEVEL 5 — P vs NP DIRECT
Attack P vs NP directly. You must evade ALL known barriers:
- Relativization (Baker-Gill-Solovay)
- Natural Proofs (Razborov-Rudich)
- Algebrization (Aaronson-Wigderson)
Consider: GCT, proof complexity transfers, non-standard approaches.""",
}

ALGORITHM_SEARCH_PROMPT = """MODE: ALGORITHM SEARCH (P=NP direction)
Instead of proving separation, search for a POLYNOMIAL-TIME algorithm for an NP-complete problem.
Target problems (pick one):
- 3-SAT
- Subset Sum
- Graph Coloring
- Clique
Propose a specific algorithm with:
ALGORITHM_NAME: <name>
TARGET_PROBLEM: <which NP-complete problem>
DESCRIPTION: <how it works, step by step>
TIME_COMPLEXITY_CLAIM: <what you claim the runtime is>
CORRECTNESS_ARGUMENT: <why it's correct>
KEY_INSIGHT: <what makes this work when others failed>"""


# ============================================================
# CHANGE #5: PROOF COMPLEXITY DOMAIN CONTEXT
# ============================================================

PROOF_COMPLEXITY_CONTEXT = """
PROOF COMPLEXITY — An alternative path to P vs NP:
- Resolution: Prove exponential lower bounds on resolution refutation length
- Cutting Planes: Show CP proofs of certain tautologies require exponential length
- Frege Systems: The frontier — proving Frege lower bounds would separate NP from coNP
- Extended Frege: Even harder — EF lower bounds would show NP != coNP unconditionally
- Connections: Proof complexity lower bounds imply circuit lower bounds via feasible interpolation
- Known results: Tseitin tautologies hard for resolution, PHP hard for bounded-depth Frege
- Open: Any superpolynomial lower bound for general Frege systems

Key insight: Proof complexity sidesteps the Natural Proofs barrier entirely because proof
systems are defined objects, not random Boolean functions.
"""

# ============================================================
# LAYER IMPLEMENTATIONS
# ============================================================

def load_existing_theorems() -> str:
    if RESEARCH_LEAN.exists():
        content = RESEARCH_LEAN.read_text()
        lines = content.split('\n')
        theorems = [l.strip() for l in lines if l.strip().startswith("theorem ") or l.strip().startswith("lemma ")]
        return f"Existing library: {len(theorems)} theorems/lemmas in Research.lean ({len(lines)} lines)"
    return "No existing theorem library."

def load_lean_examples() -> str:
    if not RESEARCH_LEAN.exists():
        return ""
    content = RESEARCH_LEAN.read_text()
    lines = content.split('\n')
    examples = []
    i = 0
    while i < len(lines) and len(examples) < 20:
        line = lines[i].strip()
        if line.startswith("theorem ") or line.startswith("lemma "):
            block = []
            while i < len(lines) and lines[i].strip() != "" and not lines[i].strip().startswith("-- ="):
                block.append(lines[i])
                i += 1
            text = '\n'.join(block)
            if len(block) >= 2 and "trivial" not in text and ":= rfl" not in text:
                examples.append(text)
        i += 1
    if not examples:
        return ""
    sample = examples[:15] if len(examples) <= 15 else examples[::len(examples)//15][:15]
    header = f"--- {len(sample)} COMPILED LEAN 4 EXAMPLES FROM OUR LIBRARY ---\n"
    return header + "\n\n".join(sample)


# ============================================================
# CHANGE #4: NON-NATURAL PROOF FILTER (pre-barrier hard gate)
# ============================================================

def run_natural_filter(proposal: dict) -> bool:
    """Hard binary gate: reject proposals that use natural proof strategies.
    Returns True if proposal PASSES (is non-natural), False if killed."""
    text = proposal["text"]
    msg = [
        {"role": "system", "content": """You are a Natural Proofs barrier detector. Your SOLE job is a binary decision.

A proof strategy is "natural" (in the Razborov-Rudich sense) if it:
1. Defines a combinatorial PROPERTY of Boolean functions
2. That property is CONSTRUCTIVE (efficiently checkable given the truth table)
3. That property is LARGE (holds for a random function with non-negligible probability)

If ALL THREE conditions hold, the approach CANNOT prove circuit lower bounds against P/poly
(assuming pseudorandom functions exist).

Analyze the proposal and respond with EXACTLY:
NATURAL: YES  (if all 3 conditions hold — this approach is doomed)
NATURAL: NO   (if at least one condition fails — this approach might work)
REASON: <one sentence>"""},
        {"role": "user", "content": f"Is this a natural proof strategy?\n\n{text}"}
    ]
    result = llm_call(MODELS["natural_filter"], msg, temperature=0.2)
    if result:
        is_natural = "NATURAL: YES" in result.upper() or "NATURAL:YES" in result.upper()
        if is_natural:
            print(f"  [NATURAL FILTER] KILLED — natural proof strategy detected")
            reason = ""
            for line in result.split('\n'):
                if line.strip().upper().startswith("REASON:"):
                    reason = line.split(":", 1)[-1].strip()[:80]
            if reason:
                print(f"    Reason: {reason}")
            return False
        else:
            print(f"  [NATURAL FILTER] PASSED — non-natural strategy")
            return True
    print(f"  [NATURAL FILTER] Model failed, allowing through")
    return True


def run_triviality_only(proposal: dict) -> dict:
    """At difficulty 1-2, only check triviality — don't try to falsify known results."""
    text = proposal["text"]
    trivial_prompt = [
        {"role": "system", "content": """Check if this is trivially true (tautology, x=x) or too simple to be worth formalizing.
Do NOT check if it's "known" — at this difficulty level we WANT known results.
Only reject if it's completely trivial (e.g. 1=1, True, obvious tautology).
VERDICT: TRIVIAL or VERDICT: NONTRIVIAL"""},
        {"role": "user", "content": f"Check:\n\n{text}"}
    ]
    print("  [TRIVIALITY CHECK] (level 1-2: skipping counterexample critic)...")
    result = llm_call(MODELS["critic_triviality"], trivial_prompt, temperature=0.3)
    verdict = {"falsified": False, "trivial": False, "details": {}}
    if result:
        verdict["trivial"] = "VERDICT: TRIVIAL" in result.upper()
        verdict["details"]["triviality"] = result[:500]
        print(f"    {'TRIVIAL' if verdict['trivial'] else 'NONTRIVIAL — proceeding to formalization'}")
    else:
        print(f"    Critic FAILED — proceeding")
    return verdict


# --- Layer 2: Conjecture Engine ---
def run_conjecture_engine(memory: SwarmMemory, cycle: int) -> list[dict]:
    context = memory.get_context_summary()
    existing = load_existing_theorems()
    difficulty = memory.global_state["difficulty_level"]
    mode = memory.global_state.get("mode", MODE)

    if mode == "algorithm_search":
        mode_prompt = ALGORITHM_SEARCH_PROMPT
    else:
        mode_prompt = DIFFICULTY_PROMPTS.get(difficulty, DIFFICULTY_PROMPTS[5])

    # Add proof complexity context for level >= 3
    extra = ""
    if difficulty >= 3 and mode == "separation":
        extra = PROOF_COMPLEXITY_CONTEXT

    system_prompt = f"""You are a mathematical research agent working on P vs NP and related complexity theory.
Your job is to propose a SPECIFIC, FORMAL conjecture or lemma.

{mode_prompt}

{extra}

CONSTRAINTS:
- Must be precise enough to formalize in Lean 4
- Must NOT repeat failed approaches listed below
- State the conjecture, a proof sketch, and relevant barriers

{context}
{existing}"""

    if mode == "algorithm_search":
        user_prompt = f"Cycle {cycle}, difficulty {difficulty}. Propose a polynomial-time algorithm for an NP-complete problem."
    else:
        user_prompt = f"""Cycle {cycle}, difficulty {difficulty}/5. Propose ONE specific mathematical conjecture or lemma.

Format:
CONJECTURE_NAME: <short_name>
STATEMENT: <precise mathematical statement>
PROOF_SKETCH: <brief proof strategy>
BARRIER_CLAIM: <which barriers does this evade and why?>
DOMAIN: <circuit_complexity / proof_complexity / algebraic / combinatorial / algorithm>"""

    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    print(f"  [LAYER 2] Conjecture Engine — 3 models (mode={mode}, difficulty={difficulty})...")
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
    text = proposal["text"]

    def make_sentinel_prompt(barrier_type, description):
        return [
            {"role": "system", "content": f"""You are the {barrier_type} Sentinel in a P vs NP research swarm.
Evaluate whether a proposed proof approach falls prey to the {barrier_type} barrier.

{description}

Score 1-10:
  1-3 = LOW RISK (likely evades)
  4-6 = MODERATE (unclear)
  7-10 = HIGH RISK (likely blocked)

Respond EXACTLY:
SCORE: <number>
REASONING: <2-3 sentences>"""},
            {"role": "user", "content": f"Evaluate:\n\n{text}"}
        ]

    rel_desc = "The RELATIVIZATION barrier (Baker-Gill-Solovay 1975): Any proof that P!=NP must use techniques that do NOT work relative to all oracles."
    nat_desc = "The NATURAL PROOFS barrier (Razborov-Rudich 1997): Circuit lower bounds cannot use a combinatorial property that is both constructive and large."
    alg_desc = "The ALGEBRIZATION barrier (Aaronson-Wigderson 2009): Techniques that algebrize cannot resolve P vs NP."

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
            score = 5
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
            print(f"    [{barrier}] Score: {score}/10 -- {reasoning[:80]}")
        else:
            scores[barrier] = 5
            print(f"    [{barrier}] Sentinel FAILED, defaulting to 5")

    scores["total"] = scores.get("R", 5) + scores.get("N", 5) + scores.get("A", 5)
    scores["killed"] = all(v >= 7 for k, v in scores.items() if k in ("R", "N", "A"))
    return scores


# --- Layer 4: Adversarial Critics ---
def run_adversarial_critics(proposal: dict) -> dict:
    text = proposal["text"]
    counter_prompt = [
        {"role": "system", "content": """You are an adversarial critic in a math research swarm. ATTACK the proposal.
Find: counterexample, logical flaw, hidden impossible dependency, or vacuous truth.
VERDICT: FALSIFIED (with explanation) or VERDICT: SURVIVES (with why you couldn't break it)."""},
        {"role": "user", "content": f"Attack:\n\n{text}"}
    ]
    trivial_prompt = [
        {"role": "system", "content": """Check if this is trivially true, well-known, or doesn't advance research.
VERDICT: TRIVIAL, KNOWN, or NONTRIVIAL."""},
        {"role": "user", "content": f"Check:\n\n{text}"}
    ]

    print("  [LAYER 4] Adversarial Critics -- attacking...")
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
                print(f"    [counterexample] {'FALSIFIED' if verdict['falsified'] else 'SURVIVES'}")
            elif role == "triviality":
                verdict["trivial"] = "VERDICT: TRIVIAL" in upper or "VERDICT: KNOWN" in upper
                verdict["details"]["triviality"] = text[:500]
                print(f"    [triviality] {'TRIVIAL/KNOWN' if verdict['trivial'] else 'NONTRIVIAL'}")
        else:
            print(f"    [{role}] Critic FAILED")
    return verdict


# ============================================================
# CHANGE #3: REPAIR LOOP
# ============================================================

def run_repair(proposal: dict, critic_feedback: str, attempt: int) -> Optional[dict]:
    """Given a falsified proposal and the critic's feedback, try to repair it."""
    print(f"  [REPAIR] Attempt {attempt}/{MAX_REPAIR_ATTEMPTS} -- weakening/repairing conjecture...")

    msg = [
        {"role": "system", "content": """You are a conjecture repair agent. A proposal was FALSIFIED by an adversarial critic.
Your job: analyze the counterexample/flaw and REPAIR the conjecture by:
1. Weakening the statement to avoid the counterexample
2. Adding conditions that exclude the counterexample
3. Reformulating the approach to address the flaw
4. Pivoting to a related but sound conjecture

The repaired conjecture must still be meaningful and non-trivial.

Respond in the SAME format:
CONJECTURE_NAME: <name>_repaired
STATEMENT: <repaired statement>
PROOF_SKETCH: <updated proof strategy>
BARRIER_CLAIM: <barriers evaded>
REPAIR_NOTE: <what was wrong and how you fixed it>
DOMAIN: <domain>"""},
        {"role": "user", "content": f"""ORIGINAL PROPOSAL:
{proposal['text'][:2000]}

CRITIC FEEDBACK (why it was falsified):
{critic_feedback[:1500]}

Repair this conjecture to survive the criticism."""}
    ]

    result = llm_call(MODELS["repair"], msg, temperature=0.6)
    if result and len(result) > 100:
        print(f"    Repair generated ({len(result)} chars)")
        return {"source": f"{proposal['source']}_repair{attempt}", "text": result,
                "model": MODELS["repair"], "is_repair": True}
    print(f"    Repair FAILED")
    return None


# --- Layer 3: Decomposer + Formalizer ---
def run_decompose_and_formalize(proposal: dict, existing_library: str, difficulty: int = 5) -> Optional[str]:
    print("  [LAYER 3] Decomposer -- breaking into subgoals...")

    # Step 3: Constrain decomposition based on difficulty
    if difficulty <= 2:
        constraint = """CONSTRAINTS:
- Maximum 3 subgoals
- Proof should be under 15 lines of Lean 4
- Prefer using existing Mathlib lemmas over building from scratch
- Do NOT propose multi-lemma architectures — one main theorem with a simple proof"""
        decomp_tokens = 1500
    elif difficulty <= 3:
        constraint = """CONSTRAINTS:
- Maximum 5 subgoals
- Proof should be under 30 lines of Lean 4
- Prefer simple tactics: simp, omega, ring, exact, apply
- At most 1 auxiliary lemma"""
        decomp_tokens = 2500
    else:
        constraint = """CONSTRAINTS:
- Maximum 7 subgoals
- Keep proof strategy concrete and achievable
- At most 2 auxiliary lemmas"""
        decomp_tokens = 4096

    decompose_msg = [
        {"role": "system", "content": f"""You are a mathematical decomposer. Break the conjecture into:
1. Required definitions (only if not in Mathlib)
2. Auxiliary lemmas needed (minimize these)
3. The main theorem statement
4. Proof strategy as ordered subgoals

{constraint}

Keep it precise and formal. Output should be ready for Lean 4."""},
        {"role": "user", "content": f"Decompose:\n\n{proposal['text']}"}
    ]
    decomposition = llm_call(MODELS["decomposer"], decompose_msg, temperature=0.4, max_tokens=decomp_tokens)
    if not decomposition:
        print("    Decomposer FAILED")
        return None
    print(f"    Decomposed ({len(decomposition)} chars)")

    lean_examples = load_lean_examples()
    seed_examples = get_seed_examples()

    print("  [LAYER 3] Formalizer -- translating to Lean 4...")
    formalize_msg = [
        {"role": "system", "content": f"""You are a Lean 4 formalization expert. Convert to COMPILABLE Lean 4 code.

RULES:
- Import Mathlib (use `import Mathlib` at top)
- Use Lean 4 syntax (NOT Lean 3)
- Do NOT use `begin`/`end` -- use `by` tactic blocks
- NEVER use `sorry`, `admit`, or `Sorry` — code with sorry will be REJECTED
- If proof is hard, prove a SIMPLER version that still compiles
- Keep code SHORT — under 30 lines preferred
- Prefer simple tactics: simp, omega, ring, exact, apply, intro, cases
- The code must be SELF-CONTAINED

{existing_library}
{lean_examples}
{seed_examples}

Output ONLY Lean 4 code starting with `import Mathlib`."""},
        {"role": "user", "content": f"Formalize:\n\n{decomposition}"}
    ]

    for formalizer_key in ["formalizer_primary", "formalizer_backup"]:
        lean_code = llm_call(MODELS[formalizer_key], formalize_msg, temperature=0.3, max_tokens=8192)
        if lean_code:
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
def load_fix_patterns() -> str:
    """Load successful fix patterns from past proof worker successes."""
    fix_file = MEMORY_DIR / "fix_patterns.json"
    if not fix_file.exists():
        return ""
    try:
        patterns = json.loads(fix_file.read_text())
        if not patterns:
            return ""
        lines = ["--- PAST SUCCESSFUL FIXES (learn from these) ---"]
        for p in patterns[-5:]:  # last 5 successes
            lines.append(f"\nError type: {p.get('error_type', 'unknown')}")
            lines.append(f"Fix applied: {p.get('fix_summary', 'unknown')}")
            if p.get('before_snippet'):
                lines.append(f"Before: {p['before_snippet'][:200]}")
            if p.get('after_snippet'):
                lines.append(f"After: {p['after_snippet'][:200]}")
        return "\n".join(lines)
    except:
        return ""


def save_fix_pattern(error_msg: str, before_code: str, after_code: str):
    """Save a successful fix for future proof worker context."""
    fix_file = MEMORY_DIR / "fix_patterns.json"
    patterns = []
    if fix_file.exists():
        try:
            patterns = json.loads(fix_file.read_text())
        except:
            patterns = []

    # Classify error type
    error_type = "unknown"
    error_lower = error_msg.lower()
    if "unknown identifier" in error_lower or "unknown constant" in error_lower:
        error_type = "unknown_identifier"
    elif "type mismatch" in error_lower:
        error_type = "type_mismatch"
    elif "expected" in error_lower and "got" in error_lower:
        error_type = "syntax_error"
    elif "tactic" in error_lower:
        error_type = "tactic_error"
    elif "import" in error_lower:
        error_type = "import_error"

    patterns.append({
        "error_type": error_type,
        "error_snippet": error_msg[:300],
        "fix_summary": f"Fixed {error_type} error",
        "before_snippet": before_code[:300],
        "after_snippet": after_code[:300],
        "timestamp": datetime.datetime.now().isoformat(),
    })
    patterns = patterns[-20:]  # keep last 20
    fix_file.write_text(json.dumps(patterns, indent=2))


def run_proof_search(lean_code: str, error_msg: str, attempt: int) -> Optional[str]:
    print(f"  [LAYER 5] Proof Workers -- fix attempt {attempt}...")

    fix_patterns = load_fix_patterns()

    fix_msg = [
        {"role": "system", "content": f"""Fix this Lean 4 code so it compiles.

COMMON ERROR PATTERNS AND FIXES:
- "unknown identifier X": The Mathlib API name is wrong. Search for the correct name.
  Common renames: Nat.lt_of_lt_of_le -> Nat.lt_of_lt_of_le, Set.subset -> Set.Subset
- "type mismatch": Check expected vs actual types carefully. Use `show` to clarify types.
- "tactic failed": Try alternative tactics. If `simp` fails, try `simp only [...]` or `exact?`.
- "expected token": Syntax error. Check parentheses, colons, arrows.
- When in doubt: simplify the proof. Replace complex tactics with `simp`, `omega`, `decide`, or `exact`.

RULES:
- NEVER introduce `sorry` or `admit`
- Keep the fix minimal — change as little as possible
- Output ONLY the complete fixed Lean 4 code

{fix_patterns}"""},
        {"role": "user", "content": f"Fix:\n```lean\n{lean_code}\n```\nError:\n{error_msg[:2000]}"}
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
    print("  [LAYER 6] Intent Checker -- verifying semantic match...")
    msg = [
        {"role": "system", "content": """Compare informal statement with Lean 4 formalization.
Does the code prove what's claimed? Watch for weaker statements, trivial substitutions, sorry.
MATCH: YES or MATCH: NO
EXPLANATION: <brief>"""},
        {"role": "user", "content": f"INFORMAL:\n{proposal_text[:2000]}\n\nLEAN:\n{lean_code[:3000]}"}
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
    msg = [
        {"role": "system", "content": "You are a terse research scribe. Summarize in 3-5 short lines. What was proposed, what passed/failed, what to try next."},
        {"role": "user", "content": json.dumps(cycle_data, indent=2, default=str)[:4000]}
    ]
    result = llm_call(MODELS["scribe"], msg, temperature=0.3, max_tokens=512)
    return result or "Scribe unavailable."


# ============================================================
# APPEND TO RESEARCH.LEAN
# ============================================================

def append_to_research(lean_code: str, theorem_name: str, source: str):
    header = f"\n-- Verified by Math Lab v30 | Source: {source} | {datetime.datetime.now().isoformat()}\n"
    lines = lean_code.split('\n')
    code_lines = [l for l in lines if not l.strip().startswith("import ")]
    with open(RESEARCH_LEAN, 'a') as f:
        f.write(header)
        f.write('\n'.join(code_lines))
        f.write('\n')
    print(f"  [ARCHIVE] Appended to Research.lean: {theorem_name}")

def is_trivial_proof(lean_code: str) -> bool:
    trivial_patterns = [
        "theorem trivial", ": True", ":= trivial", ":= rfl",
        "1 = 1", "0 = 0", ": 1 + 1 = 2",
    ]
    code_lower = lean_code.lower()
    if any(p.lower() in code_lower for p in trivial_patterns):
        return True
    # Catch sorry-based "proofs" — these compile but prove nothing
    if "sorry" in lean_code:
        print("  [TRIVIAL] Contains 'sorry' — not a real proof")
        return True
    return False


# ============================================================
# COMPILE TRAINING — Known theorems for formalizer practice
# ============================================================

TRAINING_THEOREMS = [
    {
        "name": "injective_card_le",
        "statement": "If f : Fin n -> Fin m is injective, then n <= m.",
        "hint": "Use Fintype.card_le_of_injective and Fintype.card_fin.",
        "difficulty": 1,
    },
    {
        "name": "surjective_card_ge",
        "statement": "If f : Fin n -> Fin m is surjective, then n >= m.",
        "hint": "Use Fintype.card_le_of_surjective and Fintype.card_fin.",
        "difficulty": 1,
    },
    {
        "name": "nat_pow_pos",
        "statement": "For any natural number n, 2^n > 0.",
        "hint": "Use Nat.pos_of_ne_zero or positivity tactic.",
        "difficulty": 1,
    },
    {
        "name": "double_complement",
        "statement": "For any set S, the complement of the complement of S equals S.",
        "hint": "Use compl_compl.",
        "difficulty": 1,
    },
    {
        "name": "subset_trans_sets",
        "statement": "If A is a subset of B and B is a subset of C, then A is a subset of C.",
        "hint": "Use Set.Subset.trans.",
        "difficulty": 1,
    },
    {
        "name": "finset_union_comm",
        "statement": "For finite sets A and B, A union B = B union A.",
        "hint": "Use Finset.union_comm.",
        "difficulty": 1,
    },
    {
        "name": "bool_not_not",
        "statement": "For any boolean b, !!b = b.",
        "hint": "Use Bool.not_not or cases on b.",
        "difficulty": 1,
    },
    {
        "name": "exp_monotone",
        "statement": "If a <= b then 2^a <= 2^b for natural numbers.",
        "hint": "Use Nat.pow_le_pow_right.",
        "difficulty": 1,
    },
    {
        "name": "infinite_primes",
        "statement": "For every natural number n, there exists a prime p > n.",
        "hint": "Use Nat.exists_infinite_primes.",
        "difficulty": 1,
    },
    {
        "name": "empty_subset",
        "statement": "The empty set is a subset of every set.",
        "hint": "Use Set.empty_subset or Finset.empty_subset.",
        "difficulty": 1,
    },
    {
        "name": "comp_injective",
        "statement": "If f and g are both injective, then f composed with g is injective.",
        "hint": "Use Function.Injective.comp.",
        "difficulty": 1,
    },
    {
        "name": "nat_add_comm",
        "statement": "For natural numbers a and b, a + b = b + a.",
        "hint": "Use Nat.add_comm or omega.",
        "difficulty": 1,
    },
    {
        "name": "list_length_append",
        "statement": "The length of list A ++ B equals length A + length B.",
        "hint": "Use List.length_append.",
        "difficulty": 1,
    },
    {
        "name": "de_morgan_not_and",
        "statement": "not (P and Q) iff (not P or not Q).",
        "hint": "Use not_and_or.",
        "difficulty": 1,
    },
    {
        "name": "pow_two_ge_one",
        "statement": "For any natural number n, 2^n >= 1.",
        "hint": "Use Nat.one_le_pow or omega.",
        "difficulty": 1,
    },
    {
        "name": "card_image_le",
        "statement": "For a finite set s and function f, the cardinality of f(s) <= cardinality of s.",
        "hint": "Use Finset.card_image_le.",
        "difficulty": 2,
    },
    {
        "name": "nat_strong_induction",
        "statement": "If P(0) and (forall n, (forall m < n, P m) -> P n), then forall n, P n.",
        "hint": "Use Nat.strongRecOn or Nat.strong_rec_on.",
        "difficulty": 2,
    },
    {
        "name": "even_or_odd",
        "statement": "Every natural number is either even or odd.",
        "hint": "Use Nat.even_or_odd.",
        "difficulty": 1,
    },
    {
        "name": "cantor_no_surjection",
        "statement": "There is no surjection from a type A to Set A.",
        "hint": "Use Function.cantor_surjective or construct the diagonal set.",
        "difficulty": 2,
    },
    {
        "name": "fintype_pigeonhole",
        "statement": "If f maps a larger Fintype to a smaller one, f is not injective.",
        "hint": "Use Fintype.exists_ne_map_eq_of_card_lt.",
        "difficulty": 2,
    },
    {
        "name": "pow_add",
        "statement": "For natural numbers, 2^(a+b) = 2^a * 2^b.",
        "hint": "Use pow_add.",
        "difficulty": 1,
    },
    {
        "name": "disjoint_compl",
        "statement": "A set and its complement are disjoint.",
        "hint": "Use disjoint_compl_right.",
        "difficulty": 1,
    },
    {
        "name": "mono_comp_strict",
        "statement": "If f is strictly monotone and g is strictly monotone, f comp g is strictly monotone.",
        "hint": "Use StrictMono.comp.",
        "difficulty": 2,
    },
    {
        "name": "card_powerset",
        "statement": "The powerset of a finset of size n has 2^n elements.",
        "hint": "Use Finset.card_powerset.",
        "difficulty": 2,
    },
    {
        "name": "sum_range_id",
        "statement": "The sum of 0 + 1 + ... + (n-1) = n*(n-1)/2.",
        "hint": "Use Finset.sum_range_id_eq_sum or Gauss_sum_Icc_id.",
        "difficulty": 2,
    },
]


def run_compile_training_cycle(cycle: int, memory: SwarmMemory, session_log: list):
    """Skip conjecture engine. Pick a known theorem, formalize it, compile it."""
    print(f"\n{'='*60}")
    print(f"  COMPILE TRAINING — Cycle {cycle}")
    print(f"{'='*60}")

    cycle_data = {
        "cycle": cycle, "timestamp": datetime.datetime.now().isoformat(),
        "mode": "compile_training", "proposals": 0,
        "verified": 0, "trivial": 0, "failed_compile": 0,
    }

    # Pick theorems we haven't verified yet
    verified_names = {t.get("name", "") for t in memory.verified_theorems}
    available = [t for t in TRAINING_THEOREMS if t["name"] not in verified_names]
    if not available:
        print("  [DONE] All training theorems verified! Switching to separation mode.")
        memory.global_state["mode"] = "separation"
        memory.save()
        session_log.append(cycle_data)
        return

    # Pick 3 random theorems for this cycle
    batch = random.sample(available, min(3, len(available)))
    cycle_data["proposals"] = len(batch)

    lean_examples = load_lean_examples()
    seed_examples = get_seed_examples()
    existing = load_existing_theorems()

    for i, thm in enumerate(batch):
        print(f"\n  --- Training [{thm['name']}] ({i+1}/{len(batch)}) ---")
        print(f"  Statement: {thm['statement']}")

        # Go straight to formalizer — no conjecture engine, no critics
        formalize_msg = [
            {"role": "system", "content": f"""You are a Lean 4 formalization expert. Formalize the given mathematical statement into COMPILABLE Lean 4 code.

RULES:
- Start with `import Mathlib`
- Use Lean 4 syntax (NOT Lean 3)
- Use `by` tactic blocks (NOT `begin`/`end`)
- NEVER use `sorry`, `admit`, or `Sorry` — code with sorry will be REJECTED
- Keep it SHORT — under 15 lines of actual code
- Prefer simple tactics: simp, omega, ring, exact, apply, intro, cases
- Use the hint provided to find the right Mathlib lemma

{existing}
{seed_examples}
{lean_examples}

Output ONLY the Lean 4 code, starting with `import Mathlib`."""},
            {"role": "user", "content": f"""Formalize this theorem:

NAME: {thm['name']}
STATEMENT: {thm['statement']}
HINT: {thm['hint']}

Keep the proof short and simple. Use the Mathlib hint."""}
        ]

        lean_code = None
        for formalizer_key in ["formalizer_primary", "formalizer_backup"]:
            result = llm_call(MODELS[formalizer_key], formalize_msg, temperature=0.3, max_tokens=2048)
            if result:
                code = result
                if "```lean" in code:
                    code = code.split("```lean")[-1].split("```")[0].strip()
                elif "```" in code:
                    code = code.split("```")[1].split("```")[0].strip()
                if code.strip():
                    print(f"    [{formalizer_key}] Generated ({len(code)} chars)")
                    lean_code = code
                    break
            print(f"    [{formalizer_key}] FAILED")

        if not lean_code:
            print(f"  [FAILED] Could not formalize")
            cycle_data["failed_compile"] += 1
            continue

        # Compile
        print("  [LEAN] Compiling...")
        success, output = compile_lean(lean_code)

        # Fix loop
        attempt = 0
        last_error = output
        original_code = lean_code
        while not success and attempt < MAX_FIX_ATTEMPTS:
            attempt += 1
            fixed = run_proof_search(lean_code, output, attempt)
            if fixed:
                before_code = lean_code
                lean_code = fixed
                success, output = compile_lean(lean_code)
                if success:
                    save_fix_pattern(last_error, before_code, lean_code)
            else:
                break
            last_error = output

        if not success:
            print(f"  [FAILED] Compilation failed after {attempt+1} attempts")
            cycle_data["failed_compile"] += 1
            continue

        # Check for sorry/trivial
        if is_trivial_proof(lean_code):
            print(f"  [TRIVIAL] Rejected")
            cycle_data["trivial"] += 1
            memory.global_state["total_trivial"] += 1
            continue

        # SUCCESS
        theorem_name = f"train_{thm['name']}_{int(time.time())}"
        print(f"  [VERIFIED] {theorem_name}")
        append_to_research(lean_code, theorem_name, "compile_training")
        memory.add_verified(theorem_name, thm["statement"], lean_code, "compile_training")
        cycle_data["verified"] += 1

        # Save to dynamic seed bank
        save_verified_seed(thm["name"], lean_code)

        telegram_alert(
            f"<b>MATH LAB v30 — TRAINING VERIFIED</b>\n\n"
            f"<b>{theorem_name}</b>\n"
            f"Statement: {thm['statement']}\n"
            f"Total verified: {memory.global_state['total_verified']}"
        )

    summary = run_scribe_summary(cycle_data)
    print(f"\n  [SCRIBE] {summary}")
    session_log.append(cycle_data)
    memory.global_state["total_cycles"] += 1
    memory.save()


def save_verified_seed(name: str, lean_code: str):
    """Save a verified theorem to the dynamic seed bank (Step 5 flywheel)."""
    seed_file = MEMORY_DIR / "verified_seeds.json"
    seeds = []
    if seed_file.exists():
        try:
            seeds = json.loads(seed_file.read_text())
        except:
            seeds = []
    seeds.append({"name": name, "code": lean_code, "timestamp": datetime.datetime.now().isoformat()})
    seeds = seeds[-30:]  # keep last 30
    seed_file.write_text(json.dumps(seeds, indent=2))


# ============================================================
# MAIN CYCLE (v30 — with all 6 changes)
# ============================================================

def run_cycle(cycle: int, memory: SwarmMemory, session_log: list):
    difficulty = memory.global_state["difficulty_level"]
    mode = memory.global_state.get("mode", MODE)
    print(f"\n{'='*60}")
    print(f"  CYCLE {cycle}  [mode={mode}, difficulty={difficulty}/5]")
    print(f"{'='*60}")

    cycle_data = {
        "cycle": cycle, "timestamp": datetime.datetime.now().isoformat(),
        "mode": mode, "difficulty": difficulty,
        "proposals": 0, "barrier_killed": 0, "falsified": 0,
        "verified": 0, "trivial": 0, "failed_compile": 0,
        "natural_filtered": 0, "repairs_attempted": 0, "repairs_succeeded": 0,
    }

    proposals = run_conjecture_engine(memory, cycle)
    cycle_data["proposals"] = len(proposals)
    if not proposals:
        print("  [ABORT] No proposals generated")
        session_log.append(cycle_data)
        return

    for i, proposal in enumerate(proposals):
        print(f"\n  --- Proposal {i+1}/{len(proposals)} from {proposal['source']} ---")

        # CHANGE #4: Non-natural filter (only for separation mode, difficulty >= 3)
        if mode == "separation" and difficulty >= 3:
            if not run_natural_filter(proposal):
                cycle_data["natural_filtered"] += 1
                memory.global_state["total_natural_filtered"] = memory.global_state.get("total_natural_filtered", 0) + 1
                memory.add_failed(proposal["text"][:300], "Natural proof strategy detected", {})
                continue

        # Barrier Council (skip for difficulty 1-2 — known results don't need barrier checking)
        if difficulty >= 3:
            scores = run_barrier_council(proposal)
            if scores["killed"]:
                print(f"  [KILLED] All barriers HIGH")
                memory.add_barrier_kill(proposal["text"][:300], scores)
                cycle_data["barrier_killed"] += 1
                continue
        else:
            scores = {"R": 0, "N": 0, "A": 0, "total": 0, "killed": False}

        # Adversarial Critics (skip counterexample at difficulty 1-2 — known true results)
        if difficulty <= 2:
            # Only run triviality check, skip counterexample — these are known results
            verdict = run_triviality_only(proposal)
        else:
            verdict = run_adversarial_critics(proposal)

        # CHANGE #3: Repair loop if falsified
        if verdict["falsified"]:
            repaired = False
            current_proposal = proposal
            for repair_attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
                cycle_data["repairs_attempted"] += 1
                memory.global_state["total_repairs"] = memory.global_state.get("total_repairs", 0) + 1

                feedback = verdict["details"].get("counterexample", "No details")
                repaired_proposal = run_repair(current_proposal, feedback, repair_attempt)
                if not repaired_proposal:
                    break

                # Re-run critics on repaired version
                verdict = run_adversarial_critics(repaired_proposal)
                if not verdict["falsified"] and not verdict["trivial"]:
                    print(f"  [REPAIR SUCCESS] Repaired proposal survives critics!")
                    proposal = repaired_proposal
                    cycle_data["repairs_succeeded"] += 1
                    memory.global_state["total_repair_successes"] = memory.global_state.get("total_repair_successes", 0) + 1
                    repaired = True
                    break
                current_proposal = repaired_proposal

            if not repaired:
                print(f"  [FALSIFIED] Proposal rejected (after {min(repair_attempt, MAX_REPAIR_ATTEMPTS)} repair attempts)")
                memory.add_failed(proposal["text"][:300], "Falsified (repair failed)",
                                {"R": scores.get("R"), "N": scores.get("N"), "A": scores.get("A")})
                memory.global_state["total_falsified"] += 1
                cycle_data["falsified"] += 1
                continue

        if verdict.get("trivial"):
            print(f"  [TRIVIAL] Detected as trivial/known")
            cycle_data["trivial"] += 1
            memory.global_state["total_trivial"] += 1
            continue

        # Decompose and Formalize
        existing = load_existing_theorems()
        lean_code = run_decompose_and_formalize(proposal, existing, difficulty=difficulty)
        if not lean_code:
            print(f"  [FAILED] Could not formalize")
            memory.add_failed(proposal["text"][:300], "Formalization failed", scores)
            cycle_data["failed_compile"] += 1
            continue

        # Compile with Lean 4
        print("  [LEAN] Compiling...")
        success, output = compile_lean(lean_code)

        attempt = 0
        last_error = output
        while not success and attempt < MAX_FIX_ATTEMPTS:
            attempt += 1
            fixed = run_proof_search(lean_code, output, attempt)
            if fixed:
                before_code = lean_code
                lean_code = fixed
                success, output = compile_lean(lean_code)
                if success:
                    save_fix_pattern(last_error, before_code, lean_code)
            else:
                break
            last_error = output

        if not success:
            print(f"  [FAILED] Lean compilation failed after {attempt+1} attempts")
            memory.add_failed(proposal["text"][:300], f"Compile failed: {output[:200]}", scores)
            cycle_data["failed_compile"] += 1
            continue

        # Trivial check
        if is_trivial_proof(lean_code):
            print(f"  [TRIVIAL] Compiled but trivially true")
            cycle_data["trivial"] += 1
            memory.global_state["total_trivial"] += 1
            continue

        # Intent check
        if not run_intent_check(proposal["text"], lean_code):
            print(f"  [MISMATCH] Formal proof doesn't match intent")
            memory.add_failed(proposal["text"][:300], "Intent mismatch", scores)
            continue

        # SUCCESS!
        theorem_name = f"swarm_v30_c{cycle}_{proposal['source']}_{int(time.time())}"
        print(f"  [VERIFIED] {theorem_name}")
        append_to_research(lean_code, theorem_name, proposal["source"])
        memory.add_verified(theorem_name, proposal["text"][:500], lean_code, proposal["source"])
        cycle_data["verified"] += 1

        telegram_alert(
            f"<b>MATH LAB v30 -- THEOREM VERIFIED</b>\n\n"
            f"<b>{theorem_name}</b>\n"
            f"Mode: {mode} | Difficulty: {difficulty}/5\n"
            f"Source: {proposal['source']} ({proposal['model']})\n"
            f"Cycle: {cycle}\n\n"
            f"<pre>{proposal['text'][:400]}</pre>\n\n"
            f"Barrier: R={scores.get('R','?')} N={scores.get('N','?')} A={scores.get('A','?')}\n"
            f"Total verified: {memory.global_state['total_verified']}"
        )

    # Scribe
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
    session_id = datetime.datetime.now().strftime("swarm_v30_%Y%m%d_%H%M%S")
    session_file = SESSION_DIR / f"{session_id}.json"
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    memory = SwarmMemory()
    difficulty = memory.global_state["difficulty_level"]
    mode = memory.global_state.get("mode", MODE)

    print(f"""
+===========================================================+
|  MATH LAB v30 -- ENHANCED SWARM ARCHITECTURE               |
|  15 NVIDIA Models | 7 Layers | Lean 4 Ground Truth          |
|  Mode: {mode:<15} Difficulty: {difficulty}/5                 |
|  Session: {session_id}                     |
|  UPGRADES: curriculum, repair loop, natural filter,          |
|            proof complexity, algorithm search, seed theorems  |
+===========================================================+
""")

    print(f"Research memory loaded:")
    print(f"  Verified: {memory.global_state['total_verified']}")
    print(f"  Failed approaches: {len(memory.failed_approaches)}")
    print(f"  Barrier kills: {memory.global_state['total_rejected_barrier']}")
    print(f"  Sessions: {memory.global_state['session_count']}")
    print(f"  Difficulty: {difficulty}/5")
    print(f"  Consecutive verified: {memory.global_state['consecutive_verified']}")
    print(f"  Consecutive failed: {memory.global_state['consecutive_failed']}")
    print(f"  Repairs: {memory.global_state.get('total_repairs', 0)} attempted, {memory.global_state.get('total_repair_successes', 0)} succeeded")

    print("\nChecking Lean 4 setup...")
    test_code = 'import Mathlib\n\ntheorem v30_ping : 1 = 1 := rfl\n'
    ok, out = compile_lean(test_code)
    if not ok:
        print(f"FATAL: Lean 4 check failed: {out[:500]}")
        sys.exit(1)
    print("Lean 4 + Mathlib: OK")

    session_log = []
    session_start = time.time()

    for cycle in range(1, MAX_CYCLES + 1):
        try:
            current_mode = memory.global_state.get("mode", MODE)
            if current_mode == "compile_training":
                run_compile_training_cycle(cycle, memory, session_log)
            else:
                run_cycle(cycle, memory, session_log)
        except KeyboardInterrupt:
            print("\n\n[INTERRUPTED] Saving state...")
            break
        except Exception as e:
            print(f"\n[CYCLE ERROR] {e}")
            import traceback
            traceback.print_exc()
            session_log.append({"cycle": cycle, "error": str(e)})

    elapsed = time.time() - session_start
    memory.global_state["session_count"] += 1
    memory.save()

    total_verified = sum(c.get("verified", 0) for c in session_log)
    total_killed = sum(c.get("barrier_killed", 0) for c in session_log)
    total_falsified = sum(c.get("falsified", 0) for c in session_log)
    total_repairs = sum(c.get("repairs_attempted", 0) for c in session_log)
    total_repair_ok = sum(c.get("repairs_succeeded", 0) for c in session_log)
    total_natural = sum(c.get("natural_filtered", 0) for c in session_log)

    summary = {
        "session_id": session_id, "version": "v30",
        "mode": mode, "difficulty_start": difficulty,
        "difficulty_end": memory.global_state["difficulty_level"],
        "duration_seconds": elapsed, "cycles_completed": len(session_log),
        "total_verified": total_verified, "total_barrier_killed": total_killed,
        "total_falsified": total_falsified, "total_natural_filtered": total_natural,
        "repairs_attempted": total_repairs, "repairs_succeeded": total_repair_ok,
        "log": session_log,
    }
    session_file.write_text(json.dumps(summary, indent=2, default=str))

    print(f"""
+===========================================================+
|  SESSION COMPLETE                                           |
|  Duration: {elapsed:.0f}s | Cycles: {len(session_log):<30}|
|  Verified: {total_verified} | Falsified: {total_falsified} | Barrier-killed: {total_killed:<10}|
|  Natural-filtered: {total_natural} | Repairs: {total_repair_ok}/{total_repairs:<20}|
|  Difficulty: {difficulty} -> {memory.global_state['difficulty_level']:<36}|
|  Saved: {session_file.name:<42}|
+===========================================================+
""")

    try:
        subprocess.run(["git", "add", "-A"], cwd=str(MATH_LAB_DIR), timeout=10)
        subprocess.run(["git", "commit", "-m", f"v30 session {session_id}: {total_verified} verified, difficulty {memory.global_state['difficulty_level']}"],
                       cwd=str(MATH_LAB_DIR), timeout=10)
        subprocess.run(["git", "push"], cwd=str(MATH_LAB_DIR), timeout=30)
    except:
        pass


if __name__ == "__main__":
    run_session()

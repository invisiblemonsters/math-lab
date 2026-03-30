# Math Lab v30 — Formalizer Improvement Plan

## Goal
Get the verification rate from ~1/40 cycles to something meaningful (target: 1/5 cycles at difficulty 1) so the curriculum can actually promote through levels.

## Current State
- v30 running, all 6 upgrades deployed
- 1 verified theorem in ~40 v30 cycles
- Pipeline flows: proposals pass triviality -> decompose -> formalize -> FAIL at Lean compile
- Proof workers fix attempts also mostly fail
- Occasional intent mismatches when code does compile
- Difficulty stuck at 1/5

## Root Cause Analysis
The formalizer receives a 14-15K char decomposition and tries to produce valid Lean 4 + Mathlib code in one shot. This fails because:
1. Decompositions are too ambitious for what the formalizer can translate
2. Formalizer doesn't know Mathlib's actual API surface well enough
3. Proof workers are guessing at fixes without understanding the error patterns
4. 10 seed theorems aren't enough context

## Plan — 5 Steps, One at a Time

### Step 1: Study the Success
**What:** Extract the one verified theorem, analyze what made it work.
**How:** Read Research.lean for the v30 entry. Look at: how long was the Lean code? How complex was the statement? What proof tactics were used? What model produced it?
**Why:** We need to understand our one success to replicate it.
**Validation:** Document the pattern in a "winning formula" that informs later steps.

### Step 2: Compile-First Mode (Formalizer Training Wheels)
**What:** Add a new mode where we skip conjecture generation entirely. Instead, take the seed theorems (and a curated list of 20-30 known Lean 4 theorem statements) and just try to formalize + compile them. Pure formalizer practice.
**How:** New function `run_compile_training_cycle()` that:
  - Picks a known theorem statement from a curated list
  - Sends it directly to the formalizer with the statement already written
  - Compiles, fixes, compiles again
  - Every success gets appended to Research.lean AND added to the formalizer's example bank
  - This builds up the seed library organically
**Why:** The formalizer needs more examples of what actually compiles. Right now it has 10 seeds + whatever's in Research.lean. Every successful compilation teaches it.
**Validation:** Run 15 cycles in compile-training mode. Target: 5+ successful compilations.
**File changes:** pnp-swarm-v30.py — add compile_training mode, curated theorem list

### Step 3: Constrain Decomposition Size
**What:** The decomposer produces 14-15K char plans. These are too complex. Force it to produce simpler, shorter plans.
**How:** 
  - Add max_tokens=2048 to decomposer call (currently 4096)
  - Add to decomposer prompt: "Keep decomposition under 5 subgoals. Prefer SIMPLE proofs that use basic Mathlib tactics (simp, omega, ring, exact, apply). Do NOT propose complex multi-lemma architectures."
  - At difficulty 1, add: "The proof should be achievable in under 20 lines of Lean 4."
**Why:** Shorter, simpler decompositions = formalizer has a chance of producing compilable code.
**Validation:** Check that decompositions drop from 14K to under 4K chars. Track compile success rate.
**File changes:** pnp-swarm-v30.py — modify decomposer prompt and max_tokens

### Step 4: Smarter Proof Workers
**What:** Proof workers currently get the code + error and try to fix blindly. Give them patterns.
**How:**
  - Maintain a `common_errors.json` file that maps Lean error patterns to known fixes
  - After each successful proof worker fix (code compiles after fix), save the error pattern + fix
  - Feed the last 5 successful fix patterns to proof workers as few-shot examples
  - Add specific rules: "If error mentions 'unknown identifier', check Mathlib import names. If 'type mismatch', check the expected vs actual types carefully."
**Why:** The proof workers keep producing the same broken fixes. Learning from past successes will improve their hit rate.
**Validation:** Track proof worker success rate (fixes that lead to compilation). Target: 30%+ fix success rate.
**File changes:** pnp-swarm-v30.py — modify run_proof_search, add error pattern tracking

### Step 5: Dynamic Seed Library
**What:** Every verified theorem automatically becomes a seed example for the formalizer. The seed bank grows with each success.
**How:**
  - After verification, extract the Lean code and add it to a `verified_seeds.json`
  - `get_seed_examples()` loads from both the hardcoded SEED_THEOREMS and verified_seeds.json
  - Cap at 30 examples (most recent), rotate oldest out
  - This creates a flywheel: more verifications -> better examples -> more verifications
**Why:** The current 10 static seeds are stale. A growing library of ACTUALLY COMPILED code is the best teacher.
**Validation:** After 10 verifications, the formalizer should be producing compilable code more often.
**File changes:** pnp-swarm-v30.py — modify get_seed_examples, add verified_seeds.json management

## Execution Order
1 -> 2 -> 3 -> 4 -> 5 (each builds on the last)

Steps 2+3 are the highest leverage — they directly address why proposals fail at compilation.
Steps 4+5 create compounding improvement over time.

## Risks
- Compile-first mode might be "too easy" and not teach the formalizer to handle real conjectures
- Over-constraining decomposition might prevent formalization of genuinely interesting results
- Proof worker pattern matching could overfit to specific error types

## Open Questions
- Should we try a different formalizer model? Mathstral-7B is the backup but has context limits. Are there better Lean-specific models on NVIDIA?
- Should difficulty 1 just be compile-training mode by default?

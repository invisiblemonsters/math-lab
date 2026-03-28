# GPT 5.4 Swarm Architecture Proposal - Part 1
# Source: Email from Chris Powers, 2026-03-28
# Subject: "Pt 1"

## Summary

Formal-first layered research machine for frontier mathematical discovery.

## Core Principles
- Formal-first, not text-first (Lean at center)
- Informal reasoning is cheap/creative but untrusted
- Formal proof artifacts are expensive but canonical
- Swarm moves ideas: vague → structured → formal → verified

## Seven Layers
1. Problem framing
2. Knowledge and corpus
3. Conjecture and decomposition
4. Proof search
5. Formal verification
6. Adversarial critique / barrier-check
7. Synthesis and research-memory

## Agent Roles (A-J)
A. Orchestrator - budget allocation, branch management, abandon decisions
B. Librarian/Corpus - mathlib, LMFDB, dependency graphs, premise selection
C. Problem Framer/Autoformalizer - informal→formal translation (KEY CHOKEPOINT)
D. Conjecture Engine (4 sub-agents):
   1. Variation agent (perturb hypotheses/quantifiers)
   2. Analogy agent (cross-theory pattern import)
   3. Counterexample-aware conjecturer (cheap falsification)
   4. Domain-specific conjecturer (trained on local corpora)
E. Decomposer/Lemma Planner - subgoal generation, staged attacks
F. Proof Search (4 species):
   1. Tactic-level formal prover (Lean tactics + premise selection)
   2. RL-based prover (AlphaProof-style)
   3. Natural-language sketch prover
   4. Specialist solvers (geometry, SMT/SAT/ATP, symbolic algebra)
G. Verifiers (4 types):
   1. Formal proof checker (kernel)
   2. Semantic consistency checker (formal matches intent?)
   3. Independent re-prover (different route)
   4. Counterexample/model finder
H. Adversarial Critic / Barrier Agent
   - Trivially check, library duplication, edge cases
   - Barrier-aware: natural-proofs critic, relativization critic, known-obstruction critic
I. Experiment/Example Generator - numeric/symbolic experiments, parameter families
J. Scribe/Compression Agent - proof traces → human-readable narratives

## Five Core Loops
1. Conjecture → Falsify → Refine (cheap filter before proof search)
2. Informal sketch → Formalization → Kernel check (BACKBONE)
3. Lemma mining (stall → propose auxiliaries → filter → prove)
4. Related-problem curriculum (AlphaProof-style RL on variants)
5. Discovery → Formal archive → Reuse (compounding library)

## Three Memories
A. Global research memory (solved, failed, barriers, heuristics)
B. Branch-local working memory (hypotheses, candidates, failures per branch)
C. Formal memory (Lean files, declarations, dependency graph, provenance)

## Toolchain
- Lean 4 + mathlib (primary)
- Coq / Isabelle/HOL / ATP/SMT (secondary)
- LeanConjecturer-style conjecture generation
- RL-based proof worker (AlphaProof paradigm)
- Retrieval/index over mathlib + LMFDB
- Research notebook / provenance system

## Success Metrics
- Verified theorem yield
- Interestingness / novelty
- Lemma reuse value
- Formalization quality
- Human comprehensibility
- Time-to-counterexample on false conjectures
- Compounding library growth

## Bottom Line
"LLMs for imagination, RL/search for persistence, proof assistants for truth, 
adversarial critics for skepticism, formal libraries for memory."

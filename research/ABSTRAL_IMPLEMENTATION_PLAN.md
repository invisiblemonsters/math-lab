# ABSTRAL for Math Lab — Implementation Plan

## Paper
ABSTRAL: Automatic Design of Multi-Agent Systems Through Iterative Refinement and Topology Optimization
https://arxiv.org/abs/2603.22791

## What It Does
Meta-agent automatically discovers optimal multi-agent topologies by:
1. Building agent systems from a SKILL.md spec
2. Running them on tasks, capturing traces
3. Analyzing failures (5 evidence classes)
4. Updating the spec to fix failures
5. Outer loop forces structural diversity via graph edit distance

## What We Need

### Models (all on NVIDIA free API)
- **Meta-agent** (BUILD/ANALYZE/UPDATE): Needs the strongest reasoning model available
  - Best: nvidia/llama-3.1-nemotron-ultra-253b-v1 (reasoning model, chain-of-thought)
  - Backup: meta/llama-3.1-405b-instruct
- **Agent backbone** (the actual math agents): Multiple models for diversity
  - meta/llama-3.1-405b-instruct (proposer)
  - meta/llama-3.3-70b-instruct (formalizer/fast roles)
  - nvidia/llama-3.1-nemotron-ultra-253b-v1 (reasoning-heavy roles)
  - qwen/qwen2.5-coder-32b-instruct (code generation roles)
  - mistralai/mixtral-8x22b-instruct-v0.1 (diverse architecture)
- **Multiple NVIDIA API keys** needed for parallel agent execution within a single run

### Infrastructure (already have)
- Lean 4 + Mathlib4 (installed at ~/.elan/, project at ~/mathlib_test/)
- Python 3.11
- The verification signal (Lean compiler) is BETTER than their SOPBench oracle — binary, deterministic, with diagnostic error messages

### Software to Build
1. **Agent graph framework** — LangGraph equivalent but simpler, just needs:
   - Agent nodes with system prompts + model assignment
   - Directed edges for message passing
   - Router nodes for conditional branching
   - Execution trace capture (can be simple JSON logging, no OpenTelemetry needed)

2. **Meta-agent loop** — the SKILL.md read/analyze/update cycle:
   - SKILL.md with 4 sections: K (domain knowledge), R (topology reasoning), T (role templates), P (construction protocol)
   - Evidence classifier (EC1-EC5) — can be a prompted LLM call
   - Convergence detector (skill diff, pass rate plateau, evidence distribution)

3. **Outer loop** — diversity enforcement:
   - Graph edit distance computation (networkx has this)
   - Role embedding + cosine distance (can use a simple embedding or just string comparison)
   - Seed mutation for new topology families

4. **Task suite** — theorem proving tasks with known difficulty levels:
   - Easy: basic Nat/List lemmas (should compile first try)
   - Medium: set theory, function composition (may need retries)
   - Hard: complexity theory lemmas (current frontier)
   - Use ~40 tasks for validation, hold out harder ones for test

### Estimated Build Time
- Agent graph framework: 1-2 sessions
- Meta-agent loop: 1-2 sessions  
- Outer loop + diversity: 1 session
- Task suite curation: 1 session
- Integration + first run: 1 session
- Total: ~5-7 sessions

### Estimated Run Cost
- Paper spent $5.50 for 24 iterations over 28 hours
- We'd be ~$0 (NVIDIA free API) but need multiple API keys for parallelism
- Wall clock: ~24-48 hours per full outer loop (3-5 topology families)
- Each NVIDIA key gives limited rate — more keys = faster parallel execution

### What ABSTRAL Might Discover For Us
- Debate topology: two proposers with different strategies, judge selects best
- Pre-check agent: validates proof sketch feasibility before formal compilation
- Counterexample agent: tries to disprove before proving
- Theorem decomposer: breaks complex theorems into lemma chains
- Different topologies per theorem type (algebraic vs combinatorial vs analysis)
- Feedback router: sends compiler errors to different specialists based on error type

### Key Insight From Paper
Their pipeline topology (like ours) scored 55%. Ensemble topology scored 70%.
We might be leaving 15+ percentage points on the table with our linear pipeline.

## Priority
After current formal lab stabilizes and produces a solid base of verified theorems.
The verified theorem library IS the task suite for ABSTRAL — we need it first.

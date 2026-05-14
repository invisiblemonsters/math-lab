#!/usr/bin/env python3
"""
CDCL Arbitrage Router — DeFi route finder using Conflict-Driven Clause Learning.

Maps SAT solving to DeFi arbitrage:
  Variable ≡ Token pair direction
  Clause   ≡ Pool constraint (reserves, fee, slippage curve)
  Conflict ≡ Route is unprofitable after gas + slippage
  Learned  ≡ "Never route X→Y→Z when reserves < threshold"

Only dependency: Python stdlib + Base RPC for live pool data.
"""

import json, math, time, urllib.request
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════
# DOMAIN MODEL: Token Graph
# ═══════════════════════════════════════════════

@dataclass
class Token:
    symbol: str
    address: str
    decimals: int = 18

@dataclass
class Pool:
    """An AMM liquidity pool = a directed edge in the token graph."""
    token0: Token
    token1: Token
    reserve0: float  # in human-readable units
    reserve1: float
    fee: float  # e.g. 0.003 for 0.3%
    dex: str  # "uniswap_v3", "aerodrome", etc.
    address: str = ""
    
    def get_price(self, token_in: str) -> float:
        """Price of token_in in terms of the other token."""
        if token_in == self.token0.address:
            return self.reserve1 / self.reserve0 if self.reserve0 > 0 else float('inf')
        else:
            return self.reserve0 / self.reserve1 if self.reserve1 > 0 else float('inf')
    
    def get_output(self, token_in: str, amount_in: float) -> float:
        """Constant product AMM: how much token_out for amount_in of token_in."""
        if token_in == self.token0.address:
            reserve_in, reserve_out = self.reserve0, self.reserve1
        else:
            reserve_in, reserve_out = self.reserve1, self.reserve0
        
        amount_in_with_fee = amount_in * (1 - self.fee)
        if reserve_in <= 0 or reserve_out <= 0:
            return 0.0
        
        # x * y = k => (r_in + Δ_in)(r_out - Δ_out) = r_in * r_out
        # Δ_out = r_out * Δ_in / (r_in + Δ_in)
        return (reserve_out * amount_in_with_fee) / (reserve_in + amount_in_with_fee)


# ═══════════════════════════════════════════════
# KNOWN BASE TOKENS & POOLS
# ═══════════════════════════════════════════════

BASE_TOKENS = {
    "WETH": Token("WETH", "0x4200000000000000000000000000000000000006", 18),
    "USDC": Token("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
    "USDT": Token("USDT", "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", 6),
    "DAI":  Token("DAI",  "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", 18),  # placeholder
    "cbBTC": Token("cbBTC", "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8),
    "AERO": Token("AERO", "0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18),
    "DEGEN": Token("DEGEN", "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed", 18),
}

# Estimated Base pools (will be replaced with live data)
# Format: (token0, token1, reserve0, reserve1, fee, dex)
ESTIMATED_POOLS = [
    # WETH/USDC — the backbone
    ("WETH", "USDC", 5000, 17_500_000, 0.0005, "aerodrome"),     # ~$3500 ETH
    ("WETH", "USDC", 2000, 7_000_000, 0.003, "uniswap_v3"),
    # WETH/USDT
    ("WETH", "USDT", 1000, 3_500_000, 0.0005, "aerodrome"),
    # USDC/USDT — stable pair
    ("USDC", "USDT", 5_000_000, 5_000_000, 0.0001, "uniswap_v3"),
    # WETH/AERO
    ("WETH", "AERO", 500, 2_000_000, 0.003, "aerodrome"),
    # AERO/USDC
    ("AERO", "USDC", 1_000_000, 500_000, 0.003, "aerodrome"),
    # WETH/cbBTC
    ("WETH", "cbBTC", 200, 3, 0.003, "uniswap_v3"),
    # cbBTC/USDC
    ("cbBTC", "USDC", 5, 500_000, 0.003, "aerodrome"),
    # WETH/DEGEN
    ("WETH", "DEGEN", 100, 50_000_000, 0.01, "aerodrome"),
    # DEGEN/USDC
    ("DEGEN", "USDC", 10_000_000, 100_000, 0.01, "aerodrome"),
]


def build_pools(estimates=None):
    """Build pool objects from estimated or live data."""
    pools = []
    data = estimates or ESTIMATED_POOLS
    for sym0, sym1, r0, r1, fee, dex in data:
        t0 = BASE_TOKENS[sym0]
        t1 = BASE_TOKENS[sym1]
        pools.append(Pool(t0, t1, r0, r1, fee, dex))
    return pools


def build_token_graph(pools: list[Pool]) -> dict[str, dict[str, list[Pool]]]:
    """Build adjacency list: graph[token_a][token_b] = [pools connecting them]."""
    graph = {}
    for pool in pools:
        a, b = pool.token0.address, pool.token1.address
        graph.setdefault(a, {}).setdefault(b, []).append(pool)
        graph.setdefault(b, {}).setdefault(a, []).append(pool)
    return graph


# ═══════════════════════════════════════════════
# CDCL ROUTE FINDER
# ═══════════════════════════════════════════════

@dataclass
class LearnedConstraint:
    """A constraint learned from a failed (unprofitable) route.
    Maps to a learned clause in SAT: "don't take this combination." """
    path: tuple  # sequence of token addresses
    reason: str  # why it failed
    conditions: dict = field(default_factory=dict)  # e.g. min reserves needed

@dataclass 
class RouteState:
    """Current partial route being explored (like partial assignment in SAT)."""
    path: list[str]  # token addresses visited
    amount: float     # current amount of start token remaining
    start_amount: float
    start_token: str
    pnl: float = 0.0  # profit/loss in start token terms
    
    def copy(self):
        return RouteState(self.path[:], self.amount, self.start_amount, 
                         self.start_token, self.pnl)


class CDCLRouter:
    """CDCL-based arbitrage route finder.
    
    Explores token graph looking for profitable cycles.
    On conflict (unprofitable or no route), learns constraints
    that prune the search space — just like CDCL clause learning.
    """
    
    def __init__(self, pools: list[Pool], gas_cost_usd: float = 0.50):
        self.pools = pools
        self.graph = build_token_graph(pools)
        self.gas_cost_usd = gas_cost_usd
        self.learned_constraints: list[LearnedConstraint] = []
        self.stats = {"routes_evaluated": 0, "conflicts": 0, "learned": 0, "profitable": 0}
    
    def gas_in_native(self, eth_price: float = 3500) -> float:
        return self.gas_cost_usd / eth_price
    
    def find_routes(self, start_token: str, amount: float, max_depth: int = 4) -> list[dict]:
        """Find profitable arbitrage routes starting and ending at start_token."""
        self.stats = {"routes_evaluated": 0, "conflicts": 0, "learned": 0, "profitable": 0}
        state = RouteState([start_token], amount, amount, start_token)
        results = []
        self._dfs(state, max_depth, 0, results)
        return sorted(results, key=lambda r: r["net_pnl_usd"], reverse=True)
    
    def _dfs(self, state: RouteState, max_depth: int, depth: int, results: list):
        """Depth-first search with CDCL constraint checking."""
        current = state.path[-1]
        
        # Check if we've completed a cycle back to start
        if depth > 0 and current == state.start_token:
            self._evaluate_cycle(state, results)
            return
        
        if depth >= max_depth:
            return
        
        # Get all possible next tokens
        neighbors = self.graph.get(current, {})
        
        # CDCL: score and sort neighbors by pool attractiveness
        scored = []
        for next_token, pools in neighbors.items():
            score = self._pool_score(next_token, pools, state)
            scored.append((score, next_token, pools))
        
        # VSIDS-like: explore most attractive first
        scored.sort(key=lambda x: x[0], reverse=True)
        
        for score, next_token, pools in scored:
            # CDCL: check learned constraints before exploring
            if self._check_constraint(state, next_token):
                self.stats["conflicts"] += 1
                continue
            
            # Try each pool for this token pair
            for pool in pools:
                output = pool.get_output(current, state.amount)
                if output <= 0:
                    continue
                
                self.stats["routes_evaluated"] += 1
                
                new_state = state.copy()
                new_state.path.append(next_token)
                new_state.amount = output
                
                self._dfs(new_state, max_depth, depth + 1, results)
    
    def _evaluate_cycle(self, state: RouteState, results: list):
        """Check if a completed cycle is profitable."""
        # Net in start token terms
        net = state.amount - state.start_amount
        gas = self.gas_in_native()
        
        # Convert gas to start token if needed
        if state.start_token == BASE_TOKENS["WETH"].address:
            net_after_gas = net - gas
        elif state.start_token == BASE_TOKENS["USDC"].address:
            net_after_gas = net - self.gas_cost_usd / 1.0  # USDC ~ $1
        else:
            # Approximate: assume start token ~ ETH-priced
            eth_price = 3500
            gas_in_start = self.gas_cost_usd / eth_price
            net_after_gas = net - gas_in_start
        
        if net_after_gas > 0:
            self.stats["profitable"] += 1
            results.append({
                "path": [self._addr_to_symbol(a) for a in state.path],
                "start_amount": state.start_amount,
                "end_amount": state.amount,
                "gross_pnl": net,
                "gas_cost": self.gas_cost_usd,
                "net_pnl_usd": net_after_gas * 3500 if state.start_token == BASE_TOKENS["WETH"].address else net_after_gas,
                "depth": len(state.path) - 1,
            })
        else:
            # Learn a constraint from this unprofitable cycle
            self._learn(state, net_after_gas)
    
    def _learn(self, state: RouteState, loss: float):
        """Learn a constraint from a failed route (CDCL conflict analysis)."""
        # Identify the weakest link — the pool with worst price impact
        # and learn: "this path pattern is unprofitable when reserves < X"
        constraint = LearnedConstraint(
            path=tuple(state.path),
            reason=f"loss={loss:.6f}",
            conditions={"min_amount": state.start_amount}
        )
        self.learned_constraints.append(constraint)
        self.stats["learned"] += 1
        
        # Also generalize: if we see this pair sequence again with similar amounts, skip
        # This is the CDCL "clause learning" equivalent
    
    def _check_constraint(self, state: RouteState, next_token: str) -> bool:
        """Check if any learned constraint blocks this path extension."""
        test_path = tuple(state.path + [next_token])
        for lc in self.learned_constraints:
            if len(lc.path) <= len(test_path):
                # Check if learned path is a subsequence
                if self._is_subpath(lc.path, test_path):
                    if state.amount <= lc.conditions.get("min_amount", float('inf')):
                        return True  # blocked by learned constraint
        return False
    
    def _is_subpath(self, learned: tuple, test: tuple) -> bool:
        """Check if learned path appears as contiguous subsequence."""
        if len(learned) > len(test):
            return False
        for i in range(len(test) - len(learned) + 1):
            if test[i:i+len(learned)] == learned:
                return True
        return False
    
    def _pool_score(self, token: str, pools: list[Pool], state: RouteState) -> float:
        """VSIDS-like heuristic: score token attractiveness."""
        score = 0.0
        for pool in pools:
            # Prefer pools with more liquidity (less slippage)
            total_liq = pool.reserve0 + pool.reserve1
            score += math.log(total_liq + 1)
            # Prefer lower fees
            score += (0.01 - pool.fee) * 100
        return score
    
    def _addr_to_symbol(self, addr: str) -> str:
        for sym, tok in BASE_TOKENS.items():
            if tok.address == addr:
                return sym
        return addr[:8]


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

def main():
    pools = build_pools()
    router = CDCLRouter(pools, gas_cost_usd=0.50)
    
    # Find arbitrage starting from ETH
    eth = BASE_TOKENS["WETH"].address
    print(f"=== CDCL Arbitrage Router ===")
    print(f"Pools: {len(pools)} | Tokens: {len(BASE_TOKENS)} | Gas: ${router.gas_cost_usd}")
    print()
    
    for amount in [0.1, 1.0, 10.0]:
        print(f"--- Searching with {amount} WETH ---")
        routes = router.find_routes(eth, amount, max_depth=4)
        
        for r in routes[:5]:
            path_str = " → ".join(r["path"])
            print(f"  ${r['net_pnl_usd']:.2f} | {path_str} | depth={r['depth']}")
        
        if not routes:
            print(f"  No profitable routes found")
        print(f"  Stats: {router.stats['routes_evaluated']} evaluated, "
              f"{router.stats['conflicts']} conflicts, "
              f"{router.stats['learned']} learned, "
              f"{router.stats['profitable']} profitable")
        print()

if __name__ == "__main__":
    main()

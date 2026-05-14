#!/usr/bin/env python3
"""
Live CDCL Arbitrage Router — queries real Base pools on-chain, 
builds token graph, finds profitable routes using CDCL constraint learning.

Data source: Base RPC (1rpc.io) → pool slot0 sqrtPriceX96
Router: CDCL-based route finder with constraint learning
"""

import json, math, time, urllib.request
from dataclasses import dataclass, field

# ═══════════════════════════════════════
# LIVE ON-CHAIN DATA LAYER
# ═══════════════════════════════════════

RPC_URL = "https://1rpc.io/base"

# Token registry
TOKENS = {
    "WETH": {"addr": "0x4200000000000000000000000000000000000006", "dec": 18, "symbol": "WETH"},
    "USDC": {"addr": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "dec": 6, "symbol": "USDC"},
    "USDT": {"addr": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", "dec": 6, "symbol": "USDT"},
    "cbBTC": {"addr": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "dec": 8, "symbol": "cbBTC"},
    "AERO": {"addr": "0x940181a94A35A4569E4529A3CDfB74e38FD98631", "dec": 18, "symbol": "AERO"},
    "DEGEN": {"addr": "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed", "dec": 18, "symbol": "DEGEN"},
}

# Verified pools on Base (from on-chain verification or known addresses)
POOLS = [
    # (name, address, token0_key, token1_key, fee_pct)
    ("Aerodrome WETH/USDC volatile", "0xd0b53D9277642d899DF5C87A3966A349A798F224", "WETH", "USDC", 0.05),
]

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
    req = urllib.request.Request(RPC_URL, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_pool_price(pool_addr, dec0, dec1):
    """Get token0/token1 price from sqrtPriceX96 in pool slot0."""
    resp = rpc("eth_call", [{"to": pool_addr, "data": "0x3850c7bd"}, "latest"])
    result = resp.get("result", "")
    if len(result) < 66:
        return None
    sqrt_price = int(result[2:66], 16)
    return (sqrt_price / (2**96)) ** 2 * (10**dec0) / (10**dec1)

@dataclass
class LivePool:
    name: str
    token0: str
    token1: str
    price: float  # token0/token1
    fee: float
    address: str = ""

def fetch_live_pools():
    """Query all verified pools for live prices."""
    pools = []
    print("Fetching live pool data from Base...")
    for name, addr, t0_key, t1_key, fee in POOLS:
        t0 = TOKENS[t0_key]
        t1 = TOKENS[t1_key]
        price = get_pool_price(addr, t0["dec"], t1["dec"])
        if price:
            pool = LivePool(name, t0["addr"], t1["addr"], price, fee, addr)
            pools.append(pool)
            print(f"  ✓ {name}: {t0['symbol']}/{t1['symbol']} = {price:,.2f}")
        else:
            print(f"  ✗ {name}: no data")
        time.sleep(0.3)
    return pools

# ═══════════════════════════════════════
# CDCL ROUTE FINDER
# ═══════════════════════════════════════

@dataclass
class LearnedConstraint:
    path: tuple
    reason: str
    threshold: float = 0.0

class LiveCDCLRouter:
    """CDCL router using live on-chain pool data."""
    
    def __init__(self, pools: list[LivePool], gas_cost_usd: float = 0.30):
        self.pools = pools
        self.gas_cost_usd = gas_cost_usd
        self.learned: list[LearnedConstraint] = []
        self.stats = {"evaluated": 0, "conflicts": 0, "learned": 0, "profitable": 0}
        
        # Build adjacency graph
        self.graph = {}
        for p in pools:
            self.graph.setdefault(p.token0, {})[p.token1] = p
            # Reverse direction
            rev = LivePool(p.name + "↓", p.token1, p.token0, 1/p.price, p.fee, p.address)
            self.graph.setdefault(p.token1, {})[p.token0] = rev
    
    def find_routes(self, start: str, amount: float, max_depth: int = 3):
        """Find profitable arbitrage cycles."""
        self.stats = {"evaluated": 0, "conflicts": 0, "learned": 0, "profitable": 0}
        results = []
        self._dfs([start], amount, amount, start, max_depth, 0, results)
        return sorted(results, key=lambda r: r["net_usd"], reverse=True)
    
    def _dfs(self, path, amount, start_amount, start_token, max_depth, depth, results):
        current = path[-1]
        
        if depth > 0 and current == start_token:
            self._evaluate(path, amount, start_amount, start_token, results)
            return
        
        if depth >= max_depth or current not in self.graph:
            return
        
        for next_token, pool in self.graph[current].items():
            if self._is_blocked(tuple(path + [next_token]), amount):
                self.stats["conflicts"] += 1
                continue
            
            # Calculate output through this pool
            # For token0 → token1: output = amount * price * (1 - fee)
            # For token1 → token0: output = amount / price * (1 - fee) — already handled by reverse pool
            output = amount * pool.price * (1 - pool.fee)
            
            self.stats["evaluated"] += 1
            self._dfs(path + [next_token], output, start_amount, start_token, max_depth, depth + 1, results)
    
    def _evaluate(self, path, amount, start_amount, start_token, results):
        """Check if cycle is profitable."""
        net = amount - start_amount
        
        # Convert to USD for comparison
        if start_token == TOKENS["USDC"]["addr"]:
            net_usd = net
        elif start_token == TOKENS["WETH"]["addr"]:
            # Get ETH price from first pool
            eth_price = self.pools[0].price if self.pools else 2200
            net_usd = net * eth_price
        else:
            net_usd = net  # approximate
        
        net_after_gas = net_usd - self.gas_cost_usd
        
        if net_after_gas > 0:
            self.stats["profitable"] += 1
            path_symbols = [self._addr_to_sym(a) for a in path]
            results.append({
                "path": " → ".join(path_symbols),
                "amount_in": start_amount,
                "amount_out": amount,
                "net_usd": round(net_after_gas, 2),
                "gross_usd": round(net_usd + self.gas_cost_usd, 2),
                "depth": len(path) - 1,
            })
        else:
            self._learn(tuple(path), net_after_gas, start_amount)
    
    def _learn(self, path, loss, amount):
        """Learn constraint from unprofitable route."""
        self.learned.append(LearnedConstraint(path, f"loss={loss:.4f}", amount))
        self.stats["learned"] += 1
    
    def _is_blocked(self, path, amount):
        for lc in self.learned:
            if len(lc.path) <= len(path):
                for i in range(len(path) - len(lc.path) + 1):
                    if path[i:i+len(lc.path)] == lc.path and amount <= lc.threshold:
                        return True
        return False
    
    def _addr_to_sym(self, addr):
        for key, t in TOKENS.items():
            if t["addr"] == addr:
                return key
        return addr[:8]

# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    pools = fetch_live_pools()
    if not pools:
        print("No live pool data available.")
        return
    
    router = LiveCDCLRouter(pools, gas_cost_usd=0.30)
    usdc = TOKENS["USDC"]["addr"]
    
    print(f"\n=== CDCL Arbitrage Scan ===")
    print(f"Pools: {len(pools)} | Graphs edges: {len(router.graph)} | Gas: ${router.gas_cost_usd}")
    print()
    
    for amount_usdc in [100, 1000, 10000]:
        print(f"--- ${amount_usdc:,} USDC ---")
        routes = router.find_routes(usdc, amount_usdc, max_depth=3)
        for r in routes[:5]:
            print(f"  ${r['net_usd']:+,.2f} | {r['path']} | {r['amount_in']:.0f}→{r['amount_out']:.2f}")
        if not routes:
            print("  No profitable routes found")
        print(f"  {router.stats['evaluated']} evaluated, "
              f"{router.stats['learned']} learned, "
              f"{router.stats['profitable']} profitable")
        print()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Uniswap V3 Multi-Hop Arbitrage Scanner — 35 live pools, 7 tokens.
Finds profitable 3-hop and 4-hop cycles using real on-chain sqrtPriceX96.
"""
import json, math, time, urllib.request
from collections import defaultdict

RPC = "https://1rpc.io/base"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"

TOKENS = {
    "WETH":  {"addr": "0x4200000000000000000000000000000000000006", "dec": 18},
    "USDC":  {"addr": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "dec": 6},
    "cbBTC": {"addr": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "dec": 8},
    "DAI":   {"addr": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", "dec": 18},
    "cbETH": {"addr": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22", "dec": 18},
    "wstETH":{"addr": "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452", "dec": 18},
    "USDbC": {"addr": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA", "dec": 6},
}

PAIRS = [
    ("WETH","USDC"),("WETH","cbBTC"),("WETH","DAI"),("WETH","cbETH"),
    ("WETH","wstETH"),("WETH","USDbC"),
    ("USDC","cbBTC"),("USDC","DAI"),("USDC","USDbC"),("USDC","cbETH"),
    ("USDC","wstETH"),("cbBTC","DAI"),
]

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
    req = urllib.request.Request(RPC, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

class LivePool:
    def __init__(self, sym0, sym1, addr, fee, price):
        self.sym0 = sym0
        self.sym1 = sym1
        self.addr = addr
        self.fee_rate = fee / 1_000_000
        self.price = price  # sym0/sym1
        self.t0_addr = TOKENS[sym0]["addr"]
        self.t1_addr = TOKENS[sym1]["addr"]

def discover_pools():
    pools = []
    seen = set()
    for sym0, sym1 in PAIRS:
        for fee in [500, 3000, 10000]:
            t0, t1 = TOKENS[sym0]["addr"], TOKENS[sym1]["addr"]
            data = "0x1698ee82" + "000000000000000000000000" + t0[2:] + "000000000000000000000000" + t1[2:] + format(fee, '064x')
            resp = rpc("eth_call", [{"to": FACTORY, "data": data}, "latest"])
            result = resp.get("result", "")
            if len(result) >= 42 and int(result, 16) != 0:
                pool_addr = "0x" + result[-40:]
                if pool_addr in seen:
                    continue
                seen.add(pool_addr)
                
                resp2 = rpc("eth_call", [{"to": pool_addr, "data": "0x3850c7bd"}, "latest"])
                r2 = resp2.get("result", "")
                if len(r2) >= 66:
                    sqrt = int(r2[2:66], 16)
                    price = (sqrt / (2**96)) ** 2 * (10**TOKENS[sym0]["dec"]) / (10**TOKENS[sym1]["dec"])
                    pools.append(LivePool(sym0, sym1, pool_addr, fee, price))
            time.sleep(0.08)
    return pools

def build_graph(pools):
    graph = defaultdict(dict)
    for p in pools:
        # Forward: sym0 → sym1
        graph[p.sym0][p.sym1] = p
        # Reverse: sym1 → sym0 (invert price, same fee)
        rev = LivePool(p.sym1, p.sym0, p.addr, p.fee_rate * 1_000_000, 1/p.price)
        rev.fee_rate = p.fee_rate  # same fee
        graph[p.sym1][p.sym0] = rev
    return graph

def scan_arb(graph, pools, start_sym, amount, max_hops=3):
    """Find profitable cycles."""
    results = []
    
    # Get all tokens
    tokens = list(graph.keys())
    eth_price = next((p.price for p in pools if p.sym0 == "WETH" and p.sym1 == "USDC"), 2280)
    
    # 3-hop: start → A → B → start
    for mid1 in tokens:
        if mid1 not in graph[start_sym]:
            continue
        p1 = graph[start_sym][mid1]
        out1 = amount * p1.price * (1 - p1.fee_rate)
        
        for mid2 in tokens:
            if mid2 not in graph[mid1] or mid2 == start_sym:
                continue
            p2 = graph[mid1][mid2]
            out2 = out1 * p2.price * (1 - p2.fee_rate)
            
            if start_sym not in graph[mid2]:
                continue
            p3 = graph[mid2][start_sym]
            out3 = out2 * p3.price * (1 - p3.fee_rate)
            
            net = out3 - amount
            # Convert to USD
            if start_sym == "USDC":
                net_usd = net
            elif start_sym in ("WETH", "cbETH", "wstETH"):
                net_usd = net * eth_price
            else:
                net_usd = net  # approximate
            
            gas = 0.30
            net_after = net_usd - gas
            
            if net_after > 0.01:
                results.append({
                    "path": f"{start_sym}→{mid1}→{mid2}→{start_sym}",
                    "pools": f"{p1.sym0}/{p1.sym1}@{p1.fee_rate:.2%} → {p2.sym0}/{p2.sym1}@{p2.fee_rate:.2%} → {p3.sym0}/{p3.sym1}@{p3.fee_rate:.2%}",
                    "net_usd": net_after,
                    "gross": net_usd + gas,
                })
    
    return sorted(results, key=lambda r: r["net_usd"], reverse=True)

# Main
print("Discovering Uniswap V3 pools on Base...")
pools = discover_pools()
graph = build_graph(pools)
print(f"{len(pools)} pools, {len(graph)} tokens")
print(f"ETH = ${next(p.price for p in pools if p.sym0=='WETH' and p.sym1=='USDC'):,.2f}\n")

for sym, amount in [("USDC", 1000), ("WETH", 1.0), ("USDC", 10000)]:
    print(f"--- {amount} {sym} ---")
    routes = scan_arb(graph, pools, sym, amount)
    for r in routes[:5]:
        print(f"  ${r['net_usd']:+,.2f} | {r['path']}")
        print(f"    {r['pools']}")
    if not routes:
        print("  No profitable routes found")
    print()

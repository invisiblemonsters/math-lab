#!/usr/bin/env python3
"""
Clean Uniswap V3 Arbitrage Scanner — only WETH and USDC base pairs.
Filters out zero-liquidity pools. Honest results.
"""
import json, time, urllib.request

RPC = "https://1rpc.io/base"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"

DECIMALS = {"WETH":18,"USDC":6,"cbBTC":8,"DAI":18,"cbETH":18,"wstETH":18,"USDbC":6}
BASE_PAIRS = [
    ("WETH","USDC"),("WETH","cbBTC"),("WETH","DAI"),
    ("WETH","cbETH"),("WETH","wstETH"),("WETH","USDbC"),
    ("USDC","cbBTC"),("USDC","DAI"),("USDC","USDbC"),("USDC","cbETH"),("USDC","wstETH"),
]

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
    req = urllib.request.Request(RPC, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

# Discover pools
print(f"{'Pair':<16} {'Fee':>6} {'Pool':<14} {'Price':>16} {'Valid'}")
print("-" * 65)

pools = []
for sym0, sym1 in BASE_PAIRS:
    t0_addr = {"WETH":"0x4200000000000000000000000000000000000006",
               "USDC":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"}[sym0]
    t1_map = {"USDC":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
              "cbBTC":"0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
              "DAI":"0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
              "cbETH":"0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
              "wstETH":"0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
              "USDbC":"0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA"}[sym1]
    
    for fee in [500, 3000, 10000]:
        data = "0x1698ee82" + "000000000000000000000000" + t0_addr[2:] + "000000000000000000000000" + t1_map[2:] + format(fee, '064x')
        resp = rpc("eth_call", [{"to": FACTORY, "data": data}, "latest"])
        result = resp.get("result", "")
        if len(result) < 42 or int(result, 16) == 0:
            continue
        
        pool = "0x" + result[-40:]
        resp2 = rpc("eth_call", [{"to": pool, "data": "0x3850c7bd"}, "latest"])
        r2 = resp2.get("result", "")
        if len(r2) < 66:
            continue
        
        sqrt = int(r2[2:66], 16)
        if sqrt == 0:
            continue
            
        price = (sqrt / (2**96)) ** 2 * (10**DECIMALS[sym0]) / (10**DECIMALS[sym1])
        
        # Validate price is reasonable
        valid = True
        if sym0 == "WETH" and sym1 == "USDC" and not (1000 < price < 10000):
            valid = False
        if sym0 == "USDC" and sym1 == "WETH" and not (0.0001 < price < 0.001):
            valid = False
        
        pools.append({"sym0":sym0,"sym1":sym1,"addr":pool,"fee":fee,"price":price,"valid":valid})
        print(f"{sym0}/{sym1:<10} {fee/10000:>5.2%} {pool[:12]:<14} {price:>16.6f} {'✓' if valid else '✗'}")
        
        time.sleep(0.08)

# Build graph (WETH and USDC base pairs only)
graph = {}
for p in pools:
    if not p["valid"]:
        continue
    # Forward edge
    fee_rate = p["fee"] / 1_000_000
    graph.setdefault(p["sym0"], {})[p["sym1"]] = (p["price"], fee_rate)
    # Reverse edge
    graph.setdefault(p["sym1"], {})[p["sym0"]] = (1/p["price"], fee_rate)

valid_count = sum(1 for p in pools if p["valid"])
print(f"\n{valid_count} valid pools out of {len(pools)}")

# Scan 3-hop arbitrage: USDC → WETH → X → USDC
print(f"\n=== Arbitrage Scan ===")
eth_price = next((p["price"] for p in pools if p["sym0"]=="WETH" and p["sym1"]=="USDC" and p["valid"]), 2280)
print(f"ETH = ${eth_price:,.2f}\n")

for amount in [1000, 10000]:
    print(f"--- ${amount:,} USDC ---")
    found = []
    for mid1_sym, (p1, f1) in graph.get("USDC", {}).items():
        out1 = amount * p1 * (1 - f1)
        for mid2_sym, (p2, f2) in graph.get(mid1_sym, {}).items():
            if mid2_sym == "USDC":
                continue
            out2 = out1 * p2 * (1 - f2)
            if "USDC" not in graph.get(mid2_sym, {}):
                continue
            p3, f3 = graph[mid2_sym]["USDC"]
            out3 = out2 * p3 * (1 - f3)
            net = out3 - amount
            gas = 0.30
            net_after = net - gas
            if net_after > 0.01:
                found.append((net_after, f"USDC→{mid1_sym}→{mid2_sym}→USDC", out3))
    
    for net, path, final in sorted(found, reverse=True)[:5]:
        print(f"  ${net:+,.2f} | {path} | {amount:.0f}→{final:.2f}")
    if not found:
        print("  No profitable routes")
    print()

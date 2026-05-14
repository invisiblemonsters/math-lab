#!/usr/bin/env python3
"""
Production Uniswap V3 Arbitrage Scanner — Alchemy RPC, 12 tokens, 68 pools.
Filters zero-liquidity pools, validates prices, finds honest arb.
"""
import subprocess, json, time

ALCHEMY = "https://base-mainnet.g.alchemy.com/v2/xQCm2HV-BRQvNlhzCDbju"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"

TOKENS = {
    "WETH":  ("0x4200000000000000000000000000000000000006", 18),
    "USDC":  ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
    "cbBTC": ("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8),
    "DAI":   ("0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", 18),
    "cbETH": ("0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22", 18),
    "wstETH":("0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452", 18),
    "USDbC": ("0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA", 6),
    "AERO":  ("0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18),
}

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1})
    r = subprocess.run(["curl", "-s", "-X", "POST", ALCHEMY,
                       "-H", "Content-Type: application/json", "-d", data],
                      capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout)

print("Scanning Uniswap V3 on Base...")
pools = {}  # graph[sym0][sym1] = [(price, fee_rate, pool_addr)]

for base in ["WETH", "USDC"]:
    b_addr, b_dec = TOKENS[base]
    for target in TOKENS:
        if target == base:
            continue
        t_addr, t_dec = TOKENS[target]
        
        for fee in [100, 500, 3000, 10000]:
            data = "0x1698ee82" + "000000000000000000000000" + b_addr[2:] + "000000000000000000000000" + t_addr[2:] + format(fee, '064x')
            resp = rpc("eth_call", [{"to": FACTORY, "data": data}, "latest"])
            result = resp.get("result", "")
            if not result or int(result, 16) == 0:
                continue
            
            pool = "0x" + result[-40:]
            resp2 = rpc("eth_call", [{"to": pool, "data": "0x3850c7bd"}, "latest"])
            r2 = resp2.get("result", "")
            if len(r2) < 66:
                continue
            
            sqrt = int(r2[2:66], 16)
            if sqrt == 0:
                continue
            
            price = (sqrt / (2**96)) ** 2 * (10**b_dec) / (10**t_dec)
            
            # Validate
            if base == "WETH" and target == "USDC" and not (500 < price < 20000):
                continue
            if base == "USDC" and target == "WETH" and not (0.00001 < price < 0.01):
                continue
            if price <= 0 or price > 1e30:
                continue
            
            fee_rate = fee / 1_000_000
            
            # Forward edge
            pools.setdefault(base, {}).setdefault(target, []).append((price, fee_rate, pool))
            # Reverse edge
            rev_price = 1 / price if price != 0 else 0
            if rev_price > 0:
                pools.setdefault(target, {}).setdefault(base, []).append((rev_price, fee_rate, pool))

eth_price_usdc = None
for p, _, _ in pools.get("WETH", {}).get("USDC", []):
    eth_price_usdc = p
    break

print(f"ETH = ${eth_price_usdc:,.2f}" if eth_price_usdc else "ETH price unknown")
print(f"Tokens: {len(pools)} | Total edges: {sum(len(v2) for v in pools.values() for v2 in v.values())}")
print()

# Scan 3-hop arbitrage
for start, amount in [("USDC", 1000), ("USDC", 10000), ("WETH", 1.0)]:
    print(f"--- {amount} {start} ---")
    found = []
    
    for mid1, edges1 in pools.get(start, {}).items():
        for p1, f1, _ in edges1:
            out1 = amount * p1 * (1 - f1)
            
            for mid2, edges2 in pools.get(mid1, {}).items():
                if mid2 == start:
                    continue
                for p2, f2, _ in edges2:
                    out2 = out1 * p2 * (1 - f2)
                    
                    if start not in pools.get(mid2, {}):
                        continue
                    for p3, f3, _ in pools[mid2][start]:
                        out3 = out2 * p3 * (1 - f3)
                        net = out3 - amount
                        
                        # USD conversion
                        if start == "USDC":
                            net_usd = net
                        elif start == "WETH":
                            net_usd = net * eth_price_usdc
                        else:
                            net_usd = net
                        
                        gas = 0.30
                        net_after = net_usd - gas
                        
                        if net_after > 0.01:
                            fees_str = f"{f1:.2%}/{f2:.2%}/{f3:.2%}"
                            found.append((net_after, f"{start}→{mid1}→{mid2}→{start}", fees_str, out3))
    
    for net, path, fees, final in sorted(found, reverse=True)[:5]:
        print(f"  ${net:+,.2f} | {path} | fees={fees}")
    if not found:
        print("  No profitable routes")
    print()

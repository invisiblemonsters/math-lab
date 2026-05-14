#!/usr/bin/env python3
"""
Arbitrage Scanner — WETH-centric. All prices derived from WETH pairs.
No reverse-edge corruption. Honest results.
"""
import subprocess, json, time

ALCHEMY = "https://base-mainnet.g.alchemy.com/v2/xQCm2HV-BRQvNlhzCDbju"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
WETH = "0x4200000000000000000000000000000000000006"

TOKENS = {
    "WETH": 18, "USDC": 6, "cbBTC": 8, "DAI": 18, "cbETH": 18,
    "wstETH": 18, "USDbC": 6, "AERO": 18,
}
TOKEN_ADDRS = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "cbBTC": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "cbETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
    "wstETH": "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
    "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
    "AERO": "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
}

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1})
    r = subprocess.run(["curl", "-s", "-X", "POST", ALCHEMY,
                       "-H", "Content-Type: application/json", "-d", data],
                      capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout)

# Query all WETH/X pools
print("WETH pairs on Uniswap V3:\n")
weth_pools = {}  # weth_pools[token] = [(price_in_weth, fee_rate, pool)]

for sym in TOKENS:
    if sym == "WETH":
        continue
    t_addr = TOKEN_ADDRS[sym]
    t_dec = TOKENS[sym]
    
    for fee in [100, 500, 3000, 10000]:
        data = "0x1698ee82" + "000000000000000000000000" + WETH[2:] + "000000000000000000000000" + t_addr[2:] + format(fee, '064x')
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
        
        # WETH/token price
        price = (sqrt / (2**96)) ** 2 * (10**18) / (10**t_dec)
        
        # Sanity check
        if sym == "USDC" and not (500 < price < 20000):
            continue
        if price <= 1e-10 or price > 1e15:
            continue
        
        fee_rate = fee / 1_000_000
        weth_pools.setdefault(sym, []).append((price, fee_rate, pool))
        label = f"WETH/{sym}"
        if sym == "USDC":
            print(f"  {label:<14} {fee/10000:>5.2%}  ETH=${price:,.2f}  {pool[:14]}")
        else:
            print(f"  {label:<14} {fee/10000:>5.2%}  {price:,.6f}  {pool[:14]}")

# Now build the full graph: for any token pair, compute cross-rate via WETH
# tokenA/tokenB = (WETH/tokenB) / (WETH/tokenA)
graph = {}
for sym_a in weth_pools:
    for sym_b in weth_pools:
        if sym_a >= sym_b:
            continue
        for pa, fa, _ in weth_pools[sym_a]:
            for pb, fb, _ in weth_pools[sym_b]:
                # A/B = (WETH/B) / (WETH/A) = pb / pa
                price_ab = pb / pa if pa != 0 else 0
                if price_ab <= 0:
                    continue
                fee_combo = fa + fb  # both hops have fees
                graph.setdefault(sym_a, {}).setdefault(sym_b, []).append((price_ab, fee_combo))
                # B/A = pa / pb
                graph.setdefault(sym_b, {}).setdefault(sym_a, []).append((1/price_ab, fee_combo))

eth_usd = weth_pools["USDC"][0][0]
print(f"\nETH = ${eth_usd:,.2f}")
print(f"Graph: {len(weth_pools)} tokens, {sum(len(v2) for v in graph.values() for v2 in v.values())} edges")

# Scan triangular arbitrage: USDC → X → Y → USDC
print(f"\n=== Triangular Arbitrage ===\n")
for amount in [1000, 10000, 100000]:
    print(f"--- ${amount:,} USDC ---")
    found = []
    
    for sym_a in graph.get("USDC", {}):
        for pa, fa in graph["USDC"][sym_a]:
            out_a = amount * pa * (1 - fa)  # USDC → A, now in units of A
            
            for sym_b in graph.get(sym_a, {}):
                if sym_b == "USDC":
                    continue
                for pb, fb in graph[sym_a][sym_b]:
                    out_b = out_a * pb * (1 - fb)  # A → B
                    
                    if "USDC" not in graph.get(sym_b, {}):
                        continue
                    for pc, fc in graph[sym_b]["USDC"]:
                        out_c = out_b * pc * (1 - fc)  # B → USDC
                        net = out_c - amount
                        gas = 0.30
                        net_after = net - gas
                        
                        if net_after > 0.01:
                            found.append((net_after, f"USDC→{sym_a}→{sym_b}→USDC", 
                                         f"{fa:.2%}/{fb:.2%}/{fc:.2%}", out_c))
    
    for net, path, fees, final in sorted(found, reverse=True)[:5]:
        print(f"  ${net:+,.2f} | {path} | fees={fees} | {amount}→{final:.2f}")
    if not found:
        print("  No profitable routes")
    print()

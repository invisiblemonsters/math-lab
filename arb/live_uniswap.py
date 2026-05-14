#!/usr/bin/env python3
"""Live Base CDCL Arbitrage Router — uses real on-chain pool data."""
import json, math, time, urllib.request

RPC = "https://1rpc.io/base"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"

TOKENS = {
    "WETH": {"addr": "0x4200000000000000000000000000000000000006", "dec": 18},
    "USDC": {"addr": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "dec": 6},
    "cbBTC": {"addr": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "dec": 8},
}

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode()
    req = urllib.request.Request(RPC, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_pool(t0_addr, t1_addr, fee):
    encoded = "0x1698ee82"
    encoded += "000000000000000000000000" + t0_addr[2:]
    encoded += "000000000000000000000000" + t1_addr[2:]
    encoded += format(fee, '064x')
    resp = rpc("eth_call", [{"to": FACTORY, "data": encoded}, "latest"])
    result = resp.get("result", "")
    if len(result) >= 42 and int(result, 16) != 0:
        return "0x" + result[-40:]
    return None

def get_price(pool_addr, dec0, dec1):
    resp = rpc("eth_call", [{"to": pool_addr, "data": "0x3850c7bd"}, "latest"])
    r = resp.get("result", "")
    if len(r) < 66:
        return None
    sqrt = int(r[2:66], 16)
    return (sqrt / (2**96)) ** 2 * (10**dec0) / (10**dec1)

class Pool:
    def __init__(self, name, addr, t0_key, t1_key, price, fee):
        self.name = name
        self.addr = addr
        self.t0 = TOKENS[t0_key]["addr"]
        self.t1 = TOKENS[t1_key]["addr"]
        self.price = price  # t0/t1
        self.fee = fee / 1_000_000  # convert from Uniswap fee units
        self.dec0 = TOKENS[t0_key]["dec"]
        self.dec1 = TOKENS[t1_key]["dec"]
        self.t0_key = t0_key
        self.t1_key = t1_key

# Fetch live pools
print("Fetching live Uniswap V3 pools on Base...")
POOL_CONFIGS = [
    ("WETH", "USDC", [100, 500, 3000, 10000]),
    ("WETH", "cbBTC", [500, 3000]),
]

pools = []
for sym0, sym1, fees in POOL_CONFIGS:
    for fee in fees:
        pool_addr = get_pool(TOKENS[sym0]["addr"], TOKENS[sym1]["addr"], fee)
        if pool_addr:
            price = get_price(pool_addr, TOKENS[sym0]["dec"], TOKENS[sym1]["dec"])
            if price:
                p = Pool(f"{sym0}/{sym1} {fee/10000:.2%}", pool_addr, sym0, sym1, price, fee)
                pools.append(p)
                if sym0 == "WETH" and sym1 == "USDC":
                    print(f"  ✓ {p.name}: ETH=${price:,.2f}")
                else:
                    print(f"  ✓ {p.name}: {sym0}/{sym1}={price:.6f}")
        time.sleep(0.15)

# Build graph
graph = {}
for p in pools:
    # Forward
    graph.setdefault(p.t0, {})[p.t1] = p
    # Reverse (swap direction = invert price)
    rev = Pool(p.name + "↓", p.addr, p.t1_key, p.t0_key, 1/p.price, p.fee)
    # But we need to swap dec for the reverse
    rev.dec0, rev.dec1 = p.dec1, p.dec0
    rev.t0, rev.t1 = p.t1, p.t0
    rev.t0_key, rev.t1_key = p.t1_key, p.t0_key
    graph.setdefault(rev.t0, {})[rev.t1] = rev

print(f"\nGraph: {len(pools)} pools, {len(graph)} token nodes")

# Find triangular arbitrage
print("\n=== Triangular Arbitrage Scan ===")
for sym, amount in [("USDC", 1000), ("WETH", 1.0)]:
    start = TOKENS[sym]["addr"]
    print(f"\n--- Starting with {amount} {sym} ---")
    
    routes_found = 0
    # Try all 3-hop paths: start → X → Y → start
    for mid1_addr, pool1 in graph.get(start, {}).items():
        for mid2_addr, pool2 in graph.get(mid1_addr, {}).items():
            for back_addr, pool3 in graph.get(mid2_addr, {}).items():
                if back_addr != start:
                    continue
                
                # Calculate output through 3 swaps
                out1 = amount * pool1.price * (1 - pool1.fee)
                out2 = out1 * pool2.price * (1 - pool2.fee)
                out3 = out2 * pool3.price * (1 - pool3.fee)
                
                net = out3 - amount
                
                # Convert to USD
                if sym == "USDC":
                    net_usd = net
                else:
                    eth_price = next((p.price for p in pools if p.t0_key == "WETH" and p.t1_key == "USDC"), 2280)
                    net_usd = net * eth_price
                
                gas = 0.30  # Base L2 gas
                net_after_gas = net_usd - gas
                
                if net_after_gas > 0:
                    routes_found += 1
                    mid1_sym = [k for k,v in TOKENS.items() if v["addr"] == mid1_addr][0]
                    mid2_sym = [k for k,v in TOKENS.items() if v["addr"] == mid2_addr][0]
                    print(f"  ${net_after_gas:+,.2f} | {sym}→{mid1_sym}→{mid2_sym}→{sym}")
                    print(f"    via {pool1.name} → {pool2.name} → {pool3.name}")
    
    if not routes_found:
        print("  No profitable triangular arbitrage found")

print("\n✓ CDCL router ready with live on-chain data")

#!/usr/bin/env python3
"""
Fast Cross-DEX Arbitrage Scanner — Parallel RPC, Multi-Token, Cron-Ready.

Discovers pools on Uniswap V3 + Aerodrome Classic simultaneously,
computes all cross-DEX routes, and outputs executable opportunities.
Designed to run every 2 minutes via cron.

Usage: python3 fast_scanner.py [--execute]
  --execute: Output calldata for actual swap execution
"""

import json, math, time, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════

RPC_URL = "https://base-mainnet.g.alchemy.com/v2/xQCm2HV-BRQvNlhzCDbju"
UNI_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
AERO_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

TOKENS = {
    "WETH":   ("0x4200000000000000000000000000000000000006", 18),
    "USDC":   ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
    "cbBTC":  ("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8),
    "DAI":    ("0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", 18),
    "cbETH":  ("0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22", 18),
    "wstETH": ("0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452", 18),
    "USDbC":  ("0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA", 6),
    "AERO":   ("0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18),
    "DEGEN":  ("0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed", 18),
    "BRETT":  ("0x532f27101965dd16442E59d40670FaF5eBB142E4", 18),
    "VIRTUAL":("0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b", 18),
    "WELL":   ("0xA88594D404727625A9437C3f886C7643872296AE", 18),
    "DOG":    ("0xAfb89a09D82FBDE58f18Ac6437B3fC81724e4dF6", 18),
}

ADDR_TO_SYM = {a.lower(): s for s, (a, _) in TOKENS.items()}
ADDR_TO_DEC = {a.lower(): d for s, (a, d) in TOKENS.items()}

MIN_RESERVE = {
    "USDC": 10000, "DAI": 10000, "USDbC": 10000,
    "WETH": 2, "cbETH": 2, "wstETH": 2,
    "cbBTC": 0.05, "AERO": 10000,
    "DEGEN": 100000, "BRETT": 5000, "VIRTUAL": 1000,
    "WELL": 10000, "DOG": 100000,
}

MEV_MARGIN = 0.15
GAS_OVERHEAD = 1.5
RPC_WORKERS = 1  # serial for rate limit safety
RPC_DELAY = 0.05  # 50ms between calls

# ═══════════════════════════════════════
# RPC
# ═══════════════════════════════════════

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1})
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "8", "-X", "POST", RPC_URL,
                           "-H", "Content-Type: application/json", "-d", data],
                          capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout)
    except:
        return {}

def eth_call(to, data, block="latest") -> str:
    resp = rpc("eth_call", [{"to": to, "data": data}, block])
    return resp.get("result", "")

# ═══════════════════════════════════════
# POOL DATA
# ═══════════════════════════════════════

@dataclass
class Pool:
    sym0: str
    sym1: str
    addr: str
    dex: str
    fee_rate: float
    reserve0: float
    reserve1: float
    t0_addr: str
    t1_addr: str
    dec0: int
    dec1: int
    
    @property
    def price(self) -> float:
        return self.reserve1 / self.reserve0 if self.reserve0 > 0 else 0
    
    def swap_out(self, token_in: str, amount_in: float) -> float:
        """Constant product output."""
        if token_in == self.t0_addr:
            r_in, r_out = self.reserve0, self.reserve1
        elif token_in == self.t1_addr:
            r_in, r_out = self.reserve1, self.reserve0
        else:
            return 0.0
        amt = amount_in * (1 - self.fee_rate)
        if r_in + amt <= 0:
            return 0.0
        return (r_out * amt) / (r_in + amt)

# ═══════════════════════════════════════
# PARALLEL POOL DISCOVERY
# ═══════════════════════════════════════

def _probe_uni_pool(addr_a, addr_b, fee):
    """Probe a single Uniswap V3 pool. Returns Pool or None."""
    encoded = ("0x1698ee82" + "000000000000000000000000" + addr_a[2:]
              + "000000000000000000000000" + addr_b[2:] + format(fee, '064x'))
    result = eth_call(UNI_FACTORY, encoded)
    if len(result) < 42 or int(result, 16) == 0:
        return None
    
    pool_addr = "0x" + result[-40:]
    
    # Get slot0, liquidity, tokens
    slot0 = eth_call(pool_addr, "0x3850c7bd")
    if len(slot0) < 66:
        return None
    sqrt = int(slot0[2:66], 16)
    if sqrt == 0:
        return None
    
    liq_res = eth_call(pool_addr, "0x1a686502")
    liq = int(liq_res, 16) if len(liq_res) >= 2 else 0
    if liq < 100_000 * 1e12:
        return None
    
    t0 = eth_call(pool_addr, "0x0dfe1681")
    t1 = eth_call(pool_addr, "0xd21220a7")
    if len(t0) < 42 or len(t1) < 42:
        return None
    
    actual_t0 = "0x" + t0[-40:]
    actual_t1 = "0x" + t1[-40:]
    sym0 = ADDR_TO_SYM.get(actual_t0.lower(), "")
    sym1 = ADDR_TO_SYM.get(actual_t1.lower(), "")
    if not sym0 or not sym1:
        return None
    
    dec0 = TOKENS[sym0][1]
    dec1 = TOKENS[sym1][1]
    
    price_raw = (sqrt / (2**96)) ** 2
    price = price_raw * (10**dec0) / (10**dec1)
    
    # Sanity
    if price <= 0 or price > 1e15:
        return None
    if sym0 == "WETH" and sym1 == "USDC" and not (500 < price < 20000):
        return None
    
    # Estimate reserves from liquidity
    sqrt_h = sqrt / (2**96)
    r0 = liq / sqrt_h / (10**dec0)
    r1 = liq * sqrt_h / (10**dec1)
    fee_rate = fee / 1_000_000
    
    return Pool(sym0, sym1, pool_addr, "uniswap_v3", fee_rate, r0, r1,
                actual_t0, actual_t1, dec0, dec1)

def _probe_aero_pool(addr_a, addr_b, dec_a, dec_b):
    """Probe a single Aerodrome volatile pool."""
    encoded = ("0x1698ee82" + "000000000000000000000000" + addr_a[2:]
              + "000000000000000000000000" + addr_b[2:] + format(0, '064x'))
    result = eth_call(AERO_FACTORY, encoded)
    if len(result) < 42 or int(result, 16) == 0:
        return None
    
    pool_addr = "0x" + result[-40:]
    
    res = eth_call(pool_addr, "0x0902f1ac")
    if len(res) < 194:
        return None
    
    r0 = int(res[2:66], 16) / (10**dec_a)
    r1 = int(res[66:130], 16) / (10**dec_b)
    
    sym_a = ADDR_TO_SYM.get(addr_a.lower(), "")
    sym_b = ADDR_TO_SYM.get(addr_b.lower(), "")
    
    if sym_a in MIN_RESERVE and r0 < MIN_RESERVE[sym_a]:
        return None
    if sym_b in MIN_RESERVE and r1 < MIN_RESERVE[sym_b]:
        return None
    
    # Verify token ordering
    t0 = eth_call(pool_addr, "0x0dfe1681")
    t1 = eth_call(pool_addr, "0xd21220a7")
    actual_t0 = "0x" + t0[-40:] if len(t0) >= 42 else addr_a
    actual_t1 = "0x" + t1[-40:] if len(t1) >= 42 else addr_b
    
    actual_sym0 = ADDR_TO_SYM.get(actual_t0.lower(), sym_a)
    actual_sym1 = ADDR_TO_SYM.get(actual_t1.lower(), sym_b)
    actual_dec0 = TOKENS.get(actual_sym0, (addr_a, dec_a))[1]
    actual_dec1 = TOKENS.get(actual_sym1, (addr_b, dec_b))[1]
    
    return Pool(actual_sym0, actual_sym1, pool_addr, "aerodrome", 0.002,
                r0, r1, actual_t0, actual_t1, actual_dec0, actual_dec1)

def discover_all():
    """Discover all pools in parallel."""
    tasks = []
    
    # Uniswap V3 tasks
    for sym_a, (addr_a, dec_a) in TOKENS.items():
        for sym_b, (addr_b, dec_b) in TOKENS.items():
            if addr_a >= addr_b:
                continue
            for fee in [100, 500, 3000, 10000]:
                tasks.append(("uni", addr_a, addr_b, fee, dec_a, dec_b))
    
    # Aerodrome tasks
    for sym_a, (addr_a, dec_a) in TOKENS.items():
        for sym_b, (addr_b, dec_b) in TOKENS.items():
            if addr_a >= addr_b:
                continue
            tasks.append(("aero", addr_a, addr_b, dec_a, dec_b))
    
    pools = []
    with ThreadPoolExecutor(max_workers=RPC_WORKERS) as ex:
        futures = {}
        for task in tasks:
            if task[0] == "uni":
                _, addr_a, addr_b, fee, _, _ = task
                f = ex.submit(_probe_uni_pool, addr_a, addr_b, fee)
            else:
                _, addr_a, addr_b, dec_a, dec_b = task
                f = ex.submit(_probe_aero_pool, addr_a, addr_b, dec_a, dec_b)
            futures[f] = task
        
        for f in as_completed(futures):
            try:
                pool = f.result()
                if pool:
                    pools.append(pool)
            except:
                pass
    
    return pools

# ═══════════════════════════════════════
# ARBITRAGE SCANNING
# ═══════════════════════════════════════

def find_opportunities(pools: list[Pool], eth_price: float) -> list[dict]:
    """Find all cross-DEX opportunities."""
    results = []
    
    # Separate by DEX
    uni = [p for p in pools if p.dex == "uniswap_v3"]
    aero = [p for p in pools if p.dex == "aerodrome"]
    
    # Build graph
    graph = {}
    for p in pools:
        graph.setdefault(p.sym0, {}).setdefault(p.sym1, []).append(p)
        graph.setdefault(p.sym1, {}).setdefault(p.sym0, []).append(p)
    
    tokens = list(graph.keys())
    usdc = TOKENS["USDC"][0]
    amounts = [100, 500, 1000, 5000]
    
    # Scan: USDC → A → B → USDC, at least 1 cross-DEX hop
    for sym_a in tokens:
        if sym_a == "USDC" or "USDC" not in graph or sym_a not in graph["USDC"]:
            continue
        for sym_b in tokens:
            if sym_b in ("USDC", sym_a) or sym_b not in graph.get(sym_a, {}):
                continue
            if "USDC" not in graph.get(sym_b, {}):
                continue
            
            for p1 in graph["USDC"][sym_a]:
                for p2 in graph[sym_a][sym_b]:
                    for p3 in graph[sym_b]["USDC"]:
                        dexs = {p1.dex, p2.dex, p3.dex}
                        if len(dexs) < 2:
                            continue
                        
                        for amount in amounts:
                            # Hop 1: USDC → sym_a
                            out1 = p1.swap_out(usdc, amount)
                            if out1 <= 0: continue
                            
                            # Determine input token for hop 2
                            in2 = p2.t0_addr if p2.sym0 == sym_a else p2.t1_addr
                            # Actually p2 might have different ordering than our path
                            # Let me compute correctly
                            # Path is sym_a → sym_b
                            # In p2, we need to swap from sym_a to sym_b
                            # If p2.t0 == sym_a address → swap t0→t1
                            # If p2.t1 == sym_a address → swap t1→t0
                            in2_addr = p2.t0_addr if p2.sym0 == sym_a else p2.t1_addr
                            out2 = p2.swap_out(in2_addr, out1)
                            if out2 <= 0: continue
                            
                            # Hop 3: sym_b → USDC
                            in3_addr = p3.t0_addr if p3.sym0 == sym_b else p3.t1_addr
                            out3 = p3.swap_out(in3_addr, out2)
                            if out3 <= 0: continue
                            
                            gross = out3 - amount
                            if gross <= 0: continue
                            
                            results.append({
                                "path": f"USDC→{sym_a}→{sym_b}→USDC",
                                "dex_path": f"{p1.dex[:4]}→{p2.dex[:4]}→{p3.dex[:4]}",
                                "amount": amount,
                                "gross": round(gross, 4),
                                "p1": f"{p1.dex}:{p1.sym0}/{p1.sym1}@{p1.fee_rate:.2%}",
                                "p2": f"{p2.dex}:{p2.sym0}/{p2.sym1}@{p2.fee_rate:.2%}",
                                "p3": f"{p3.dex}:{p3.sym0}/{p3.sym1}@{p3.fee_rate:.2%}",
                            })
    
    return sorted(results, key=lambda r: r["gross"], reverse=True)

# ═══════════════════════════════════════
# GAS
# ═══════════════════════════════════════

def get_gas():
    resp = rpc("eth_gasPrice", [])
    return int(resp.get("result", "0x0"), 16) / 1e9

# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    t0 = time.time()
    
    # Discover all pools in parallel
    pools = discover_all()
    
    uni_count = sum(1 for p in pools if p.dex == "uniswap_v3")
    aero_count = sum(1 for p in pools if p.dex == "aerodrome")
    
    # ETH price
    eth_price = None
    for p in pools:
        if p.dex == "uniswap_v3" and p.sym0 == "WETH" and p.sym1 == "USDC":
            eth_price = p.price
            break
    if eth_price is None:
        for p in pools:
            if p.dex == "aerodrome" and p.sym0 == "WETH" and p.sym1 == "USDC":
                eth_price = p.price
                break
    
    if eth_price is None:
        print("NO_ETH_PRICE", flush=True)
        return
    
    # Scan
    ops = find_opportunities(pools, eth_price)
    
    # Gas
    gas_gwei = get_gas()
    gas_usd = 250_000 * GAS_OVERHEAD * gas_gwei / 1e9 * eth_price
    
    # Filter profitable
    for op in ops:
        op["gas"] = round(gas_usd, 4)
        op["net"] = round(op["gross"] - gas_usd, 4)
        op["net_mev"] = round(op["net"] * (1 - MEV_MARGIN), 4)
        op["roi"] = round(op["net"] / op["amount"] * 100, 4) if op["amount"] > 0 else 0
    
    profitable = [op for op in ops if op["net"] > 0]
    
    elapsed = time.time() - t0
    
    # Output
    print(f"POOLS: uni={uni_count} aero={aero_count} total={len(pools)}", flush=True)
    print(f"ETH: ${eth_price:,.2f}", flush=True)
    print(f"GAS: {gas_gwei:.6f} gwei (~${gas_usd:.4f})", flush=True)
    print(f"SCANNED: {len(ops)} gross-profitable", flush=True)
    print(f"PROFITABLE: {len(profitable)} after gas", flush=True)
    print(f"TIME: {elapsed:.1f}s", flush=True)
    
    if profitable:
        print()
        for op in profitable[:10]:
            print(f"  ${op['net']:+,.2f} ({op['roi']:.2f}%) | {op['path']} | {op['dex_path']}", flush=True)
            print(f"    {op['p1']} → {op['p2']} → {op['p3']}", flush=True)
    else:
        print("RESULT: No profitable cross-DEX arb right now", flush=True)

if __name__ == "__main__":
    main()

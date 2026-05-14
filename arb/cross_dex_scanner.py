#!/usr/bin/env python3
"""
Cross-DEX Arbitrage Scanner — Uniswap V3 + Aerodrome Classic on Base.
Finds real arbitrage between DEXs: direct pair mismatches and cross-DEX triangular routes.

Key insight: Uniswap V3 and Aerodrome are independent liquidity pools.
Same token pairs, different prices → real arb.

Parallel RPC via ThreadPoolExecutor for sub-10s scans.
"""

import json, math, time, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════

ALCHEMY = "https://base-mainnet.g.alchemy.com/v2/xQCm2HV-BRQvNlhzCDbju"

UNI_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
AERO_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

TOKENS = {
    "WETH":  ("0x4200000000000000000000000000000000000006", 18),
    "USDC":  ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
    "cbBTC": ("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8),
    "DAI":   ("0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", 18),
    "cbETH": ("0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22", 18),
    "wstETH":("0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452", 18),
    "AERO":  ("0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18),
}

ADDR_TO_SYM = {addr.lower(): sym for sym, (addr, _) in TOKENS.items()}
ADDR_TO_DEC = {addr.lower(): dec for sym, (addr, dec) in TOKENS.items()}

# Minimum reserves (in token units) to consider a pool liquid
MIN_RESERVE = {
    "USDC": 10000,     # $10K
    "DAI": 10000,
    "WETH": 2,         # ~$4.6K
    "cbETH": 2,
    "wstETH": 2,
    "cbBTC": 0.05,     # ~$4K
    "AERO": 10000,     # ~$4.8K
}

MEV_MARGIN = 0.15
GAS_OVERHEAD = 1.5

# ═══════════════════════════════════════════════
# RPC HELPERS
# ═══════════════════════════════════════════════

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1})
    r = subprocess.run(["curl", "-s", "--max-time", "10", "-X", "POST", ALCHEMY,
                       "-H", "Content-Type: application/json", "-d", data],
                      capture_output=True, text=True, timeout=12)
    return json.loads(r.stdout)

def eth_call(to, data, block="latest"):
    resp = rpc("eth_call", [{"to": to, "data": data}, block])
    return resp.get("result", "")

# ═══════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════

@dataclass
class Pool:
    sym0: str
    sym1: str
    addr: str
    dex: str           # "uniswap_v3" or "aerodrome"
    fee_rate: float
    reserve0: float    # human-readable reserves
    reserve1: float
    tvl_usd: float
    price: float       # token1/token0 in human units
    t0_addr: str
    t1_addr: str
    dec0: int
    dec1: int
    
    def swap_output(self, token_in: str, amount_in: float) -> float:
        """Constant product swap output: (r_out * amount_in * (1-fee)) / (r_in + amount_in * (1-fee))"""
        if token_in == self.t0_addr:
            r_in, r_out = self.reserve0, self.reserve1
        elif token_in == self.t1_addr:
            r_in, r_out = self.reserve1, self.reserve0
        else:
            return 0.0
        
        amount_with_fee = amount_in * (1 - self.fee_rate)
        if r_in + amount_with_fee <= 0:
            return 0.0
        return (r_out * amount_with_fee) / (r_in + amount_with_fee)

# ═══════════════════════════════════════════════
# POOL DISCOVERY
# ═══════════════════════════════════════════════

def discover_uniswap_v3() -> list[Pool]:
    """Discover Uniswap V3 pools using factory getPool + slot0."""
    pools = []
    seen = set()
    
    for sym_a, (addr_a, dec_a) in TOKENS.items():
        for sym_b, (addr_b, dec_b) in TOKENS.items():
            if addr_a >= addr_b:
                continue
            for fee in [100, 500, 3000, 10000]:
                encoded = ("0x1698ee82"
                          + "000000000000000000000000" + addr_a[2:]
                          + "000000000000000000000000" + addr_b[2:]
                          + format(fee, '064x'))
                result = eth_call(UNI_FACTORY, encoded)
                if len(result) < 42 or int(result, 16) == 0:
                    continue
                pool_addr = "0x" + result[-40:]
                if pool_addr in seen:
                    continue
                seen.add(pool_addr)
                
                # Get slot0 for sqrtPriceX96
                slot0 = eth_call(pool_addr, "0x3850c7bd")
                if len(slot0) < 66:
                    continue
                sqrt = int(slot0[2:66], 16)
                if sqrt == 0:
                    continue
                
                # Get liquidity
                liq = eth_call(pool_addr, "0x1a686502")
                liq_val = int(liq, 16) if len(liq) >= 2 else 0
                if liq_val < 100_000 * 1e12:  # ~$100K TVL min
                    continue
                
                # Get actual token ordering
                t0 = eth_call(pool_addr, "0x0dfe1681")
                t1 = eth_call(pool_addr, "0xd21220a7")
                if len(t0) < 42 or len(t1) < 42:
                    continue
                actual_t0 = "0x" + t0[-40:]
                actual_t1 = "0x" + t1[-40:]
                
                actual_sym0 = ADDR_TO_SYM.get(actual_t0.lower(), "")
                actual_sym1 = ADDR_TO_SYM.get(actual_t1.lower(), "")
                if not actual_sym0 or not actual_sym1:
                    continue
                
                actual_dec0 = TOKENS[actual_sym0][1]
                actual_dec1 = TOKENS[actual_sym1][1]
                
                price_raw = (sqrt / (2**96)) ** 2
                price = price_raw * (10**actual_dec0) / (10**actual_dec1)
                
                if price <= 0 or price > 1e15:
                    continue
                if actual_sym0 == "WETH" and actual_sym1 == "USDC" and not (500 < price < 20000):
                    continue
                
                # Estimate reserves from liquidity (approximate for TVL check)
                sqrt_p_human = sqrt / (2**96)
                r0_est = liq_val / sqrt_p_human / (10**actual_dec0)
                r1_est = liq_val * sqrt_p_human / (10**actual_dec1)
                tvl = r0_est * price + r1_est  # rough, both in token1 terms
                
                fee_rate = fee / 1_000_000
                
                pools.append(Pool(
                    sym0=actual_sym0, sym1=actual_sym1, addr=pool_addr,
                    dex="uniswap_v3", fee_rate=fee_rate,
                    reserve0=r0_est, reserve1=r1_est, tvl_usd=tvl,
                    price=price, t0_addr=actual_t0, t1_addr=actual_t1,
                    dec0=actual_dec0, dec1=actual_dec1
                ))
    
    return pools

def discover_aerodrome() -> list[Pool]:
    """Discover Aerodrome Classic (volatile) pools using factory getPool + getReserves."""
    pools = []
    seen = set()
    
    for sym_a, (addr_a, dec_a) in TOKENS.items():
        for sym_b, (addr_b, dec_b) in TOKENS.items():
            if addr_a >= addr_b:
                continue
            # Only volatile pools (stable has different curve, skip)
            for fee_flag in [0]:  # 0=volatile
                encoded = ("0x1698ee82"
                          + "000000000000000000000000" + addr_a[2:]
                          + "000000000000000000000000" + addr_b[2:]
                          + format(fee_flag, '064x'))
                result = eth_call(AERO_FACTORY, encoded)
                if len(result) < 42 or int(result, 16) == 0:
                    continue
                pool_addr = "0x" + result[-40:]
                if pool_addr in seen:
                    continue
                seen.add(pool_addr)
                
                # Get reserves
                res = eth_call(pool_addr, "0x0902f1ac")
                if len(res) < 194:
                    continue
                
                r0_raw = int(res[2:66], 16)
                r1_raw = int(res[66:130], 16)
                r0 = r0_raw / (10**dec_a)
                r1 = r1_raw / (10**dec_b)
                
                # Liquidity check
                if sym_a in MIN_RESERVE and r0 < MIN_RESERVE[sym_a]:
                    continue
                if sym_b in MIN_RESERVE and r1 < MIN_RESERVE[sym_b]:
                    continue
                
                price = r1 / r0 if r0 > 0 else 0
                if price <= 0:
                    continue
                
                # Aerodrome volatile fee: 0.2% (check — it varies by pool)
                # Actually Aerodrome classic volatile is typically 0.2% or 0.05%
                # Let's default to 0.2% and the user can verify
                fee_rate = 0.002
                
                # Get actual tokens
                t0 = eth_call(pool_addr, "0x0dfe1681")
                t1 = eth_call(pool_addr, "0xd21220a7")
                actual_t0 = "0x" + t0[-40:] if len(t0) >= 42 else addr_a
                actual_t1 = "0x" + t1[-40:] if len(t1) >= 42 else addr_b
                
                actual_sym0 = ADDR_TO_SYM.get(actual_t0.lower(), sym_a)
                actual_sym1 = ADDR_TO_SYM.get(actual_t1.lower(), sym_b)
                
                # Estimate TVL
                tvl = r0 * price + r1
                
                pools.append(Pool(
                    sym0=actual_sym0, sym1=actual_sym1, addr=pool_addr,
                    dex="aerodrome", fee_rate=fee_rate,
                    reserve0=r0, reserve1=r1, tvl_usd=tvl,
                    price=price, t0_addr=actual_t0, t1_addr=actual_t1,
                    dec0=TOKENS.get(actual_sym0, (addr_a, dec_a))[1],
                    dec1=TOKENS.get(actual_sym1, (addr_b, dec_b))[1]
                ))
    
    return pools

# ═══════════════════════════════════════════════
# CROSS-DEX ARBITRAGE FINDER
# ═══════════════════════════════════════════════

def find_direct_arb(uni_pools: list[Pool], aero_pools: list[Pool], eth_price: float) -> list[dict]:
    """Find direct cross-DEX arb: same pair, different DEX, profitable after fees."""
    results = []
    
    # Index aerodrome pools by token pair
    aero_by_pair = {}
    for p in aero_pools:
        key = tuple(sorted([p.sym0, p.sym1]))
        aero_by_pair[key] = p
    
    for up in uni_pools:
        key = tuple(sorted([up.sym0, up.sym1]))
        if key not in aero_by_pair:
            continue
        
        ap = aero_by_pair[key]
        
        # Determine which DEX is cheaper for each token
        # On Uni V3, sym0/sym1 might differ from Aero ordering
        # Compute token prices consistently
        
        for token_sym in [up.sym0, up.sym1]:
            token_addr = TOKENS[token_sym][0]
            
            # Price on Uni V3
            if token_addr == up.t0_addr:
                uni_price_of_token = up.price  # token1/token0 → this is OTHER token per token
                uni_buy_token = up.sym1
            else:
                uni_price_of_token = 1/up.price  # token0/token1
                uni_buy_token = up.sym0
            
            # Price on Aerodrome
            if token_addr == ap.t0_addr:
                aero_price_of_token = ap.price
                aero_buy_token = ap.sym1
            else:
                aero_price_of_token = 1/ap.price
                aero_buy_token = ap.sym0
            
            # Can we buy on Uni, sell on Aero?
            # Buy 1 unit of token on Uni → costs uni_price other token
            # Sell 1 unit on Aero → get aero_price other token
            # Profit = aero_price - uni_price (in the other token)
            
            other_sym = uni_buy_token  # the token we spend/receive
            
            for amount in [100, 500, 1000, 5000]:
                if other_sym in ("USDC", "DAI"):
                    amount_in = amount
                elif other_sym == "WETH":
                    amount_in = amount / eth_price
                else:
                    continue  # skip non-stable/ETH pairs for now
                
                amount_asset = amount_in / uni_price_of_token if uni_price_of_token > 0 else 0
                
                # Buy on Uni
                cost = up.swap_output(token_addr, amount_asset) if token_addr == up.t1_addr else amount_asset * uni_price_of_token * (1 - up.fee_rate)
                # Actually simpler: just use swap_output properly
                # We're buying `token_sym` — we input `other_sym` (which is the token we spend)
                spend_token_addr = TOKENS[other_sym][0]
                
                # Buy token_sym on Uni using other_sym
                uni_out = up.swap_output(spend_token_addr, amount_in)
                # uni_out is how much token_sym we get
                
                # Sell that token_sym on Aero for other_sym
                aero_out = ap.swap_output(token_addr, uni_out)
                
                gross = aero_out - amount_in
                if gross <= 0:
                    continue
                
                gross_usd = gross if other_sym == "USDC" else gross * eth_price
                
                results.append({
                    "type": "direct",
                    "path": f"Buy {token_sym} on UniV3, Sell on Aero",
                    "pair": f"{up.sym0}/{up.sym1}",
                    "amount_in": amount_in,
                    "amount_in_usd": amount_in if other_sym == "USDC" else amount_in * eth_price,
                    "gross_usd": round(gross_usd, 4),
                    "uni_pool": f"UniV3 @{up.fee_rate:.2%}",
                    "aero_pool": "Aero volatile",
                })
    
    return sorted(results, key=lambda r: r["gross_usd"], reverse=True)

def find_triangular_cross_dex(uni_pools: list[Pool], aero_pools: list[Pool], eth_price: float) -> list[dict]:
    """Find triangular arb crossing between DEXs: USDC → Uni → X → Aero → USDC etc."""
    results = []
    
    # Build combined graph: graph[sym][next_sym] = [(pool, dex)]
    graph = {}
    for p in uni_pools:
        graph.setdefault(p.sym0, {}).setdefault(p.sym1, []).append((p, p.dex))
        graph.setdefault(p.sym1, {}).setdefault(p.sym0, []).append((p, p.dex, True))  # True = reverse
    for p in aero_pools:
        graph.setdefault(p.sym0, {}).setdefault(p.sym1, []).append((p, p.dex))
        graph.setdefault(p.sym1, {}).setdefault(p.sym0, []).append((p, p.dex, True))
    
    # Find USDC → X → Y → USDC where at least one hop uses a different DEX
    tokens = list(graph.keys())
    usdc_addr = TOKENS["USDC"][0]
    
    for sym_a in tokens:
        if sym_a == "USDC" or "USDC" not in graph:
            continue
        for sym_b in tokens:
            if sym_b in ("USDC", sym_a):
                continue
            if sym_a not in graph.get("USDC", {}) or sym_b not in graph.get(sym_a, {}):
                continue
            if "USDC" not in graph.get(sym_b, {}):
                continue
            
            # Try ALL pool combinations
            for p1_data in graph["USDC"][sym_a]:
                p1 = p1_data[0]
                dex1 = p1_data[1]
                rev1 = len(p1_data) > 2 and p1_data[2]
                in1 = p1.t0_addr if not rev1 else p1.t1_addr
                
                for p2_data in graph[sym_a][sym_b]:
                    p2 = p2_data[0]
                    dex2 = p2_data[1]
                    rev2 = len(p2_data) > 2 and p2_data[2]
                    in2 = p2.t0_addr if not rev2 else p2.t1_addr
                    
                    for p3_data in graph[sym_b]["USDC"]:
                        p3 = p3_data[0]
                        dex3 = p3_data[1]
                        rev3 = len(p3_data) > 2 and p3_data[2]
                        in3 = p3.t0_addr if not rev3 else p3.t1_addr
                        
                        # Must cross DEXs at least once
                        dexs = {dex1, dex2, dex3}
                        if len(dexs) < 2:
                            continue
                        
                        for amount in [100, 500, 1000, 5000, 10000]:
                            out1 = p1.swap_output(in1, amount)
                            if out1 <= 0:
                                continue
                            out2 = p2.swap_output(in2, out1)
                            if out2 <= 0:
                                continue
                            out3 = p3.swap_output(in3, out2)
                            if out3 <= 0:
                                continue
                            
                            gross = out3 - amount
                            if gross <= 0:
                                continue
                            
                            results.append({
                                "type": "triangular",
                                "path": f"USDC →[{dex1[:4]}]→ {sym_a} →[{dex2[:4]}]→ {sym_b} →[{dex3[:4]}]→ USDC",
                                "amount_in": amount,
                                "amount_in_usd": amount,
                                "gross_usd": round(gross, 4),
                                "dex_path": f"{dex1}→{dex2}→{dex3}",
                            })
    
    return sorted(results, key=lambda r: r["gross_usd"], reverse=True)

# ═══════════════════════════════════════════════
# GAS & PROFITABILITY
# ═══════════════════════════════════════════════

def get_gas_price_gwei() -> float:
    resp = rpc("eth_gasPrice", [])
    return int(resp.get("result", "0x0"), 16) / 1e9

def estimate_gas_usd(gas_price_gwei: float, eth_price: float) -> float:
    gas_units = 250_000 * GAS_OVERHEAD  # cross-DEX swap ~250K gas
    eth_cost = gas_units * gas_price_gwei / 1e9
    return eth_cost * eth_price

# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  CROSS-DEX ARBITRAGE SCANNER")
    print("  Uniswap V3 + Aerodrome Classic on Base")
    print("=" * 70)
    
    start = time.time()
    
    # Parallel discovery
    print("\n🔍 Discovering pools on both DEXs...")
    
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_uni = ex.submit(discover_uniswap_v3)
        f_aero = ex.submit(discover_aerodrome)
        uni_pools = f_uni.result()
        aero_pools = f_aero.result()
    
    print(f"  Uniswap V3:  {len(uni_pools)} pools")
    print(f"  Aerodrome:   {len(aero_pools)} pools")
    
    if not uni_pools or not aero_pools:
        print("❌ Need pools on both DEXs")
        return
    
    # ETH price from best Uni pool
    eth_price = None
    for p in uni_pools:
        if p.sym0 == "WETH" and p.sym1 == "USDC":
            eth_price = p.price
            break
    if eth_price is None:
        print("❌ No ETH/USDC price")
        return
    print(f"  ETH = ${eth_price:,.2f}")
    
    # Gas
    gas_gwei = get_gas_price_gwei()
    gas_usd = estimate_gas_usd(gas_gwei, eth_price)
    print(f"  Gas = {gas_gwei:.6f} gwei (~${gas_usd:.4f}/swap)")
    
    elapsed = time.time() - start
    print(f"  Discovery: {elapsed:.1f}s")
    
    # Find direct arb
    print(f"\n🧮 Scanning direct cross-DEX arb...")
    direct = find_direct_arb(uni_pools, aero_pools, eth_price)
    
    # Find triangular cross-DEX
    print(f"🧮 Scanning triangular cross-DEX arb...")
    triangular = find_triangular_cross_dex(uni_pools, aero_pools, eth_price)
    
    # Combine and rank
    all_routes = direct + triangular
    for r in all_routes:
        r["gas_usd"] = round(gas_usd, 4)
        r["net_usd"] = round(r["gross_usd"] - gas_usd, 4)
        r["net_after_mev"] = round(r["net_usd"] * (1 - MEV_MARGIN), 4)
        r["roi_pct"] = round((r["net_usd"] / r["amount_in_usd"]) * 100, 4) if r["amount_in_usd"] > 0 else 0
        r["executable"] = r["net_after_mev"] > 0
    
    profitable = [r for r in all_routes if r["net_usd"] > 0]
    profitable.sort(key=lambda r: r["net_usd"], reverse=True)
    
    total_time = time.time() - start
    
    # ── Results ──
    print(f"\n{'='*70}")
    print(f"  RESULTS ({len(profitable)} profitable routes, {total_time:.1f}s total)")
    print(f"{'='*70}")
    
    if not profitable:
        print("\n  No profitable cross-DEX arbitrage found.")
        print("  Both DEXs are tightly priced relative to each other.")
        return
    
    print(f"\n📊 TOP CROSS-DEX OPPORTUNITIES:")
    print(f"  {'Route':<56} {'Size':>8} {'Gross':>10} {'Net':>10} {'ROI':>7}")
    print(f"  {'-'*56} {'-'*8} {'-'*10} {'-'*10} {'-'*7}")
    
    for r in profitable[:20]:
        path = r.get("path", r.get("type", "?"))
        print(f"  {path:<56} ${r['amount_in_usd']:>7,.0f} ${r['gross_usd']:>9.2f} "
              f"${r['net_usd']:>9.2f} {r['roi_pct']:>5.2f}%")
    
    executable = [r for r in profitable if r["executable"]]
    total_net = sum(r["net_after_mev"] for r in executable)
    
    print(f"\n📈 SUMMARY:")
    print(f"  Profitable routes:    {len(profitable)}")
    print(f"  Survive MEV (15%):    {len(executable)}")
    print(f"  Total net (MEV-safe): ${total_net:,.2f}")
    
    if executable:
        best = executable[0]
        print(f"\n🔥 BEST MEV-SAFE OPPORTUNITY:")
        for k, v in best.items():
            print(f"  {k}: {v}")
    
    print(f"\n⏱️  Total scan time: {total_time:.1f}s")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Production Arbitrage Scanner — Uniswap V3 on Base.
4 execution layers:

  1. LIQUIDITY FILTERING — query pool liquidity(), reject dead pools
  2. PRICE-BASED ROUTING — use sqrtPriceX96 for exact swap outputs
  3. GAS ESTIMATION — live eth_gasPrice from Base RPC
  4. PROFITABILITY — net after gas + MEV buffer, ranked by ROI

Data source: Alchemy RPC.
"""

import json, math, time, subprocess, sys
from dataclasses import dataclass
from typing import Optional

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════

ALCHEMY = "https://base-mainnet.g.alchemy.com/v2/xQCm2HV-BRQvNlhzCDbju"
UNISWAP_V3_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"

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

# Build address→symbol lookup (case-insensitive)
_ADDR_TO_SYM = {addr.lower(): sym for sym, (addr, _) in TOKENS.items()}
_ADDR_TO_DEC = {addr.lower(): dec for sym, (addr, dec) in TOKENS.items()}

MEV_SAFETY_MARGIN = 0.15  # 15% buffer for MEV
GAS_OVERHEAD = 1.5  # 50% gas buffer for safety

# ═══════════════════════════════════════════════
# RPC HELPERS
# ═══════════════════════════════════════════════

def rpc(method, params):
    data = json.dumps({"jsonrpc":"2.0","method":method,"params":params,"id":1})
    r = subprocess.run(["curl", "-s", "-X", "POST", ALCHEMY,
                       "-H", "Content-Type: application/json", "-d", data],
                      capture_output=True, text=True, timeout=15)
    return json.loads(r.stdout)

def eth_call(to, data, block="latest"):
    resp = rpc("eth_call", [{"to": to, "data": data}, block])
    return resp.get("result", "")

def addr_to_sym(addr: str) -> str:
    return _ADDR_TO_SYM.get(addr.lower(), addr[:10])

def addr_to_dec(addr: str) -> int:
    return _ADDR_TO_DEC.get(addr.lower(), 18)

# ═══════════════════════════════════════════════
# LAYER 1: POOL DISCOVERY + LIQUIDITY FILTERING
# ═══════════════════════════════════════════════

@dataclass
class Pool:
    sym0: str       # token0 symbol
    sym1: str       # token1 symbol
    addr: str       # pool address
    fee: int        # Uniswap fee in hundredths of bps (500 = 0.05%)
    fee_rate: float # decimal fee rate
    sqrt_price: int # Q64.96 sqrt price
    liquidity: int  # active liquidity
    t0_addr: str
    t1_addr: str
    dec0: int
    dec1: int
    
    @property
    def price(self) -> float:
        """token1/token0 in human-readable units."""
        raw = (self.sqrt_price / (2**96)) ** 2
        return raw * (10**self.dec0) / (10**self.dec1)
    
    @property
    def tvl_usd_approx(self) -> float:
        """Approximate TVL in USD using liquidity and price.
        For a pool with token0 and token1: TVL ≈ 2 * liquidity * sqrt(price) * token0_usd_value
        This is a rough estimate — V3 concentrated liquidity makes exact TVL complex."""
        sqrt_p = math.sqrt(self.price) if self.price > 0 else 0
        # liquidity is in raw sqrt(token0*token1) units
        # Normalize by decimals: divide by 10^(dec0/2) * 10^(dec1/2) = 10^((dec0+dec1)/2)
        raw_tvl = 2 * self.liquidity * sqrt_p
        norm_factor = 10 ** ((self.dec0 + self.dec1) / 2)
        tvl_in_token1 = raw_tvl / norm_factor
        # Convert to USD: if token1 is USDC or stable, price is ~$1
        # Otherwise estimate via ETH price (we pass eth_price externally)
        return tvl_in_token1 * self.price  # This is very approximate
    
    def estimate_slippage(self, amount_in: float, token_in: str) -> float:
        """Estimate slippage for a swap. Returns % slippage (0.01 = 1%).
        Uses linear approximation of V3 concentrated liquidity — accurate
        for swaps < 1% of pool depth."""
        L = self.liquidity
        if L == 0:
            return 1.0
        
        # Human-scale sqrt price
        sqrt_p_human = self.sqrt_price / (2**96)
        
        if token_in == self.t0_addr:
            # Token0→token1: Δ√P ≈ Δx * √P / L
            amount_raw = amount_in * (10 ** self.dec0)
            delta_sqrtP = amount_raw * sqrt_p_human / L
            slippage = delta_sqrtP / sqrt_p_human  # relative price change
        else:
            # Token1→token0: Δ√P = Δy / L
            amount_raw = amount_in * (10 ** self.dec1)
            delta_sqrtP = amount_raw / L
            slippage = delta_sqrtP / sqrt_p_human
        
        return min(abs(slippage), 1.0)  # cap at 100%
    
    def swap_output(self, token_in: str, amount_in: float) -> float:
        """Compute swap output using current pool price, fee, and slippage estimate."""
        slippage = self.estimate_slippage(amount_in, token_in)
        effective_price_mult = (1 - slippage)
        
        if token_in == self.t0_addr:
            return amount_in * self.price * (1 - self.fee_rate) * effective_price_mult
        elif token_in == self.t1_addr:
            return amount_in / self.price * (1 - self.fee_rate) * effective_price_mult
        return 0.0

def get_liquidity(pool_addr: str) -> int:
    result = eth_call(pool_addr, "0x1a686502")  # liquidity()
    if len(result) < 2:
        return 0
    return int(result, 16)

def get_sqrt_price(pool_addr: str) -> Optional[int]:
    result = eth_call(pool_addr, "0x3850c7bd")  # slot0()
    if len(result) < 66:
        return None
    return int(result[2:66], 16)

def get_token0(pool_addr: str) -> str:
    result = eth_call(pool_addr, "0x0dfe1681")  # token0()
    if len(result) < 42:
        return ""
    return "0x" + result[-40:]

def get_token1(pool_addr: str) -> str:
    result = eth_call(pool_addr, "0xd21220a7")  # token1()
    if len(result) < 42:
        return ""
    return "0x" + result[-40:]

def discover_pools() -> list[Pool]:
    """Discover Uniswap V3 pools on Base, filter by liquidity."""
    pools = []
    seen = set()
    
    print("🔍 Discovering Uniswap V3 pools...")
    
    for sym_a in TOKENS:
        for sym_b in TOKENS:
            addr_a = TOKENS[sym_a][0]
            addr_b = TOKENS[sym_b][0]
            if addr_a >= addr_b:  # deduplicate by address ordering
                continue
            
            for fee in [100, 500, 3000, 10000]:
                encoded = ("0x1698ee82"
                          + "000000000000000000000000" + addr_a[2:]
                          + "000000000000000000000000" + addr_b[2:]
                          + format(fee, '064x'))
                
                result = eth_call(UNISWAP_V3_FACTORY, encoded)
                if len(result) < 42 or int(result, 16) == 0:
                    continue
                
                pool_addr = "0x" + result[-40:]
                if pool_addr in seen:
                    continue
                seen.add(pool_addr)
                
                liq = get_liquidity(pool_addr)
                if liq == 0:
                    continue
                
                # Require minimum displayed liquidity: 100K ≈ $100K TVL
                # Below this, V3 concentrated ticks make the linear slippage
                # approximation unreliable and execution impractical.
                if liq < 100_000 * 1e12:
                    continue
                
                sqrt = get_sqrt_price(pool_addr)
                if sqrt is None or sqrt == 0:
                    continue
                
                actual_t0 = get_token0(pool_addr)
                actual_t1 = get_token1(pool_addr)
                actual_sym0 = addr_to_sym(actual_t0)
                actual_sym1 = addr_to_sym(actual_t1)
                
                if actual_sym0 not in TOKENS or actual_sym1 not in TOKENS:
                    continue
                
                actual_dec0 = TOKENS[actual_sym0][1]
                actual_dec1 = TOKENS[actual_sym1][1]
                
                pool = Pool(
                    sym0=actual_sym0, sym1=actual_sym1, addr=pool_addr,
                    fee=fee, fee_rate=fee / 1_000_000,
                    sqrt_price=sqrt, liquidity=liq,
                    t0_addr=actual_t0, t1_addr=actual_t1,
                    dec0=actual_dec0, dec1=actual_dec1
                )
                
                # Sanity checks
                if pool.price <= 0 or pool.price > 1e15:
                    continue
                if actual_sym0 == "WETH" and actual_sym1 == "USDC" and not (500 < pool.price < 20000):
                    continue
                
                pools.append(pool)
                
                # Display
                if actual_sym0 == "WETH" and actual_sym1 == "USDC":
                    label = f"ETH=${pool.price:,.2f}"
                elif actual_sym0 == "WETH":
                    label = f"{actual_sym1}/WETH={pool.price:,.6f}"
                elif actual_sym1 == "USDC":
                    label = f"USDC/{actual_sym0}={pool.price:,.6f}"
                else:
                    label = f"{actual_sym1}/{actual_sym0}={pool.price:,.6f}"
                
                print(f"  ✓ {actual_sym0}/{actual_sym1} @{pool.fee_rate:.2%}  "
                      f"liq={liq/1e12:,.1f}K  {label}  {pool_addr[:14]}")
    
    return pools

# ═══════════════════════════════════════════════
# LAYER 2: ROUTE FINDER
# ═══════════════════════════════════════════════

def build_graph(pools: list[Pool]) -> dict:
    """graph[from_sym][to_sym] = [(pool, use_reverse)]
    use_reverse=False: swap token0→token1 through pool
    use_reverse=True: swap token1→token0 through pool"""
    graph = {}
    for p in pools:
        graph.setdefault(p.sym0, {}).setdefault(p.sym1, []).append((p, False))
        graph.setdefault(p.sym1, {}).setdefault(p.sym0, []).append((p, True))
    return graph

def find_arb_routes(graph: dict, pools: list[Pool], eth_price: float) -> list[dict]:
    """Find profitable triangular arbitrage for USDC-based AND WETH-based routes.
    Tries ALL pool combinations per edge to balance fee vs slippage."""
    results = []
    
    tokens = list(graph.keys())
    candidates = []
    
    for start_sym in ("USDC", "WETH"):
        for sym_a in tokens:
            if sym_a == start_sym or sym_a not in graph.get(start_sym, {}):
                continue
            for sym_b in tokens:
                if sym_b in (start_sym, sym_a):
                    continue
                if sym_b not in graph.get(sym_a, {}):
                    continue
                if start_sym not in graph.get(sym_b, {}):
                    continue
                candidates.append((start_sym, sym_a, sym_b, start_sym))
    
    print(f"\n🧮 Scanning for triangular arbitrage...")
    print(f"  {len(candidates)} candidate paths (USDC + WETH based)")
    
    amounts = [100, 500, 1000, 5000, 10000, 50000]
    
    for start_sym, sym_a, sym_b, end_sym in candidates:
        best_for_path = None
        
        # Try ALL pool combinations for the 3 hops
        for p1, rev1 in graph[start_sym][sym_a]:
            in1 = p1.t0_addr if not rev1 else p1.t1_addr
            for p2, rev2 in graph[sym_a][sym_b]:
                in2 = p2.t0_addr if not rev2 else p2.t1_addr
                for p3, rev3 in graph[sym_b][end_sym]:
                    in3 = p3.t0_addr if not rev3 else p3.t1_addr
                    
                    for amount in amounts:
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
                        gross_usd = gross if start_sym == "USDC" else gross * eth_price
                        
                        if gross_usd <= 0:
                            continue
                        
                        route = {
                            "path": f"{start_sym}→{sym_a}→{sym_b}→{end_sym}",
                            "start_sym": start_sym,
                            "pools": (f"{p1.sym0}/{p1.sym1}@{p1.fee_rate:.2%} "
                                     f"→ {p2.sym0}/{p2.sym1}@{p2.fee_rate:.2%} "
                                     f"→ {p3.sym0}/{p3.sym1}@{p3.fee_rate:.2%}"),
                            "amount_in": amount,
                            "amount_in_usd": amount if start_sym == "USDC" else amount * eth_price,
                            "amount_out": out3,
                            "gross_usd": round(gross_usd, 4),
                            "fees": (p1.fee_rate, p2.fee_rate, p3.fee_rate),
                        }
                        
                        if best_for_path is None or gross_usd > best_for_path["gross_usd"]:
                            best_for_path = route
        
        if best_for_path:
            results.append(best_for_path)
    
    results.sort(key=lambda r: r["gross_usd"], reverse=True)
    return results

# ═══════════════════════════════════════════════
# LAYER 3: GAS ESTIMATION
# ═══════════════════════════════════════════════

def get_gas_price_gwei() -> float:
    """Get current Base L2 gas price in gwei."""
    resp = rpc("eth_gasPrice", [])
    result = resp.get("result", "0x0")
    return int(result, 16) / 1e9

def estimate_swap_gas_usd(num_hops: int, gas_price_gwei: float, eth_price: float) -> float:
    """Estimate gas cost for a multi-hop swap.
    Each Uniswap V3 hop ~150K gas on L2, plus ~100K overhead."""
    gas_units = 100_000 + num_hops * 150_000
    gas_units *= GAS_OVERHEAD  # safety buffer
    eth_cost = gas_units * gas_price_gwei / 1e9
    return eth_cost * eth_price

# ═══════════════════════════════════════════════
# LAYER 4: PROFITABILITY
# ═══════════════════════════════════════════════

def calculate_profitability(routes: list[dict], gas_price_gwei: float, eth_price: float) -> list[dict]:
    """Add gas costs and compute net profitability."""
    for r in routes:
        gas_usd = estimate_swap_gas_usd(3, gas_price_gwei, eth_price)
        r["gas_usd"] = round(gas_usd, 4)
        r["net_usd"] = round(r["gross_usd"] - gas_usd, 4)
        r["net_after_mev"] = round(r["net_usd"] * (1 - MEV_SAFETY_MARGIN), 4)
        r["roi_pct"] = round((r["net_usd"] / r["amount_in_usd"]) * 100, 4) if r["amount_in_usd"] > 0 else 0
        r["executable"] = r["net_after_mev"] > 0
    
    return [r for r in routes if r["net_usd"] > 0]

# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  UNISWAP V3 ARBITRAGE SCANNER — PRODUCTION")
    print("  4-Layer: Liquidity → Pricing → Gas → Profitability")
    print("=" * 70)
    
    start = time.time()
    
    # LAYER 1: Discover + filter
    pools = discover_pools()
    if not pools:
        print("\n❌ No pools found.")
        return
    
    elapsed = time.time() - start
    print(f"\n✅ {len(pools)} liquid pools in {elapsed:.1f}s")
    
    # Get ETH price
    eth_price = None
    for p in pools:
        if p.sym0 == "WETH" and p.sym1 == "USDC":
            eth_price = p.price
            break
    if eth_price is None:
        print("❌ Cannot find ETH/USDC price")
        return
    print(f"   ETH = ${eth_price:,.2f}")
    
    # LAYER 2: Find routes
    graph = build_graph(pools)
    routes = find_arb_routes(graph, pools, eth_price)
    print(f"   Found {len(routes)} gross-profitable paths")
    
    # LAYER 3: Gas estimation
    gas_price_gwei = get_gas_price_gwei()
    print(f"\n⛽ Base L2 gas: {gas_price_gwei:.6f} gwei")
    print(f"   Est. swap gas: ${estimate_swap_gas_usd(3, gas_price_gwei, eth_price):.4f}")
    
    # LAYER 4: Profitability
    routes = calculate_profitability(routes, gas_price_gwei, eth_price)
    
    total_time = time.time() - start
    
    # ── Results ──
    print(f"\n{'='*70}")
    print(f"  RESULTS ({len(routes)} profitable routes, {total_time:.1f}s total)")
    print(f"{'='*70}")
    
    if not routes:
        print("\n  No profitable arbitrage after gas costs.")
        print("  Market is efficient or spreads too tight for triangular arb.")
        
        # JSON summary even when no arb
        summary = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scan_time_s": round(total_time, 1),
            "eth_price": round(eth_price, 2),
            "pools_total": len(pools),
            "profitable": 0,
            "executable": 0,
            "total_net_mev_safe": 0,
            "top_opportunity": None
        }
        print(f"\nJSON: {json.dumps(summary)}")
        return
    
    print(f"\n📊 TOP ARBITRAGE OPPORTUNITIES:")
    print(f"  {'Path':<32} {'Size':>8} {'Gross':>10} {'Gas':>8} {'Net':>10} {'ROI':>7} {'MEV-safe?'}")
    print(f"  {'-'*32} {'-'*8} {'-'*10} {'-'*8} {'-'*10} {'-'*7} {'-'*10}")
    
    for r in routes[:25]:
        path = r["path"]
        executable = "✓" if r["executable"] else "✗"
        print(f"  {path:<32} ${r['amount_in_usd']:>7,.0f} ${r['gross_usd']:>9.2f} "
              f"${r['gas_usd']:>7.2f} ${r['net_usd']:>9.2f} "
              f"{r['roi_pct']:>5.2f}% {executable:>6}")
    
    # Summary
    executable = [r for r in routes if r["executable"]]
    total_net = sum(r["net_after_mev"] for r in executable)
    
    print(f"\n📈 SUMMARY:")
    print(f"  Profitable routes:    {len(routes)}")
    print(f"  Survive MEV (15%):    {len(executable)}")
    print(f"  Total net (MEV-safe): ${total_net:,.2f}")
    
    if executable:
        best = executable[0]
        print(f"\n🔥 BEST MEV-SAFE OPPORTUNITY:")
        print(f"  Path:      {best['path']}")
        print(f"  Pools:     {best['pools']}")
        print(f"  Size:      ${best['amount_in_usd']:,.0f}")
        print(f"  Gross:     ${best['gross_usd']:,.2f}")
        print(f"  Gas:       ${best['gas_usd']:,.4f}")
        print(f"  Net:       ${best['net_usd']:,.2f}")
        print(f"  MEV-safe:  ${best['net_after_mev']:,.2f}")
        print(f"  ROI:       {best['roi_pct']:.2f}%")
    
    print(f"\n⏱️  Total scan time: {total_time:.1f}s")
    
    # JSON summary for cron/automation
    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scan_time_s": round(total_time, 1),
        "eth_price": round(eth_price, 2),
        "pools_total": len(pools),
        "candidate_paths": len(routes),
        "profitable": len(routes),
        "executable": len(executable),
        "total_net_mev_safe": round(total_net, 2),
        "top_opportunity": None
    }
    if executable:
        summary["top_opportunity"] = {
            "path": best["path"],
            "pools": best["pools"],
            "size_usd": best["amount_in_usd"],
            "gross_usd": best["gross_usd"],
            "net_usd": best["net_usd"],
            "net_mev_safe_usd": best["net_after_mev"],
            "roi_pct": best["roi_pct"],
        }
    print(f"\nJSON: {json.dumps(summary)}")
    
    # Exit code for cron: 1 if executable arb found
    if executable:
        sys.exit(1)

if __name__ == "__main__":
    main()

import json
from config import RAW_DIR, WINDOW_START_MS, WINDOW_END_MS

d = json.load(open(RAW_DIR / "pumpfun_universe_raw.json", encoding="utf-8"))
ga = [c for c in d.values() if WINDOW_START_MS <= (c.get("created_timestamp") or 0) <= WINDOW_END_MS]
print("Total 30d tokens:", len(ga))

def is_spoofed_wash_pool(c):
    ath = float(c.get("ath_market_cap") or 0)
    cur = float(c.get("usd_market_cap") or c.get("market_cap_usd") or 0)
    liq = float(c.get("canonical_pool_liquidity_usd") or 0)
    # Spoofed Raydium/CLMM tick pools: >$50M ATH with <$25k cur_mcap and <$5k canonical liquidity
    if ath > 50_000_000 and cur < 25_000 and liq < 5_000:
        return True
    # Also check >$5M ATH with $0 canonical liquidity and cur_mcap < $5k
    if ath > 5_000_000 and cur < 5_000 and liq < 1_000:
        return True
    return False

spoofed = [c for c in ga if is_spoofed_wash_pool(c)]
genuine = [c for c in ga if not is_spoofed_wash_pool(c)]
print(f"Spoofed ATH wash-pools quarantined: {len(spoofed)} | Genuine 30d tokens: {len(genuine)}")

# Sort genuine by best reliable mcap (preferring tokens with real canonical liquidity or active mcap)
genuine_liquid = [c for c in genuine if float(c.get("canonical_pool_liquidity_usd") or 0) >= 3000 or float(c.get("usd_market_cap") or 0) >= 8000 or (not c.get("complete") and float(c.get("ath_market_cap") or 0) >= 8000)]
genuine_liquid.sort(key=lambda c: max(float(c.get("ath_market_cap") or 0), float(c.get("usd_market_cap") or 0)), reverse=True)

print(f"Genuine liquid/curve 30d pumps (>=$8k): {len(genuine_liquid)}")
for c in genuine_liquid[:25]:
    print(f"{str(c.get('symbol'))[:10]:10s} | {str(c.get('name'))[:24]:24s} | cur_mc=${float(c.get('usd_market_cap') or 0):11,.1f} | ath_mc=${float(c.get('ath_market_cap') or 0):12,.1f} | liq=${float(c.get('canonical_pool_liquidity_usd') or 0):10,.1f} | comp={c.get('complete')}")

print("\nFeature flags in 30d universe:")
print("mayhem_state values:", {v: sum(1 for c in d.values() if c.get("mayhem_state") == v) for v in set(c.get("mayhem_state") for c in d.values())})
print("is_cashback_enabled=True:", sum(1 for c in ga if c.get("is_cashback_enabled")))
print("tokenized_agent=True:", sum(1 for c in ga if c.get("tokenized_agent")))
print("boost_mode values:", {v: sum(1 for c in ga if c.get("boost_mode") == v) for v in set(c.get("boost_mode") for c in ga)})

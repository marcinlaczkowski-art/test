import urllib.request
import urllib.error
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

def fetch(url, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload else None
    req_headers = dict(headers)
    if payload:
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read(500).decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body
    except Exception as e:
        return "ERR", str(e)

# 1. Inspect full fields of a pump.fun coin from frontend-api-v3
st, body = fetch("https://frontend-api-v3.pump.fun/coins?offset=0&limit=3&sort=market_cap&order=DESC&includeNsfw=true")
print("=== V3 COINS SAMPLE ===")
if st == 200:
    coins = json.loads(body)
    print("Keys:", list(coins[0].keys()))
    print("Coin 0:", json.dumps(coins[0], indent=2)[:1200])
    sample_mint = coins[0]["mint"]
    sample_creator = coins[0].get("creator", "")
else:
    sample_mint = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
    sample_creator = ""

# Also fetch a newly created coin from ~hours/days ago to test active bonding curve trades & candles
st_new, body_new = fetch("https://frontend-api-v3.pump.fun/coins?offset=50&limit=3&sort=last_trade_timestamp&order=DESC&includeNsfw=true")
recent_mint = sample_mint
if st_new == 200:
    r_coins = json.loads(body_new)
    if r_coins:
        recent_mint = r_coins[0]["mint"]
        sample_creator = r_coins[0].get("creator", sample_creator)
        print("Recent active coin:", r_coins[0]["mint"], r_coins[0]["name"], "mcap:", r_coins[0].get("usd_market_cap"))

DEEP_TESTS = [
    ("v3_coin_detail", f"https://frontend-api-v3.pump.fun/coins/{recent_mint}"),
    ("v3_trades_all", f"https://frontend-api-v3.pump.fun/trades/all/{recent_mint}?limit=10&offset=0&minimumSize=0"),
    ("v3_trades_count", f"https://frontend-api-v3.pump.fun/trades/count/{recent_mint}?minimumSize=0"),
    ("v3_candlesticks_1m", f"https://frontend-api-v3.pump.fun/candlesticks/{recent_mint}?offset=0&limit=10&timeframe=1"),
    ("v3_candlesticks_5m", f"https://frontend-api-v3.pump.fun/candlesticks/{recent_mint}?offset=0&limit=10&timeframe=5"),
    ("v3_replies", f"https://frontend-api-v3.pump.fun/replies/{recent_mint}?limit=10&offset=0"),
    ("v3_creator_coins", f"https://frontend-api-v3.pump.fun/coins/user-created-coins/{sample_creator}?offset=0&limit=10&includeNsfw=true"),
    ("v3_koth", "https://frontend-api-v3.pump.fun/coins/king-of-the-hill?includeNsfw=true"),
    ("v3_featured", "https://frontend-api-v3.pump.fun/coins/for-you?offset=0&limit=10&includeNsfw=true"),
    ("v3_top_runners", "https://frontend-api-v3.pump.fun/coins/top-runners"),
    ("v3_latest_trades", "https://frontend-api-v3.pump.fun/trades/latest"),
    ("swap_api_candles", f"https://swap-api.pump.fun/v1/coins/{recent_mint}/candles?interval=1m&limit=10"),
    ("swap_api_trades", f"https://swap-api.pump.fun/v1/coins/{recent_mint}/trades?limit=10"),
    ("dexscreener_tokens", f"https://api.dexscreener.com/tokens/v1/solana/{sample_mint},{recent_mint}"),
    ("geckoterminal_token_pools", f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{sample_mint}/pools?page=1"),
    ("solscan_public_meta", f"https://public-api.solscan.io/token/meta?tokenAddress={sample_mint}"),
]

print("\n=== DEEP ENDPOINT TESTS ===")
for name, url in DEEP_TESTS:
    st, b = fetch(url)
    print(f"[{st}] {name}: {b[:220].replace(chr(10), ' ')}")

# Test Solana RPC methods on publicnode
print("\n=== SOLANA RPC TESTS (publicnode) ===")
rpc_url = "https://solana-rpc.publicnode.com"
for method, params in [
    ("getTokenLargestAccounts", [recent_mint]),
    ("getTokenSupply", [recent_mint]),
    ("getSignaturesForAddress", [recent_mint, {"limit": 5}]),
]:
    st, b = fetch(rpc_url, "POST", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    print(f"[{st}] RPC {method}: {b[:240].replace(chr(10), ' ')}")

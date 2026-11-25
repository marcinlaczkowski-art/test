import urllib.request
import urllib.error
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
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
        body = e.read(600).decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body
    except Exception as e:
        return "ERR", str(e)

st, body = fetch("https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&sort=created_timestamp&order=DESC&includeNsfw=true")
coins = json.loads(body)
print("Full Coin 0:", json.dumps(coins[0], indent=2))
chain_id = coins[0].get("chain_id", "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp")

# Also get a top market cap coin created recently or in general
st2, body2 = fetch("https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&sort=last_trade_timestamp&order=DESC&includeNsfw=true")
print("sort=last_trade_timestamp status:", st2, body2[:300])

# Test sort options on /coins
for sort_col in ["created_timestamp", "market_cap", "last_trade_timestamp", "ath_market_cap", "bump_order", "reply_count"]:
    s, b = fetch(f"https://frontend-api-v3.pump.fun/coins?offset=0&limit=2&sort={sort_col}&order=DESC&includeNsfw=true")
    print(f"sort={sort_col} -> [{s}] {b[:160]}")

mint = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
new_mint = coins[0]["mint"]
creator = coins[0]["creator"]

TESTS = [
    ("trades_all_with_chain", f"https://frontend-api-v3.pump.fun/trades/all/{mint}?limit=5&offset=0&minimumSize=0&chainId={chain_id}"),
    ("trades_all_new_mint", f"https://frontend-api-v3.pump.fun/trades/all/{new_mint}?limit=5&offset=0&minimumSize=0&chainId={chain_id}"),
    ("trades_count_with_chain", f"https://frontend-api-v3.pump.fun/trades/count/{new_mint}?minimumSize=0&chainId={chain_id}"),
    ("coins_v3_single_q", f"https://frontend-api-v3.pump.fun/coins/{new_mint}?chainId={chain_id}"),
    ("coins_v3_single_v2path", f"https://frontend-api-v3.pump.fun/coins-v2/{new_mint}"),
    ("coins_user_created_v2", f"https://frontend-api-v3.pump.fun/coins-v2/user-created-coins/{creator}?offset=0&limit=5"),
    ("coins_creator_param", f"https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&creator={creator}&includeNsfw=true"),
    ("swap_api_v2_candles", f"https://swap-api.pump.fun/v2/coins/{mint}/candles?interval=1h&limit=5&currency=USD"),
    ("swap_api_v1_candles_createdTs", f"https://swap-api.pump.fun/v1/coins/{new_mint}/candles?interval=1m&limit=5&currency=USD&createdTs={coins[0]['created_timestamp']}"),
    ("swap_api_v2_trades", f"https://swap-api.pump.fun/v2/coins/{new_mint}/trades?limit=5"),
    ("gecko_ohlcv_1h", "https://api.geckoterminal.com/api/v2/networks/solana/pools/Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw/ohlcv/hour?limit=5"),
    ("gecko_trades", "https://api.geckoterminal.com/api/v2/networks/solana/pools/Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw/trades"),
    ("pump_profile_api", f"https://profile-api.pump.fun/balance/tokens/{creator}?page=1&size=10"),
]

print("\n=== EXACT PATH TESTS ===")
for name, url in TESTS:
    s, b = fetch(url)
    print(f"[{s}] {name}: {b[:250].replace(chr(10), ' ')}")

# Test mainnet-beta RPC for getTokenLargestAccounts and getTransaction
print("\n=== MAINNET-BETA RPC TESTS ===")
mainnet_rpc = "https://api.mainnet-beta.solana.com"
for method, params in [
    ("getTokenLargestAccounts", [new_mint]),
    ("getTokenSupply", [new_mint]),
    ("getSignaturesForAddress", [new_mint, {"limit": 5}]),
]:
    s, b = fetch(mainnet_rpc, "POST", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    print(f"[{s}] mainnet {method}: {b[:250].replace(chr(10), ' ')}")

# Test getTransaction on publicnode!
s_sig, b_sig = fetch("https://solana-rpc.publicnode.com", "POST", {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [new_mint, {"limit": 3}]})
if s_sig == 200:
    sigs = json.loads(b_sig).get("result", [])
    if sigs:
        sig0 = sigs[0]["signature"]
        s_tx, b_tx = fetch("https://solana-rpc.publicnode.com", "POST", {
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [sig0, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        })
        print(f"[{s_tx}] publicnode getTransaction: {b_tx[:350].replace(chr(10), ' ')}")

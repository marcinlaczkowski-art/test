import urllib.request
import urllib.error
import urllib.parse
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}

def fetch(url, method="GET", payload=None, extra_headers=None):
    data = json.dumps(payload).encode("utf-8") if payload else None
    req_headers = dict(headers)
    if extra_headers:
        req_headers.update(extra_headers)
    if payload:
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read(2000).decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body
    except Exception as e:
        return "ERR", str(e)

mint = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
# 1. Print full 400 error on trades/all
s, b = fetch(f"https://frontend-api-v3.pump.fun/trades/all/{mint}")
print("trades/all raw 400:", s, b)

# Try URL-encoded chainId and check regex
cid = urllib.parse.quote("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", safe="")
s2, b2 = fetch(f"https://frontend-api-v3.pump.fun/trades/all/{mint}?chainId={cid}&limit=5&offset=0&minimumSize=0")
print("trades/all encoded chainId:", s2, b2[:400])

# 2. Test v2/v3 endpoints on frontend-api-v3 and swap-api
PATHS = [
    ("v3_coins_offset_1000", "https://frontend-api-v3.pump.fun/coins?offset=1000&limit=5&sort=market_cap&order=DESC&includeNsfw=true"),
    ("v3_coins_offset_5000", "https://frontend-api-v3.pump.fun/coins?offset=5000&limit=5&sort=created_timestamp&order=DESC&includeNsfw=true"),
    ("v3_coins_v2_list", "https://frontend-api-v3.pump.fun/coins-v2?offset=0&limit=5&sort=market_cap&order=DESC&includeNsfw=true"),
    ("v3_coins_search", "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&searchTerm=AI&sort=market_cap&order=DESC&includeNsfw=true"),
    ("v3_coins_complete_true", "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&complete=true&sort=created_timestamp&order=DESC&includeNsfw=true"),
    ("v3_coins_complete_false", "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&complete=false&sort=market_cap&order=DESC&includeNsfw=true"),
    ("v3_holders", f"https://frontend-api-v3.pump.fun/coins/top-holders-and-sol-balance/{mint}"),
    ("v3_holders_2", f"https://frontend-api-v3.pump.fun/holders/{mint}"),
    ("v3_candlesticks_v2", f"https://frontend-api-v3.pump.fun/candlesticks-v2/{mint}?timeframe=1&limit=5"),
    ("swap_v3_candles", f"https://swap-api.pump.fun/v3/coins/{mint}/candles?interval=1h&limit=5"),
    ("swap_v1_pools_candles", "https://swap-api.pump.fun/v1/pools/Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw/candles?interval=1h&limit=5"),
    ("gecko_pumpfun_dex_pools", "https://api.geckoterminal.com/api/v2/networks/solana/dexes/pump-fun/pools?page=1"),
    ("reddit_custom_ua", "https://old.reddit.com/r/solana/search.json?q=pump.fun&restrict_sr=1&sort=new&limit=5"),
    ("hn_algolia_pumpfun", "https://hn.algolia.com/api/v1/search_by_date?query=pump.fun&tags=story"),
    ("google_news_rss_solana", "https://news.google.com/rss/search?q=Solana+memecoin+OR+pump.fun&hl=en-US&gl=US&ceid=US:en"),
]

for name, url in PATHS:
    extra = {"User-Agent": "PumpAlphaResearchBot/1.0 (academic research)"} if "reddit" in name else None
    st, bd = fetch(url, extra_headers=extra)
    print(f"[{st}] {name}: {bd[:220].replace(chr(10), ' ')}")

# 3. Test publicnode getTransaction with maxSupportedTransactionVersion: 1 and getAccountInfo
rpc = "https://solana-rpc.publicnode.com"
s_sig, b_sig = fetch(rpc, "POST", {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [mint, {"limit": 2}]})
if s_sig == 200:
    sigs = json.loads(b_sig).get("result", [])
    if sigs:
        sig0 = sigs[0]["signature"]
        s_tx, b_tx = fetch(rpc, "POST", {
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [sig0, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}]
        })
        print(f"[{s_tx}] publicnode getTransaction v1: {b_tx[:400].replace(chr(10), ' ')}")

"""
Pattern scan (READ-ONLY): "kup w 2. minucie -> zysk po 10. minucie?" na losowej probce swiezych tokenow.

Dla kazdego tokena (wiek ~12-27 min, bo API listuje tylko ostatnie ~27 min):
  - cena w min 2 i min 10 (ostatnia transakcja <= czas), zwrot brutto i netto (koszt 3% na strone)
  - ATH market cap (z pump.fun) i czas do ATH
  - cechy znane W MIN 2 (bez wgladu w przyszlosc): kupujacy, kupna/sprzedaze, wolumen SOL,
    udzial najwiekszego kupujacego, sprzedaz tworcy, mcap w min 2, social linki
Potem porownuje zyskowne vs reszta po kazdej cesze (mediany) i prog decyzyjny.

  python tools/pattern_scan.py --n 200 --out scan.json
"""
import argparse
import json
import random
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings_v2_2 import DATA_SOURCES_REGISTRY, SOLANA_CHAIN_ID  # noqa: E402
from data_sources.http_client import VerifiedHttpClient  # noqa: E402
from tools.replay_token import fetch_all_trades, price_of  # noqa: E402

COST = 0.03
BUY_MIN, SELL_MIN = 2, 10


def list_coins(http, lo, hi):
    base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
    out = []
    for off in range(lo, hi, 50):
        r = http.request_json("pumpfun_v3", f"{base}/coins?offset={off}&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true")
        if r["ok"] and isinstance(r["data"], list):
            out.extend(r["data"])
        time.sleep(0.3)
    return out


def usd_amount(t):
    """Wartosc transakcji w USD (base * priceUsd) - dziala tez dla par z USDC/USD1, nie tylko SOL."""
    b = t.get("baseAmount") or {}
    try:
        return int(b.get("raw") or 0) / 10 ** int(b.get("decimals") or 6) * price_of(t)
    except (TypeError, ValueError):
        return 0.0


def analyze(http, coin):
    mint, c0 = coin["mint"], int(coin["created_timestamp"])
    t_buy, t_sell = c0 + BUY_MIN * 60_000, c0 + SELL_MIN * 60_000
    trades = fetch_all_trades(http, mint, stop_after_ms=t_sell + 1)
    px = [(int(t["blockTimeMs"]), price_of(t)) for t in trades if price_of(t) > 0]

    def at(ts):
        p = [v for t, v in px if t <= ts]
        return p[-1] if p else None

    pb, ps = at(t_buy), at(t_sell)
    pre = [t for t in trades if int(t["blockTimeMs"]) <= t_buy]
    buys = [t for t in pre if t.get("side") == "buy"]
    sells = [t for t in pre if t.get("side") == "sell"]
    per_buyer = defaultdict(float)
    for t in buys:
        per_buyer[(t.get("trader") or {}).get("address")] += usd_amount(t)
    buy_usd = sum(per_buyer.values())
    creator = coin.get("creator")
    creator_sold_usd_v = sum(usd_amount(t) for t in sells if (t.get("trader") or {}).get("address") == creator)
    max_after_buy = max([v for t, v in px if t_buy < t <= t_sell], default=None)
    r = {
        "mint": mint, "symbol": coin.get("symbol"),
        "ath_mcap_usd": coin.get("ath_market_cap"),
        "ath_after_min": round((int(coin.get("ath_market_cap_timestamp") or c0) - c0) / 60000, 1),
        "mcap_now_usd": coin.get("market_cap"),
        "complete": bool(coin.get("complete")),
        "price_min2": pb, "price_min10": ps,
        "f_buyers": len(per_buyer), "f_buys": len(buys), "f_sells": len(sells),
        "f_buy_usd": round(buy_usd, 1), "f_sell_usd": round(sum(usd_amount(t) for t in sells), 1),
        "f_top_buyer_share": round(max(per_buyer.values()) / buy_usd, 3) if buy_usd else None,
        "f_creator_sold_usd": round(creator_sold_usd_v, 1),
        "f_mult_min2_vs_first": round(pb / px[0][1], 2) if pb and px else None,
        "f_socials": int(bool(coin.get("twitter"))) + int(bool(coin.get("telegram"))) + int(bool(coin.get("website"))),
    }
    if pb and ps:
        r["gross_x"] = round(ps / pb, 3)
        r["net"] = round(ps / pb * (1 - COST) / (1 + COST) - 1, 4)
        r["max_x_2_10"] = round(max_after_buy / pb, 3) if max_after_buy else None
    return r


def report(rows):
    ok = [r for r in rows if "net" in r]
    active = [r for r in ok]
    win = [r for r in ok if r["net"] > 0]
    lose = [r for r in ok if r["net"] <= 0]
    no_trade = len(rows) - len(ok)
    print(f"\nprobka: {len(rows)} tokenow; z cena w min 2 i 10: {len(ok)}; bez transakcji do min 2/10: {no_trade}")
    if not ok:
        return
    nets = [r["net"] for r in ok]
    print(f"kup min 2 -> sprzedaj min 10 (netto, koszt 3%/strone): zyskownych {len(win)}/{len(ok)} = {len(win)/len(ok):.0%}, "
          f"srednia {st.mean(nets):+.1%}, mediana {st.median(nets):+.1%}, najlepszy {max(nets):+.0%}, najgorszy {min(nets):+.0%}")
    big = [r for r in ok if r["gross_x"] >= 2]
    print(f"x2 lub wiecej w min 10: {len(big)}")
    print("\ncecha w min 2               mediana ZYSKOWNE  mediana RESZTA")
    for f in ("f_buyers", "f_buys", "f_sells", "f_buy_usd", "f_sell_usd", "f_top_buyer_share", "f_creator_sold_usd",
              "f_mult_min2_vs_first", "f_socials"):
        a = [r[f] for r in win if r.get(f) is not None]
        b = [r[f] for r in lose if r.get(f) is not None]
        if a and b:
            print(f"  {f:<26} {st.median(a):>12}  {st.median(b):>14}")
    # ATH
    ath_w = [r["ath_mcap_usd"] for r in win if r.get("ath_mcap_usd")]
    ath_l = [r["ath_mcap_usd"] for r in lose if r.get("ath_mcap_usd")]
    if ath_w:
        print(f"\nATH mcap (USD) zyskowne: mediana {st.median(ath_w):,.0f}, max {max(ath_w):,.0f}; "
              f"czas do ATH mediana {st.median([r['ath_after_min'] for r in win]):.1f} min")
    if ath_l:
        print(f"ATH mcap (USD) reszta:   mediana {st.median(ath_l):,.0f}, max {max(ath_l):,.0f}")
    print(f"tokeny, ktore ukonczyly krzywa (migracja): {sum(r['complete'] for r in rows)}")
    print("\nTOP 10 wg zwrotu min2->min10:")
    for r in sorted(ok, key=lambda r: -r["net"])[:10]:
        print(f"  {str(r['symbol'])[:12]:<12} netto {r['net']:+.0%}  ATH ${r['ath_mcap_usd'] or 0:,.0f} po {r['ath_after_min']} min  "
              f"buyers={r['f_buyers']} buy_usd={r['f_buy_usd']} top={r['f_top_buyer_share']}  https://pump.fun/coin/{r['mint']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out")
    a = ap.parse_args()
    http = VerifiedHttpClient()
    now = time.time() * 1000
    coins = [c for c in list_coins(http, 250, 1100) if now - int(c["created_timestamp"]) >= 11 * 60_000]
    random.Random(a.seed).shuffle(coins)
    rows = []
    for i, c in enumerate(coins[: a.n], 1):
        try:
            rows.append(analyze(http, c))
        except (Exception, SystemExit) as e:  # noqa: BLE001
            print(f"  pominiety {c.get('symbol')}: {e}")
        if i % 25 == 0:
            print(f"[{i}/{min(a.n, len(coins))}]", flush=True)
    report(rows)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

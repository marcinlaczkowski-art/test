"""
Replay narzedzie (READ-ONLY, bez transakcji): dla podanego tokena pump.fun (mint lub link)
pobiera cala historie swapow i liczy ZAMROZONY scoring V2.2 w kolejnych minutach od startu.
Pokazuje, KIEDY system dalby sygnal i co by sie stalo z cena po sygnale.

Uzycie:
  python tools/replay_token.py <mint_lub_link> [--offsets 1,2,3,5,10,15,30,60] [--out plik.json]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings_v2_2 import DATA_SOURCES_REGISTRY, SOLANA_CHAIN_ID  # noqa: E402
from data_sources.http_client import VerifiedHttpClient  # noqa: E402
from data_integrity.temporal_ledger import TemporalIntegrityLedger  # noqa: E402
from wallet_intelligence.wallet_intel_v2_2 import WalletIntelligenceEngineV22  # noqa: E402
from feature_engine.feature_engine import CausalMarketRegimeTracker, SharedFeatureEngineV22  # noqa: E402
from scoring.confluence_scorer import score_multi_signal_confluence  # noqa: E402

MINT_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
OPEN_THRESHOLD = 34.0  # ten sam prog co w paper tradingu


def extract_mint(arg: str) -> str:
    m = re.search(r"/coin/([1-9A-HJ-NP-Za-km-z]{32,44})", arg)
    if m:
        return m.group(1)
    m = MINT_RE.search(arg)
    if not m:
        raise SystemExit("Nie znaleziono adresu mint w argumencie")
    return m.group(0)


def fetch_all_trades(http, mint: str, max_pages: int = 3000, stop_after_ms: int = 0) -> list:
    base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
    seen, out, after_ts = set(), [], 0
    for _ in range(max_pages):
        for attempt in range(6):  # lagodne tempo + ponowienia przy 429
            time.sleep(0.3)
            r = http.request_json(
                "pumpfun_v3", f"{base}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after=1-0-0-{after_ts}"
            )
            if r["ok"]:
                break
            time.sleep(2 ** attempt)
        if not r["ok"]:
            raise SystemExit(f"Blad pobierania transakcji: {r.get('error_message')}")
        page = (r["data"] or {}).get("trades", [])
        new = [t for t in page if t.get("ordinalKey") not in seen]
        if not page or (not new and len(page) < 100):
            break
        for t in new:
            seen.add(t["ordinalKey"])
        out.extend(new)
        last = max(int(t["blockTimeMs"]) for t in page)
        if not new:
            last += 1
        after_ts = last
        if stop_after_ms and last > stop_after_ms:
            break
        if len(page) < 100:
            break
    out.sort(key=lambda t: (int(t["blockTimeMs"]), int(t.get("txIndex") or 0), int(t.get("eventIndex") or 0)))
    return out


def fetch_candles(http, mint: str) -> list:
    base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
    r = http.request_json(
        "pumpfun_v3", f"{base}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={int(time.time() * 1000)}"
    )
    return (r["data"] or {}).get("candles", []) if r["ok"] else []


def fetch_meta(http, mint: str) -> dict:
    r = http.request_json("dexscreener_api", f"https://api.dexscreener.com/latest/dex/tokens/{mint}")
    pairs = (r["data"] or {}).get("pairs") or [] if r["ok"] else []
    return pairs[0] if pairs else {}


def price_of(t: dict) -> float:
    try:
        return float(t.get("priceUsd") or 0)
    except (TypeError, ValueError):
        return 0.0


def replay(mint: str, offsets_min: list, delays_s: tuple = (0, 30, 60, 120)) -> dict:
    http = VerifiedHttpClient()
    base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
    first = http.request_json("pumpfun_v3", f"{base}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=1&after=1-0-0-0")
    ft = ((first["data"] or {}).get("trades") or [{}])[0] if first["ok"] else {}
    t0 = int(ft.get("blockTimeMs") or 0)
    trades = fetch_all_trades(http, mint, stop_after_ms=t0 + int(max(offsets_min) * 60_000) + 300_000)
    if not trades:
        raise SystemExit("Brak transakcji dla tego mintu")
    candles = fetch_candles(http, mint)
    meta = fetch_meta(http, mint)
    created_ms = int(trades[0]["blockTimeMs"])
    coin = {
        "mint": mint,
        "created_timestamp": created_ms,
        "symbol": (meta.get("baseToken") or {}).get("symbol"),
        "name": (meta.get("baseToken") or {}).get("name"),
    }
    priced = [(int(t["blockTimeMs"]), price_of(t)) for t in trades if price_of(t) > 0]
    # wynik po sygnale z swiec 1m (pelny przebieg, nie tylko horyzont replay)
    cpx = sorted((int(c["openTimeMs"]), float(c["high"]), float(c["close"])) for c in candles if float(c.get("high") or 0) > 0)
    allpx = [(ts, h) for ts, h, _ in cpx] or priced
    peak_ts, peak_px = max(allpx, key=lambda x: x[1])
    last_px = cpx[-1][2] if cpx else priced[-1][1]

    def px_at(ts):
        p = [x for x in priced if x[0] <= ts]
        return p[-1][1] if p else 0.0

    rows = []
    first_signal = None
    for off in offsets_min:
        cutoff = created_ms + int(off * 60_000)
        if cutoff > priced[-1][0] + 60_000 and cutoff > created_ms + 60_000:
            break
        fe = SharedFeatureEngineV22(
            TemporalIntegrityLedger(), WalletIntelligenceEngineV22(), CausalMarketRegimeTracker()
        )
        try:
            snap = fe.compute_features(
                coin=coin, trades=trades, candles_1m=candles, decision_cutoff_ts_ms=cutoff,
                acquired_at_ms=cutoff, mode="validation", source_id="pumpfun_v3",
                source_health_status="HEALTHY", is_tape_complete=True,
                has_historical_availability_proof=True,
            )
            conf = score_multi_signal_confluence(snap)
        except Exception as e:  # noqa: BLE001 - narzedzie diagnostyczne
            rows.append({"offset_min": off, "error": f"{type(e).__name__}: {e}"})
            continue
        entry = px_at(cutoff)
        fut = [h for ts, h, _ in cpx if ts > cutoff] or [p for ts, p in priced if ts > cutoff]
        row = {
            "offset_min": off,
            "entry_price_usd": entry,
            "score": conf["total_score"],
            "class": conf["confluence_class"],
            "triggered": conf["triggered_hypotheses"],
            "risk_flags": conf["risk_flags"],
            "data_quality": conf["data_quality_score"],
            "would_open": conf["confluence_class"] not in ("INSUFFICIENT_DATA", "HIGH_RISK")
            and conf["total_score"] >= OPEN_THRESHOLD,
            "max_future_x": round(max(fut) / entry, 2) if fut and entry else None,
            "last_x": round(last_px / entry, 2) if entry else None,
            "components": conf["component_scores"],
            "delayed_entry": {},
        }
        for d in delays_s:  # wejscie z opoznieniem d sekund po sygnale
            e = px_at(cutoff + d * 1000)
            f = [h for ts, h, _ in cpx if ts > cutoff + d * 1000] or [p for ts, p in priced if ts > cutoff + d * 1000]
            row["delayed_entry"][str(d)] = {
                "entry_price_usd": e,
                "last_x": round(last_px / e, 2) if e else None,
                "max_future_x": round(max(f) / e, 2) if f and e else None,
            }
        if row["would_open"] and first_signal is None:
            first_signal = row
        rows.append(row)
    return {
        "mint": mint,
        "symbol": coin["symbol"],
        "created_at_ms": created_ms,
        "trades_fetched": len(trades),
        "peak_x_from_first_trade": round(peak_px / priced[0][1], 2) if priced[0][1] else None,
        "peak_after_min": round((peak_ts - created_ms) / 60000, 1),
        "last_vs_peak": round(last_px / peak_px, 3),
        "first_signal": first_signal,
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("token")
    ap.add_argument("--offsets", default="1,2,3,5,10,15,30,60,120")
    ap.add_argument("--delays", default="0,30,60,120", help="opoznienia wejscia w sekundach")
    ap.add_argument("--out")
    a = ap.parse_args()
    res = replay(extract_mint(a.token), [float(x) for x in a.offsets.split(",")],
                 tuple(int(x) for x in a.delays.split(",")))
    print(f"{res['symbol']} {res['mint']}  transakcji={res['trades_fetched']}")
    print(f"szczyt = {res['peak_x_from_first_trade']}x ceny pierwszej transakcji po {res['peak_after_min']} min; "
          f"cena teraz / szczyt = {res['last_vs_peak']}")
    print(f"{'min':>5} {'score':>6} {'klasa':<18} {'otworzylby':<10} {'max_przyszle':>12} {'teraz':>7}  flagi")
    for r in res["rows"]:
        if "error" in r:
            print(f"{r['offset_min']:>5}  BLAD {r['error']}")
            continue
        print(f"{r['offset_min']:>5} {r['score']:>6} {r['class']:<18} {str(r['would_open']):<10} "
              f"{str(r['max_future_x']):>12} {str(r['last_x']):>7}  {','.join(r['risk_flags'])}")
    print("wejscie z opoznieniem po sygnale (cena teraz / cena wejscia):")
    for r in res["rows"]:
        if "delayed_entry" in r:
            print(f"  sygnal min {r['offset_min']:>4}: " + "  ".join(
                f"+{d}s={v['last_x']}x" for d, v in r["delayed_entry"].items()))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

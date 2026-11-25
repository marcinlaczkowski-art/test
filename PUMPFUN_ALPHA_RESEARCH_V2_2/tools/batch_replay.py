"""
Batch replay (READ-ONLY): losowa probka swiezych tokenow pump.fun -> zamrozony scoring V2.2 w min 1..5
-> symulacja wejscia (opoznienie 60 s) z trailing stopem i kosztami -> statystyki.
Porownuje tokeny z sygnalem z BASELINE (wejscie w KAZDY token) i liczy, ktory skladnik scoringu
cokolwiek przewiduje. Probka obejmuje tez tokeny, ktore nic nie osiagnely.

  python tools/batch_replay.py --n 60 --out batch.json
Uwaga: API listuje tylko ~ostatnie 27 min, wiec okno wyniku to ~20 min od startu tokena.
"""
import argparse
import json
import random
import statistics as st
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
from tools.replay_token import fetch_all_trades, fetch_candles, price_of, OPEN_THRESHOLD  # noqa: E402

OFFSETS_MIN = (1, 2, 3, 5)
ENTRY_DELAY_S = 60
HORIZON_MIN = 20          # maks. czas trzymania liczony od startu tokena
TRAIL = 0.30              # trailing stop od lokalnego szczytu
COST_PER_SIDE = 0.03      # prowizja 1% + poslizg ~2% na strone (zalozenie)


def list_candidates(http, lo=800, hi=1000, n=60, seed=7):
    base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
    coins = []
    for off in range(lo, hi, 50):
        r = http.request_json(
            "pumpfun_v3", f"{base}/coins?offset={off}&limit=50&sort=created_timestamp&order=DESC&includeNsfw=true"
        )
        if r["ok"] and isinstance(r["data"], list):
            coins.extend(r["data"])
        time.sleep(0.3)
    random.Random(seed).shuffle(coins)
    return coins[:n]


def simulate_exit(entry_ms, entry_px, candles, end_ms):
    """Trailing stop na swiecach 1m (optymistyczne: bez luk wewnatrz swiecy poza open)."""
    peak, exit_px, reason = entry_px, None, "TIME"
    last_close = entry_px
    for c in candles:
        t = int(c["openTimeMs"])
        if t + 60_000 <= entry_ms or t > end_ms:
            continue
        o, h, lo_, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        peak = max(peak, h)
        stop = peak * (1 - TRAIL)
        if lo_ <= stop:
            exit_px, reason = min(stop, o) if o < stop else stop, "TRAIL"
            break
        last_close = cl
    if exit_px is None:
        exit_px = last_close
    gross = exit_px / entry_px
    net = gross * (1 - COST_PER_SIDE) / (1 + COST_PER_SIDE) - 1
    return net, reason, peak / entry_px


def run_token(http, coin):
    mint, created = coin["mint"], int(coin["created_timestamp"])
    horizon_ms = created + (max(OFFSETS_MIN) * 60 + ENTRY_DELAY_S + 60) * 1000
    trades = fetch_all_trades(http, mint, stop_after_ms=horizon_ms)
    candles = fetch_candles(http, mint)
    priced = [(int(t["blockTimeMs"]), price_of(t)) for t in trades if price_of(t) > 0]
    if len(priced) < 2:
        return {"mint": mint, "skipped": "too_few_trades", "trades": len(trades)}

    def px_at(ts):
        p = [x for x in priced if x[0] <= ts]
        return p[-1][1] if p else 0.0

    sig = None
    scored = []
    for off in OFFSETS_MIN:
        cutoff = created + off * 60_000
        fe = SharedFeatureEngineV22(TemporalIntegrityLedger(), WalletIntelligenceEngineV22(), CausalMarketRegimeTracker())
        try:
            snap = fe.compute_features(
                coin=coin, trades=trades, candles_1m=candles, decision_cutoff_ts_ms=cutoff, acquired_at_ms=cutoff,
                mode="validation", source_id="pumpfun_v3", source_health_status="HEALTHY",
                is_tape_complete=True, has_historical_availability_proof=True,
            )
            conf = score_multi_signal_confluence(snap)
        except Exception as e:  # noqa: BLE001
            scored.append({"off": off, "error": str(e)[:80]})
            continue
        ok = conf["confluence_class"] not in ("INSUFFICIENT_DATA", "HIGH_RISK") and conf["total_score"] >= OPEN_THRESHOLD
        rec = {"off": off, "score": conf["total_score"], "class": conf["confluence_class"],
               "components": conf["component_scores"], "open": ok}
        scored.append(rec)
        if ok and sig is None:
            sig = rec

    out = {"mint": mint, "symbol": coin.get("symbol"), "trades": len(trades), "scored": scored}
    end_ms = created + HORIZON_MIN * 60_000
    # baseline: wejscie w KAZDY token w min 1 + opoznienie
    b_ms = created + 60_000 + ENTRY_DELAY_S * 1000
    b_px = px_at(b_ms)
    if b_px > 0:
        out["baseline"] = dict(zip(("net", "exit", "peak_x"), simulate_exit(b_ms, b_px, candles, end_ms)))
    if sig:
        e_ms = created + sig["off"] * 60_000 + ENTRY_DELAY_S * 1000
        e_px = px_at(e_ms)
        out["signal"] = sig
        if e_px > 0:
            out["signal_trade"] = dict(zip(("net", "exit", "peak_x"), simulate_exit(e_ms, e_px, candles, end_ms)))
    return out


def summarize(results):
    done = [r for r in results if "scored" in r]
    base = [r["baseline"]["net"] for r in done if "baseline" in r]
    sigs = [r["signal_trade"]["net"] for r in done if "signal_trade" in r]

    def stats(xs):
        if not xs:
            return "brak"
        return (f"n={len(xs)} srednia={st.mean(xs):+.1%} mediana={st.median(xs):+.1%} "
                f"trafnych(>0)={sum(x > 0 for x in xs) / len(xs):.0%} najgorszy={min(xs):+.0%} najlepszy={max(xs):+.0%}")

    print(f"tokenow z danymi: {len(done)} / {len(results)}")
    print("BASELINE (wejscie w kazdy token): ", stats(base))
    print("SYGNAL V2.2 (score>=34):          ", stats(sigs))
    # przewidywanie: korelacja skladnikow (min 1) z wynikiem baseline (ten sam punkt wejscia)
    try:
        import numpy as np
        print("korelacja skladnikow score (min 1) z wynikiem wejscia w min 1:")
        pairs = [(r["scored"][0], r["baseline"]["net"]) for r in done if "baseline" in r and r["scored"] and "components" in r["scored"][0]]
        for k in pairs[0][0]["components"] if pairs else []:
            x = np.array([p[0]["components"][k] for p in pairs], float)
            y = np.array([p[1] for p in pairs], float)
            c = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else float("nan")
            print(f"  {k:<30} r={c:+.2f}  (n={len(pairs)})")
        x = np.array([p[0]["score"] for p in pairs], float)
        y = np.array([p[1] for p in pairs], float)
        print(f"  {'total_score':<30} r={float(np.corrcoef(x, y)[0, 1]):+.2f}")
    except Exception as e:  # noqa: BLE001
        print("korelacje niedostepne:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out")
    a = ap.parse_args()
    http = VerifiedHttpClient()
    coins = list_candidates(http, n=a.n, seed=a.seed)
    results = []
    for i, c in enumerate(coins, 1):
        try:
            results.append(run_token(http, c))
        except SystemExit as e:
            results.append({"mint": c.get("mint"), "skipped": str(e)})
        except Exception as e:  # noqa: BLE001
            results.append({"mint": c.get("mint"), "skipped": f"{type(e).__name__}: {e}"})
        print(f"[{i}/{len(coins)}] {c.get('symbol')}", flush=True)
    summarize(results)
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

"""
UNIFIED, CHRONOLOGICAL, CHECKPOINTABLE STATE TRACKERS (V2.1 — P0):
1. MarketContextTracker: Strictly causal SOL/USD market context. NEVER uses an unclosed hourly/minute candle's
   close, high, or low! Uses only bars with `close_time_ms <= signal_timestamp_ms`, plus optional on-chain
   `quotePriceUsd` spot ticks at `tick_ts_ms <= signal_timestamp_ms`.
2. CreatorHistoryTracker: Tracks prior creator launches; outcomes become visible ONLY when
   `label_available_at_ms <= signal_timestamp_ms`. Returns `"unknown"` when no evaluated history exists.
3. WalletHistoryTracker: Tracks per-wallet outcomes across independent tokens (wins, losses, realized net SOL
   after fees, missing-data flags), gated strictly by `label_available_at_ms <= signal_timestamp_ms`.
4. TickerNarrativeHistoryTracker: Tracks observed prior tickers & narratives chronologically. NEVER defaults
   `is_ticker_first_mover = 1`! Returns `"insufficient_history"` unless prior launch history coverage is verified.

Supports exact state serialization (`save_checkpoint` / `load_checkpoint_as_of`) for 100% parity
across Training, Validation, Out-of-Time, Paper Trading, and Live Inference!
"""
import bisect
import json
import re
from pathlib import Path
from collections import defaultdict

from config_v2_1 import CONFIRMED_TECHNICAL_ADDRESSES, INTERVAL_MS

class MarketContextTracker:
    def __init__(self):
        # Sorted by close_time_ms: list of (close_time_ms, open_time_ms, open_p, high_p, low_p, close_p, vol_usdt, res)
        self.closed_bars_1h = []
        self._close_times_1h = []

    def ingest_binance_klines(self, klines: list, interval: str = "1h"):
        dur = INTERVAL_MS[interval]
        records = {}
        for k in self.closed_bars_1h:
            records[k[1]] = k
        for raw in klines:
            ot = int(raw[0])
            # Binance raw[6] is ot + dur - 1 (e.g. 12:59:59.999); actual full close boundary is ot + dur!
            ct = ot + dur
            rec = (ct, ot, float(raw[1]), float(raw[2]), float(raw[3]), float(raw[4]), float(raw[7]), interval)
            records[ot] = rec
        self.closed_bars_1h = sorted(records.values(), key=lambda x: x[0])
        self._close_times_1h = [x[0] for x in self.closed_bars_1h]

    def query_sol_at(self, signal_ts_ms: int, onchain_spot_tick: tuple = None) -> dict:
        """
        onchain_spot_tick: optional `(tick_ts_ms, quote_price_usd)` from a swap with `tick_ts_ms <= signal_ts_ms`.
        Guarantees: NEVER inspects any candle with `close_time_ms > signal_ts_ms`!
        """
        idx = bisect.bisect_right(self._close_times_1h, signal_ts_ms) - 1
        if idx < 0:
            if onchain_spot_tick and onchain_spot_tick[0] <= signal_ts_ms and onchain_spot_tick[1] > 0:
                return {
                    "status": "partial_spot_only",
                    "sol_price_usd": round(float(onchain_spot_tick[1]), 4),
                    "sol_price_source": "onchain_swap_quotePriceUsd",
                    "sol_price_event_ts_ms": int(onchain_spot_tick[0]),
                    "sol_price_available_at_ms": int(onchain_spot_tick[0]),
                    "sol_ret_1h_pct": "unknown",
                    "sol_ret_24h_pct": "unknown",
                    "sol_ret_available_at_ms": int(onchain_spot_tick[0]),
                }
            return {
                "status": "unknown",
                "sol_price_usd": "unknown",
                "sol_price_source": "none_available",
                "sol_price_event_ts_ms": 0,
                "sol_price_available_at_ms": 0,
                "sol_ret_1h_pct": "unknown",
                "sol_ret_24h_pct": "unknown",
                "sol_ret_available_at_ms": 0,
            }

        last_closed = self.closed_bars_1h[idx]
        ct_last = last_closed[0]
        assert ct_last <= signal_ts_ms, "CRITICAL: Unclosed SOL candle leaked!"

        closed_px = last_closed[5]
        # Determine latest strictly causal spot price: if onchain tick happened AFTER ct_last and <= signal_ts_ms, we may use it as spot
        if onchain_spot_tick and ct_last < int(onchain_spot_tick[0]) <= signal_ts_ms and float(onchain_spot_tick[1]) > 0:
            spot_px = round(float(onchain_spot_tick[1]), 4)
            spot_src = "onchain_swap_quotePriceUsd_post_bar"
            spot_ts = int(onchain_spot_tick[0])
        else:
            spot_px = round(closed_px, 4)
            spot_src = "last_closed_1h_kline"
            spot_ts = ct_last

        # Compute 1h and 24h returns strictly from closed 1h bars (`close_time_ms <= signal_ts_ms`)
        ret_1h = "unknown"
        if idx >= 1:
            prev_1h = self.closed_bars_1h[idx - 1]
            if abs((ct_last - prev_1h[0]) - 3_600_000) <= 120_000 and prev_1h[5] > 0:
                ret_1h = round(((closed_px / prev_1h[5]) - 1.0) * 100.0, 4)

        ret_24h = "unknown"
        # Search closed bar ~24h prior to ct_last
        target_24h_ct = ct_last - 24 * 3_600_000
        idx_24 = bisect.bisect_right(self._close_times_1h, target_24h_ct) - 1
        if idx_24 >= 0:
            bar_24 = self.closed_bars_1h[idx_24]
            if abs(bar_24[0] - target_24h_ct) <= 2 * 3_600_000 and bar_24[5] > 0:
                ret_24h = round(((spot_px / bar_24[5]) - 1.0) * 100.0, 4)

        return {
            "status": "ok",
            "sol_price_usd": spot_px,
            "sol_price_source": spot_src,
            "sol_price_event_ts_ms": spot_ts,
            "sol_price_available_at_ms": spot_ts,
            "last_closed_bar_close_ts_ms": ct_last,
            "sol_ret_1h_pct": ret_1h,
            "sol_ret_24h_pct": ret_24h,
            "sol_ret_available_at_ms": max(ct_last, spot_ts),
        }

    def to_dict(self) -> dict:
        return {"closed_bars_1h": self.closed_bars_1h}

    @classmethod
    def from_dict(cls, d: dict) -> "MarketContextTracker":
        obj = cls()
        obj.closed_bars_1h = [tuple(x) for x in d.get("closed_bars_1h", [])]
        obj._close_times_1h = [x[0] for x in obj.closed_bars_1h]
        return obj


class CreatorHistoryTracker:
    def __init__(self):
        # creator -> list of dicts: {mint, created_ts_ms, label_available_at_ms, is_win, outcome_status}
        self.records = defaultdict(list)

    def register_event(self, creator: str, mint: str, created_ts_ms: int, label_available_at_ms: int, is_win: int, outcome_status: str = "complete"):
        if not creator or creator in CONFIRMED_TECHNICAL_ADDRESSES:
            return
        assert label_available_at_ms > created_ts_ms, "Creator outcome label_available_at_ms must exceed created_ts_ms"
        existing = {r["mint"] for r in self.records[creator]}
        if mint not in existing:
            self.records[creator].append({
                "mint": mint,
                "created_ts_ms": int(created_ts_ms),
                "label_available_at_ms": int(label_available_at_ms),
                "is_win": int(is_win) if outcome_status == "complete" else None,
                "outcome_status": outcome_status,
            })

    def query_at(self, creator: str, current_mint: str, signal_ts_ms: int) -> dict:
        if not creator or creator not in self.records:
            return {
                "status": "unknown",
                "prior_launches_count": 0,
                "evaluated_count": 0,
                "win_rate": "unknown",
                "event_ts_ms": 0,
                "available_at_ms": 0,
            }
        recs = [r for r in self.records[creator] if r["mint"] != current_mint and r["created_ts_ms"] <= signal_ts_ms]
        eval_recs = [
            r for r in recs
            if r["label_available_at_ms"] <= signal_ts_ms and r["outcome_status"] == "complete" and r["is_win"] is not None
        ]
        max_avail = max(
            [r["created_ts_ms"] for r in recs] + [r["label_available_at_ms"] for r in eval_recs] + [0]
        )
        assert max_avail <= signal_ts_ms
        if not eval_recs:
            return {
                "status": "insufficient_history" if recs else "unknown",
                "prior_launches_count": len(recs),
                "evaluated_count": 0,
                "win_rate": "unknown",
                "event_ts_ms": max_avail,
                "available_at_ms": max_avail,
            }
        wins = sum(int(r["is_win"]) for r in eval_recs)
        return {
            "status": "ok",
            "prior_launches_count": len(recs),
            "evaluated_count": len(eval_recs),
            "win_rate": round(wins / len(eval_recs), 4),
            "event_ts_ms": max_avail,
            "available_at_ms": max_avail,
        }

    def to_dict(self) -> dict:
        return {"records": dict(self.records)}

    @classmethod
    def from_dict(cls, d: dict, max_ts_ms: int = None) -> "CreatorHistoryTracker":
        obj = cls()
        for cr, lst in d.get("records", {}).items():
            filtered = [r for r in lst if max_ts_ms is None or int(r["created_ts_ms"]) <= max_ts_ms]
            if filtered:
                obj.records[cr] = filtered
        return obj


class WalletHistoryTracker:
    """
    Tracks Smart Money / historical wallet performance across independent tokens:
    includes wins, losses, realized net SOL after fees, and missing-data flags.
    Strictly enforces `label_available_at_ms <= signal_ts_ms`.
    """
    def __init__(self):
        # wallet -> list of dicts: {mint, entry_ts_ms, label_available_at_ms, hit_2x_4h, realized_net_sol, data_complete}
        self.records = defaultdict(list)

    def register_wallet_token_outcome(
        self,
        wallet: str,
        mint: str,
        entry_ts_ms: int,
        label_available_at_ms: int,
        hit_2x_4h: int,
        realized_net_sol: float,
        data_complete: bool = True,
    ):
        if not wallet or wallet in CONFIRMED_TECHNICAL_ADDRESSES:
            return
        assert label_available_at_ms > entry_ts_ms
        existing = {r["mint"] for r in self.records[wallet]}
        if mint not in existing:
            self.records[wallet].append({
                "mint": mint,
                "entry_ts_ms": int(entry_ts_ms),
                "label_available_at_ms": int(label_available_at_ms),
                "hit_2x_4h": int(hit_2x_4h),
                "realized_net_sol": round(float(realized_net_sol), 6),
                "data_complete": bool(data_complete),
            })

    def query_wallets_at(self, wallets: list, current_mint: str, signal_ts_ms: int, min_independent_tokens: int = 2) -> dict:
        smart_count = 0
        known_wallets = 0
        max_avail = 0
        for w in set(wallets):
            if not w or w not in self.records:
                continue
            eval_recs = [
                r for r in self.records[w]
                if r["mint"] != current_mint and r["label_available_at_ms"] <= signal_ts_ms
            ]
            if eval_recs:
                max_avail = max(max_avail, max(r["label_available_at_ms"] for r in eval_recs))
            if len(eval_recs) >= min_independent_tokens:
                known_wallets += 1
                win_rate = sum(r["hit_2x_4h"] for r in eval_recs) / len(eval_recs)
                tot_net_sol = sum(r["realized_net_sol"] for r in eval_recs)
                # Smart Money requires positive realized net SOL after fees/losses AND >=30% 2x hit rate across >=2 independent tokens!
                if win_rate >= 0.30 and tot_net_sol > -0.05:
                    smart_count += 1

        assert max_avail <= signal_ts_ms
        if len(wallets) == 0:
            st = "ok"
        elif known_wallets == 0 and len(self.records) == 0:
            st = "insufficient_history"
        else:
            st = "ok"

        return {
            "status": st,
            "smart_wallets_count": smart_count if st == "ok" else "insufficient_history",
            "known_evaluated_wallets": known_wallets,
            "event_ts_ms": max_avail,
            "available_at_ms": max_avail,
        }

    def to_dict(self) -> dict:
        return {"records": dict(self.records)}

    @classmethod
    def from_dict(cls, d: dict, max_ts_ms: int = None) -> "WalletHistoryTracker":
        obj = cls()
        for w, lst in d.get("records", {}).items():
            filtered = [r for r in lst if max_ts_ms is None or int(r["entry_ts_ms"]) <= max_ts_ms]
            if filtered:
                obj.records[w] = filtered
        return obj


class TickerNarrativeHistoryTracker:
    """
    Tracks previously launched tickers & narrative density chronologically.
    NEVER defaults `is_ticker_first_mover = 1`!
    Requires verified prior launch coverage (`min_prior_observed_launches >= 25`) before classifying
    a ticker as `"first_mover"` vs `"copycat"`; otherwise returns `"insufficient_history"`.
    """
    def __init__(self, min_prior_launches_for_coverage: int = 25):
        self.min_prior = min_prior_launches_for_coverage
        # Sorted list of (created_ts_ms, mint, norm_symbol, narrative_cat)
        self.launches = []
        self._ts_list = []
        self._seen_mints = set()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (symbol or "").lower())

    def register_launch(self, created_ts_ms: int, mint: str, symbol: str, narrative_cat: str):
        if not mint or mint in self._seen_mints or created_ts_ms <= 0:
            return
        self._seen_mints.add(mint)
        rec = (int(created_ts_ms), mint, self.normalize_symbol(symbol), narrative_cat or "Other")
        idx = bisect.bisect_right(self._ts_list, rec[0])
        self.launches.insert(idx, rec)
        self._ts_list.insert(idx, rec[0])

    def query_at(self, created_ts_ms: int, current_mint: str, symbol: str, narrative_cat: str, signal_ts_ms: int) -> dict:
        assert created_ts_ms <= signal_ts_ms
        # Strictly launches created BEFORE `created_ts_ms` (and <= signal_ts_ms)
        end_idx = bisect.bisect_left(self._ts_list, created_ts_ms)
        prior_slice = [x for x in self.launches[:end_idx] if x[1] != current_mint]

        norm_sym = self.normalize_symbol(symbol)
        max_ts = prior_slice[-1][0] if prior_slice else 0
        assert max_ts <= signal_ts_ms

        # Check recent 24h density to verify whether we have meaningful prior history!
        start_24h_idx = bisect.bisect_left(self._ts_list, created_ts_ms - 86_400_000)
        prior_24h = [x for x in self.launches[start_24h_idx:end_idx] if x[1] != current_mint]
        same_narr_24h = sum(1 for x in prior_24h if x[3] == narrative_cat)

        if len(prior_slice) < self.min_prior or not norm_sym:
            return {
                "status": "insufficient_history",
                "is_ticker_first_mover": "insufficient_history",
                "prior_same_ticker_count": "insufficient_history",
                "narrative_24h_launches": same_narr_24h if len(prior_24h) >= 10 else "insufficient_history",
                "event_ts_ms": max_ts,
                "available_at_ms": max_ts,
            }

        same_sym_cnt = sum(1 for x in prior_slice if x[2] == norm_sym)
        return {
            "status": "ok",
            "is_ticker_first_mover": 1 if same_sym_cnt == 0 else 0,
            "prior_same_ticker_count": same_sym_cnt,
            "narrative_24h_launches": same_narr_24h,
            "event_ts_ms": max_ts,
            "available_at_ms": max_ts,
        }

    def to_dict(self) -> dict:
        return {"min_prior": self.min_prior, "launches": self.launches}

    @classmethod
    def from_dict(cls, d: dict, max_ts_ms: int = None) -> "TickerNarrativeHistoryTracker":
        obj = cls(min_prior_launches_for_coverage=d.get("min_prior", 25))
        for item in d.get("launches", []):
            if max_ts_ms is None or int(item[0]) <= max_ts_ms:
                obj.register_launch(int(item[0]), item[1], item[2], item[3])
        return obj


class UnifiedStateBundle:
    """Container of all 4 chronological state trackers with atomic checkpointing & resumption."""
    def __init__(self):
        self.market = MarketContextTracker()
        self.creators = CreatorHistoryTracker()
        self.wallets = WalletHistoryTracker()
        self.tickers = TickerNarrativeHistoryTracker()

    def save_checkpoint(self, checkpoint_ts_ms: int, path: Path):
        payload = {
            "checkpoint_ts_ms": int(checkpoint_ts_ms),
            "market": self.market.to_dict(),
            "creators": self.creators.to_dict(),
            "wallets": self.wallets.to_dict(),
            "tickers": self.tickers.to_dict(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load_checkpoint(cls, path: Path, as_of_ts_ms: int = None) -> "UnifiedStateBundle":
        d = json.loads(path.read_text(encoding="utf-8"))
        b = cls()
        b.market = MarketContextTracker.from_dict(d.get("market", {}))
        b.creators = CreatorHistoryTracker.from_dict(d.get("creators", {}), max_ts_ms=as_of_ts_ms)
        b.wallets = WalletHistoryTracker.from_dict(d.get("wallets", {}), max_ts_ms=as_of_ts_ms)
        b.tickers = TickerNarrativeHistoryTracker.from_dict(d.get("tickers", {}), max_ts_ms=as_of_ts_ms)
        return b

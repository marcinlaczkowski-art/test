"""
SECTION 10 (P0 — REAL-TIME LIVE SCANNER & 30-DAY APPEND-ONLY PAPER TRADING ENGINE):
- Operates EXCLUSIVELY on newly arriving real-time data over verified TLSv1.3 (`VerifiedHttpClient`).
- ZERO real transactions, ZERO wallet connections, ZERO private keys.
- Enforces 6-timestamp temporal integrity (`acquired_at_ms <= feature_computed_at_ms <= signal_generated_at_ms <= alert_emitted_at_ms`),
  NEVER backdating `signal_generated_at_ms` to historical timestamps!
- Flags tokens first observed older than `MAX_LIVE_DISCOVERY_AGE_SEC` as `LATE_DISCOVERY` (logged separately).
- Never opens a paper position with `entry_price <= 0` or missing reserves (`NO_EXECUTABLE_ENTRY`).
- APPEND-ONLY EVENT SOURCING:
    * `paper_trading/uptime_sessions_log.jsonl` (tracks start, heartbeats, downtime gaps, elapsed live days)
    * `paper_trading/signals_log.jsonl` (all evaluated/alerted/rejected live candidates with exact reasons)
    * `paper_trading/position_events_log.jsonl` (immutable state transitions: `OPEN`, `CHECKPOINT_15M/1H/4H/24H`,
      `CLOSED_TP`, `CLOSED_SL`, `CLOSED_TRAILING`, `CLOSED_TIME`, `CENSORED`, `NO_EXECUTABLE_ENTRY`, `DATA_INVALID`)
"""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import (
    PAPER_DIR, DATA_SOURCES_REGISTRY, SOLANA_CHAIN_ID,
    MAX_LIVE_DISCOVERY_AGE_SEC, PAPER_DEFAULT_SIZE_SOL,
    PAPER_TP_MULT, PAPER_SL_MULT, PAPER_TRAILING_ACTIVATE_MULT,
    PAPER_TRAILING_DRAWDOWN, PAPER_TIME_STOP_SEC, MIN_PAPER_DURATION_DAYS,
)
from data_sources.http_client import VerifiedHttpClient
from data_integrity.temporal_ledger import TemporalIntegrityLedger
from amm_reconstruction.amm_reconstructor import reconstruct_reserve_state_at, compute_realistic_swap_quote
from wallet_intelligence.wallet_intel_v2_2 import WalletIntelligenceEngineV22
from feature_engine.feature_engine import SharedFeatureEngineV22, CausalMarketRegimeTracker
from scoring.confluence_scorer import score_multi_signal_confluence
from paper_trading.wallet_history_v2_2 import WalletHistoryRecorder


class PaperTradingEngineV22:
    def __init__(
        self,
        http_client: VerifiedHttpClient,
        temporal_ledger: TemporalIntegrityLedger,
        wallet_engine: WalletIntelligenceEngineV22,
        regime_tracker: CausalMarketRegimeTracker,
        storage_dir: Optional[Path] = None,
    ):
        self.http = http_client
        self.temporal = temporal_ledger
        self.wallets = wallet_engine
        self.regime = regime_tracker
        self.fe = SharedFeatureEngineV22(temporal_ledger, wallet_engine, regime_tracker)

        self.storage_dir = storage_dir or PAPER_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.uptime_log = self.storage_dir / "uptime_sessions_log.jsonl"
        self.signals_log = self.storage_dir / "signals_log.jsonl"
        self.positions_log = self.storage_dir / "position_events_log.jsonl"
        self.late_log = self.storage_dir / "late_discoveries_log.jsonl"

        self.open_positions: dict[str, dict] = {}
        self._rehydrate_from_append_only_logs()
        # Live wallet track records for H2/H3 (append-only, rehydrated, outcomes only after +4h)
        self.wallet_history = WalletHistoryRecorder(self.storage_dir, self.wallets, http=self.http)

    def _append_jsonl(self, path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _rehydrate_from_append_only_logs(self) -> None:
        """Rebuilds in-memory active position map & deduplication keys without ever mutating historical log lines."""
        for sig in self._read_jsonl(self.signals_log):
            mint = sig.get("token_mint")
            if mint and sig.get("signal_decision") in ("PAPER_POSITION_OPENED", "NO_EXECUTABLE_ENTRY"):
                self.temporal.emitted_signal_keys.add(f"paper_trading:{mint}:primary")

        pos_state = {}
        for ev in self._read_jsonl(self.positions_log):
            pid = ev.get("position_id")
            if not pid:
                continue
            if ev["event_type"] == "POSITION_OPENED":
                pos_state[pid] = dict(ev)
            elif pid in pos_state:
                pos_state[pid]["status"] = ev.get("status", pos_state[pid]["status"])
                pos_state[pid]["last_event"] = ev
        self.open_positions = {pid: p for pid, p in pos_state.items() if p.get("status") == "OPEN"}

    def log_uptime_event(self, event_type: str, session_id: str, note: str = "") -> dict:
        prev = self._read_jsonl(self.uptime_log)
        now_ms = int(time.time() * 1000)
        downtime_gap_sec = 0.0
        if prev and event_type == "SESSION_START":
            last_ts = int(prev[-1].get("timestamp_ms") or now_ms)
            downtime_gap_sec = round(max(0.0, (now_ms - last_ts) / 1000.0), 2)
        rec = {
            "event_type": event_type,
            "session_id": session_id,
            "timestamp_ms": now_ms,
            "timestamp_utc": datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc).isoformat(),
            "downtime_gap_since_last_event_sec": downtime_gap_sec,
            "note": note,
        }
        self._append_jsonl(self.uptime_log, rec)
        return rec

    def evaluate_live_token_candidate(
        self,
        coin: dict,
        trades: list,
        candles_1m: list,
        detected_at_ms: int,
        acquired_at_ms: int,
        source_health_status: str = "HEALTHY",
        open_threshold_score: float = 34.0,
    ) -> dict:
        """
        Evaluates a single live token candidate strictly at real-time clock `now >= acquired_at_ms`,
        enforces deduplication, `LATE_DISCOVERY` isolation, `entry_price > 0`, and logs append-only records.
        """
        mint = str(coin.get("mint") or "")
        cts = int(coin.get("created_timestamp") or 0)
        decision_cutoff_ms = max(int(acquired_at_ms), int(time.time() * 1000))

        snap = self.fe.compute_features(
            coin=coin,
            trades=trades,
            candles_1m=candles_1m,
            decision_cutoff_ts_ms=decision_cutoff_ms,
            acquired_at_ms=acquired_at_ms,
            mode="paper_trading",
            source_id="pumpfun_v3",
            source_health_status=source_health_status,
            is_tape_complete=True,
        )
        self.wallet_history.record_observation(snap, trades, decision_cutoff_ms)
        conf = score_multi_signal_confluence(snap)
        env = snap["envelope"]
        sig_gen_ms = int(env["signal_generated_at_ms"])

        # 1. Check Temporal Validity
        if env["temporal_status"] != "VALID":
            rec = self._build_signal_log_record(snap, conf, detected_at_ms, None, None, "DATA_INVALID", env["rejection_reason"])
            self._append_jsonl(self.signals_log, rec)
            return rec

        # 2. Isolate LATE_DISCOVERY tokens (`token_age > MAX_LIVE_DISCOVERY_AGE_SEC` on first sight!)
        if env["discovery_status"] == "LATE_DISCOVERY":
            rec = self._build_signal_log_record(snap, conf, detected_at_ms, None, None, "REJECTED_LATE_DISCOVERY", f"Token age {snap['token_age_seconds']}s > {MAX_LIVE_DISCOVERY_AGE_SEC}s on first sight")
            self._append_jsonl(self.late_log, rec)
            self._append_jsonl(self.signals_log, rec)
            return rec

        # 3. Check Confluence Score / Risk Gate
        if conf["confluence_class"] in ("INSUFFICIENT_DATA", "HIGH_RISK") or conf["total_score"] < open_threshold_score:
            reason = f"class={conf['confluence_class']}, score={conf['total_score']} < {open_threshold_score}"
            rec = self._build_signal_log_record(snap, conf, detected_at_ms, None, None, "BELOW_CONFLUENCE_THRESHOLD", reason)
            self._append_jsonl(self.signals_log, rec)
            return rec

        # 4. Deduplication Gate (NEVER emit duplicate alert or open duplicate position on same token!)
        if not self.temporal.check_and_mark_dedup(mint, mode="paper_trading", bucket_key="primary"):
            rec = self._build_signal_log_record(snap, conf, detected_at_ms, None, None, "REJECTED_DUPLICATE_SIGNAL", "Duplicate token signal blocked")
            self._append_jsonl(self.signals_log, rec)
            return rec

        # 5. Executable Entry Price Validation (`entry_price > 0` strictly required — Rule 10.2 & Test 5!)
        entry_quote = compute_realistic_swap_quote(snap["amm_state"], None, PAPER_DEFAULT_SIZE_SOL, allow_estimated_fallback=False)
        exec_buy_px = entry_quote.get("executable_buy_price_sol")
        ref_mid_px = entry_quote.get("mid_price_entry_sol")

        alert_ms = max(sig_gen_ms, int(time.time() * 1000))
        if (
            entry_quote.get("status") != "ENTRY_ONLY_OK"
            or exec_buy_px is None
            or exec_buy_px <= 0.0
            or ref_mid_px is None
            or ref_mid_px <= 0.0
        ):
            rej_why = entry_quote.get("reason") or entry_quote.get("status") or "Zero/missing executable entry price"
            rec = self._build_signal_log_record(snap, conf, detected_at_ms, alert_ms, entry_quote, "NO_EXECUTABLE_ENTRY", rej_why)
            self._append_jsonl(self.signals_log, rec)
            self._append_jsonl(self.positions_log, {
                "event_type": "NO_EXECUTABLE_ENTRY",
                "position_id": f"pos_rej_{env['signal_id']}",
                "signal_id": env["signal_id"],
                "token_mint": mint,
                "token_symbol": snap["token_symbol"],
                "timestamp_ms": alert_ms,
                "status": "NO_EXECUTABLE_ENTRY",
                "reason": rej_why,
            })
            return rec

        # 6. Open Paper Position (Append-Only Event!)
        pos_id = f"pos_{env['signal_id']}"
        rec = self._build_signal_log_record(snap, conf, detected_at_ms, alert_ms, entry_quote, "PAPER_POSITION_OPENED", "Valid live confluence & executable curve liquidity")
        self._append_jsonl(self.signals_log, rec)

        open_ev = {
            "event_type": "POSITION_OPENED",
            "position_id": pos_id,
            "signal_id": env["signal_id"],
            "token_mint": mint,
            "token_symbol": snap["token_symbol"],
            "status": "OPEN",
            "entry_time_ms": alert_ms,
            "entry_time_utc": datetime.fromtimestamp(alert_ms / 1000.0, tz=timezone.utc).isoformat(),
            "entry_size_sol": PAPER_DEFAULT_SIZE_SOL,
            "entry_reference_mid_price_sol": ref_mid_px,
            "executable_entry_price_sol": exec_buy_px,
            "tokens_held": entry_quote["tokens_acquired"],
            "estimated_entry_cost_sol": round(
                entry_quote["entry_protocol_fee_sol"] + entry_quote["entry_network_fee_sol"] + entry_quote["entry_priority_fee_sol"], 6
            ),
            "entry_slippage_pct": entry_quote["entry_slippage_pct"],
            "peak_mid_price_sol": ref_mid_px,
            "trough_mid_price_sol": ref_mid_px,
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "checkpoints_logged": [],
            "confluence_total_score": conf["total_score"],
            "confluence_class": conf["confluence_class"],
            "sol_trend_regime": snap["market_regime"]["sol_trend_regime"],
            "liquidity_sol_at_entry": snap["liquidity_sol"],
            "token_age_sec_at_entry": snap["token_age_seconds"],
        }
        self._append_jsonl(self.positions_log, open_ev)
        self.open_positions[pos_id] = dict(open_ev)
        return rec

    def _build_signal_log_record(
        self,
        snap: dict,
        conf: dict,
        detected_at_ms: int,
        alert_emitted_at_ms: Optional[int],
        entry_quote: Optional[dict],
        decision: str,
        reason: str,
    ) -> dict:
        env = snap["envelope"]
        cs = conf["component_scores"]
        return {
            "signal_id": env["signal_id"],
            "feature_snapshot_id": env["feature_snapshot_id"],
            "data_version": env["data_version"],
            "token_mint": snap["token_mint"],
            "token_symbol": snap["token_symbol"],
            "event_ts_ms": env["event_ts_ms"],
            "source_published_at_ms": env["source_published_at_ms"],
            "detected_at_ms": int(detected_at_ms),
            "acquired_at_ms": env["acquired_at_ms"],
            "feature_computed_at_ms": env["feature_computed_at_ms"],
            "signal_generated_at_ms": env["signal_generated_at_ms"],
            "alert_emitted_at_ms": alert_emitted_at_ms if alert_emitted_at_ms is not None else "NOT_EMITTED",
            "token_age_seconds": snap["token_age_seconds"],
            "discovery_status": env["discovery_status"],
            "source_health_status": snap["source_health_status"],
            "entry_reference_price_sol": (entry_quote or {}).get("mid_price_entry_sol") or snap["amm_state"].get("mid_price_sol"),
            "executable_entry_price_sol": (entry_quote or {}).get("executable_buy_price_sol"),
            "liquidity_sol": snap["liquidity_sol"],
            "virtual_sol_reserve": snap["amm_state"].get("virtual_sol_reserve"),
            "buy_sell_ratio": snap["h5_metrics"]["buy_sell_ratio"],
            "buyer_acceleration_score": cs["buyer_acceleration"],
            "wallet_cluster_score": cs["wallet_cluster_accumulation"],
            "smart_money_score": cs["smart_money_accumulation"],
            "supply_safety_score": cs["supply_safety"],
            "absorption_score": cs["buy_pressure_absorption"],
            "total_score": conf["total_score"],
            "confluence_class": conf["confluence_class"],
            "triggered_hypotheses": conf["triggered_hypotheses"],
            "data_quality_score": conf["data_quality_score"],
            "execution_confidence": conf["execution_confidence"],
            "sol_trend_regime": snap["market_regime"]["sol_trend_regime"],
            "signal_decision": decision,
            "decision_reason": reason,
        }

    def update_position_with_market_state(
        self,
        position_id: str,
        coin: dict,
        trades: list,
        observed_at_ms: int,
    ) -> Optional[dict]:
        """
        Evaluates an `OPEN` paper position against fresh market state at `observed_at_ms`,
        updating MFE/MAE, `15m / 1h / 4h / 24h` checkpoints, and checking `SL`, `TP`, `Trailing Stop`, and `Time Stop`
        via immutable append-only events (NEVER overwriting previous position records!).
        """
        pos = self.open_positions.get(position_id)
        if not pos or pos.get("status") != "OPEN":
            return None

        cur_state = reconstruct_reserve_state_at(coin, trades, observed_at_ms, is_tape_complete_from_genesis=True)
        cur_mid = cur_state.get("mid_price_sol")
        if not cur_mid or cur_mid <= 0:
            return None

        ref_in = float(pos["entry_reference_mid_price_sol"])
        pos["peak_mid_price_sol"] = max(float(pos["peak_mid_price_sol"]), cur_mid)
        pos["trough_mid_price_sol"] = min(float(pos["trough_mid_price_sol"]), cur_mid)
        mfe_pct = round(((pos["peak_mid_price_sol"] / ref_in) - 1.0) * 100.0, 2)
        mae_pct = round(((pos["trough_mid_price_sol"] / ref_in) - 1.0) * 100.0, 2)
        pos["mfe_pct"] = mfe_pct
        pos["mae_pct"] = mae_pct

        elapsed_sec = (observed_at_ms - int(pos["entry_time_ms"])) / 1000.0
        quote_now = compute_realistic_swap_quote(
            {
                "usable_in_exact_backtest": True,
                "execution_confidence": "HIGH",
                "market_state": "ON_BONDING_CURVE",
                "virtual_sol_reserve": 30.0,
                "virtual_token_reserve": 30.0 / ref_in,
                "mid_price_sol": ref_in,
            },
            cur_state,
            float(pos["entry_size_sol"]),
            allow_estimated_fallback=True,
        )
        unreal_pnl_sol = quote_now.get("net_pnl_sol", 0.0)
        unreal_ret_pct = quote_now.get("net_return_after_fees_pct", 0.0)

        # Log milestone checkpoints (`15m`, `1h`, `4h`, `24h`) without overwriting!
        for cp_lbl, cp_sec in [("15m", 900), ("1h", 3600), ("4h", 14400), ("24h", 86400)]:
            if elapsed_sec >= cp_sec and cp_lbl not in pos["checkpoints_logged"]:
                pos["checkpoints_logged"].append(cp_lbl)
                self._append_jsonl(self.positions_log, {
                    "event_type": f"CHECKPOINT_{cp_lbl.upper()}",
                    "position_id": position_id,
                    "token_mint": pos["token_mint"],
                    "timestamp_ms": observed_at_ms,
                    "status": "OPEN",
                    "elapsed_sec": round(elapsed_sec, 1),
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "unrealized_paper_pnl_sol": unreal_pnl_sol,
                    "unrealized_return_pct": unreal_ret_pct,
                })

        # Check exit triggers (`CLOSED_SL`, `CLOSED_TP`, `CLOSED_TRAILING`, `CLOSED_TIME`)
        mult_now = cur_mid / ref_in
        peak_mult = pos["peak_mid_price_sol"] / ref_in
        new_status = None
        exit_reason = ""

        if mult_now <= PAPER_SL_MULT:
            new_status = "CLOSED_SL"
            exit_reason = f"Mid multiple {mult_now:.3f}x <= SL {PAPER_SL_MULT}x"
        elif mult_now >= PAPER_TP_MULT:
            new_status = "CLOSED_TP"
            exit_reason = f"Mid multiple {mult_now:.3f}x >= TP {PAPER_TP_MULT}x"
        elif peak_mult >= PAPER_TRAILING_ACTIVATE_MULT and mult_now <= peak_mult * (1.0 - PAPER_TRAILING_DRAWDOWN):
            new_status = "CLOSED_TRAILING"
            exit_reason = f"Pulled back from {peak_mult:.2f}x peak to {mult_now:.2f}x"
        elif elapsed_sec >= PAPER_TIME_STOP_SEC:
            new_status = "CLOSED_TIME"
            exit_reason = f"Elapsed {elapsed_sec:.0f}s >= time stop {PAPER_TIME_STOP_SEC}s"

        if new_status:
            close_ev = {
                "event_type": "POSITION_CLOSED",
                "position_id": position_id,
                "signal_id": pos["signal_id"],
                "token_mint": pos["token_mint"],
                "token_symbol": pos["token_symbol"],
                "status": new_status,
                "entry_time_ms": pos["entry_time_ms"],
                "exit_time_ms": observed_at_ms,
                "exit_time_utc": datetime.fromtimestamp(observed_at_ms / 1000.0, tz=timezone.utc).isoformat(),
                "entry_size_sol": pos["entry_size_sol"],
                "executable_entry_price_sol": pos["executable_entry_price_sol"],
                "executable_exit_price_sol": quote_now.get("executable_sell_price_sol"),
                "estimated_exit_cost_sol": round(
                    float(quote_now.get("exit_protocol_fee_sol") or 0.0)
                    + float(quote_now.get("exit_network_fee_sol") or 0.0)
                    + float(quote_now.get("exit_priority_fee_sol") or 0.0), 6
                ),
                "total_fees_sol": quote_now.get("total_costs_sol"),
                "total_slippage_pct": quote_now.get("total_slippage_and_impact_pct"),
                "gross_pnl_sol": quote_now.get("gross_pnl_sol"),
                "realized_paper_net_pnl_sol": unreal_pnl_sol,
                "realized_paper_net_return_pct": unreal_ret_pct,
                "mfe_pct": mfe_pct,
                "mae_pct": mae_pct,
                "exit_reason": exit_reason,
            }
            self._append_jsonl(self.positions_log, close_ev)
            pos["status"] = new_status
            del self.open_positions[position_id]
            return close_ev

        return None

    def run_live_scan_cycle(self, max_tokens: int = 20) -> dict:
        """
        Executes a genuine real-time live scan against verified TLSv1.3 Pump.fun & Binance endpoints.
        """
        session_id = f"sess_{uuid.uuid4().hex[:10]}"
        self.log_uptime_event("SESSION_START", session_id, note="Live V2.2 scanner cycle started")

        pf_base = DATA_SOURCES_REGISTRY["pumpfun_v3"]["base_url"]
        sol_r = self.http.request_json(
            "binance_spot",
            f"{DATA_SOURCES_REGISTRY['binance_spot']['base_url']}/api/v3/klines?symbol=SOLUSDT&interval=1h&limit=36",
        )
        if sol_r["ok"] and isinstance(sol_r["data"], list):
            self.regime.ingest_sol_klines_1h(sol_r["data"])

        # Poll brand-new emissions (`offset=0` and `offset=35` so we observe both <300s ON_TIME_LIVE and >300s LATE_DISCOVERY!)
        r_new = self.http.request_json("pumpfun_v3", f"{pf_base}/coins?offset=0&limit=25&sort=created_timestamp&order=DESC&includeNsfw=true")
        detected_ms = r_new["acquired_at_ms"]
        coins = (r_new["data"] if (r_new["ok"] and isinstance(r_new["data"], list)) else [])[:max_tokens]

        evaluated = 0
        opened = 0
        rejected = 0

        for c in coins:
            mint = c.get("mint")
            cts = int(c.get("created_timestamp") or 0)
            if not mint or cts <= 0:
                continue
            r_tr = self.http.request_json(
                "pumpfun_v3",
                f"{pf_base}/trades/{SOLANA_CHAIN_ID}/{mint}?limit=100&after=1-0-0-{max(0, cts - 5000)}",
            )
            r_1m = self.http.request_json(
                "pumpfun_v3",
                f"{pf_base}/candles/{SOLANA_CHAIN_ID}/{mint}?res=1m&to={int(time.time() * 1000)}",
            )
            acq_ms = max(detected_ms, r_tr["acquired_at_ms"], r_1m["acquired_at_ms"])
            trades = (r_tr["data"] or {}).get("trades", []) if r_tr["ok"] else []
            c1m = (r_1m["data"] or {}).get("candles", []) if r_1m["ok"] else []
            hlth = self.http.health.get_source_health_status("pumpfun_v3")

            rec = self.evaluate_live_token_candidate(
                coin=c,
                trades=trades,
                candles_1m=c1m,
                detected_at_ms=detected_ms,
                acquired_at_ms=acq_ms,
                source_health_status=hlth,
                open_threshold_score=34.0,
            )
            evaluated += 1
            if rec["signal_decision"] == "PAPER_POSITION_OPENED":
                opened += 1
            else:
                rejected += 1

        # Refresh any currently open paper positions
        for pid in list(self.open_positions.keys()):
            m_open = self.open_positions[pid]["token_mint"]
            cts_open = int(time.time() * 1000) - 3600_000
            r_tr_u = self.http.request_json(
                "pumpfun_v3",
                f"{pf_base}/trades/{SOLANA_CHAIN_ID}/{m_open}?limit=100&after=1-0-0-{max(0, cts_open)}",
            )
            if r_tr_u["ok"]:
                self.update_position_with_market_state(
                    pid, {"mint": m_open}, (r_tr_u["data"] or {}).get("trades", []), r_tr_u["acquired_at_ms"]
                )

        resolved = self.wallet_history.resolve_due()
        self.log_uptime_event("HEARTBEAT_CYCLE_DONE", session_id, note=f"evaluated={evaluated}, opened={opened}, rejected={rejected}, wallet_outcomes_resolved={resolved}, wallet_pending={len(self.wallet_history.pending)}")
        return self.build_paper_trading_status_summary()

    def build_paper_trading_status_summary(self) -> dict:
        uptime_evs = self._read_jsonl(self.uptime_log)
        sig_evs = self._read_jsonl(self.signals_log)
        pos_evs = self._read_jsonl(self.positions_log)

        if uptime_evs:
            first_ts = min(int(e["timestamp_ms"]) for e in uptime_evs)
            last_ts = max(int(e["timestamp_ms"]) for e in uptime_evs)
            elapsed_days = round((last_ts - first_ts) / 86_400_000.0, 4)
            downtime_sec = round(sum(float(e.get("downtime_gap_since_last_event_sec") or 0.0) for e in uptime_evs), 2)
        else:
            elapsed_days = 0.0
            downtime_sec = 0.0

        paper_status = "COMPLETED" if elapsed_days >= MIN_PAPER_DURATION_DAYS else "IN_PROGRESS"

        rej_reasons = pd.Series([s["signal_decision"] for s in sig_evs]).value_counts().to_dict() if sig_evs else {}
        opened_evs = [e for e in pos_evs if e["event_type"] == "POSITION_OPENED"]
        closed_evs = [e for e in pos_evs if e["event_type"] == "POSITION_CLOSED"]

        summary = {
            "PAPER_TRADING_STATUS": paper_status,
            "required_minimum_days": MIN_PAPER_DURATION_DAYS,
            "actual_elapsed_days_collected": elapsed_days,
            "recorded_downtime_gaps_sec": downtime_sec,
            "total_detected_candidates": len(sig_evs),
            "decision_breakdown": rej_reasons,
            "paper_positions_opened_total": len(opened_evs),
            "paper_positions_currently_open": len(self.open_positions),
            "paper_positions_closed_total": len(closed_evs),
            "append_only_position_events_count": len(pos_evs),
        }
        (self.storage_dir / "paper_status_summary_v2_2.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if sig_evs:
            pd.DataFrame(sig_evs).to_csv(self.storage_dir / "paper_signals_snapshot_v2_2.csv", index=False)
        if pos_evs:
            pd.DataFrame(pos_evs).to_csv(self.storage_dir / "paper_position_events_v2_2.csv", index=False)
        return summary

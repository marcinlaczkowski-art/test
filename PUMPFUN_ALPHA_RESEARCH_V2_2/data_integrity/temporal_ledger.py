"""
SECTION 3 (P0 — LIVE TIMING & 6-TIMESTAMP DATA INTEGRITY):
- Enforces separation of all 6 required timestamps:
    1. `event_ts_ms`
    2. `source_published_at_ms`
    3. `acquired_at_ms`
    4. `feature_computed_at_ms`
    5. `signal_generated_at_ms`
    6. `alert_emitted_at_ms`
  plus `signal_id`, `token_mint`, `source_id`, `data_version`, `feature_snapshot_id`.
- STRICT PROHIBITION ON TIME CLAMPING: Zero `min(acquired_at_ms, signal_ts_ms)` anywhere!
- Enforces `acquired_at_ms <= signal_generated_at_ms`. Violations are rejected with
  `INVALID_TEMPORAL_ORDER` and logged to `data/temporal_violations_log.jsonl`.
- Distinguishes real-time observed availability from `HISTORICAL_AVAILABILITY_UNKNOWN` in backtests.
- Flags tokens first discovered after `MAX_LIVE_DISCOVERY_AGE_SEC` as `LATE_DISCOVERY`.
"""
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings_v2_2 import DATA_DIR, DATA_VERSION, MAX_LIVE_DISCOVERY_AGE_SEC


class TemporalIntegrityViolation(RuntimeError):
    """Raised when an operation attempts to violate causal or live acquisition order."""
    def __init__(self, code: str, message: str, context: Optional[dict] = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.context = context or {}


@dataclass
class SixTimestampEnvelope:
    signal_id: str
    token_mint: str
    source_id: str
    data_version: str
    feature_snapshot_id: str
    event_ts_ms: int
    source_published_at_ms: Optional[int]  # None -> serialized as "UNKNOWN" if source omits publish ts
    acquired_at_ms: int
    feature_computed_at_ms: int
    signal_generated_at_ms: int
    alert_emitted_at_ms: Optional[int]
    mode: str                              # "live", "paper_trading", "oot", "validation", "training"
    availability_status: str               # "REALTIME_VERIFIED" or "HISTORICAL_AVAILABILITY_UNKNOWN"
    discovery_status: str                  # "ON_TIME_LIVE", "LATE_DISCOVERY", or "HISTORICAL_REPLAY"
    temporal_status: str                   # "VALID" or "INVALID_TEMPORAL_ORDER"
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["source_published_at_ms"] is None:
            d["source_published_at_ms"] = "UNKNOWN"
        if d["alert_emitted_at_ms"] is None:
            d["alert_emitted_at_ms"] = "NOT_EMITTED"
        return d


class TemporalIntegrityLedger:
    """
    Central temporal gatekeeper for both Live/Paper execution and Historical Backtest/OOT evaluation.
    Appends all rejected records to `temporal_violations_log.jsonl` (append-only, never overwritten).
    """
    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or (DATA_DIR / "temporal_violations_log.jsonl")
        self.first_seen_mint_ts: dict[str, int] = {}
        self.emitted_signal_keys: set[str] = set()

    def log_violation(self, record: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def register_token_first_sight(self, token_mint: str, created_ts_ms: int, observed_at_ms: int) -> str:
        """
        Records the exact wall-clock moment a token was first seen by the live scanner.
        Tokens already older than `MAX_LIVE_DISCOVERY_AGE_SEC` on first sight are marked `LATE_DISCOVERY`.
        """
        if token_mint not in self.first_seen_mint_ts:
            self.first_seen_mint_ts[token_mint] = int(observed_at_ms)
        first_obs = self.first_seen_mint_ts[token_mint]
        age_at_first_sight_sec = (first_obs - int(created_ts_ms)) / 1000.0
        if age_at_first_sight_sec < -5.0:
            return "INVALID_FUTURE_CREATION_TS"
        if age_at_first_sight_sec > MAX_LIVE_DISCOVERY_AGE_SEC:
            return "LATE_DISCOVERY"
        return "ON_TIME_LIVE"

    def validate_and_build_envelope(
        self,
        token_mint: str,
        created_ts_ms: int,
        event_ts_ms: int,
        source_id: str,
        acquired_at_ms: int,
        feature_computed_at_ms: int,
        signal_generated_at_ms: int,
        mode: str,
        decision_cutoff_ts_ms: Optional[int] = None,
        source_published_at_ms: Optional[int] = None,
        alert_emitted_at_ms: Optional[int] = None,
        has_historical_availability_proof: bool = False,
    ) -> SixTimestampEnvelope:
        """
        Validates temporal ordering WITHOUT ever clamping `acquired_at_ms` backwards!
        - In `live` / `paper_trading`:
          Requires `event_ts_ms <= acquired_at_ms <= feature_computed_at_ms <= signal_generated_at_ms`
          (and `signal_generated_at_ms > created_ts_ms`, never backdated to a historical `cts + 180s`!).
        - In `training` / `validation` / `oot`:
          Requires `event_ts_ms <= decision_cutoff_ts_ms`, AND requires `acquired_at_ms <= signal_generated_at_ms`.
          If data was fetched after `decision_cutoff_ts_ms` (archive harvest), marks
          `availability_status = "HISTORICAL_AVAILABILITY_UNKNOWN"` so it can NEVER masquerade as a real-time alert!
        """
        raw_hash = hashlib.sha256(
            f"{token_mint}:{mode}:{event_ts_ms}:{acquired_at_ms}:{signal_generated_at_ms}".encode("utf-8")
        ).hexdigest()[:16]
        sig_id = f"sig_{raw_hash}"
        snap_id = f"snap_{raw_hash}"

        reasons = []
        event_ts_ms = int(event_ts_ms)
        acquired_at_ms = int(acquired_at_ms)
        feature_computed_at_ms = int(feature_computed_at_ms)
        signal_generated_at_ms = int(signal_generated_at_ms)

        # Core Rule 3.2: NEVER clamp; strictly require `acquired_at_ms <= signal_generated_at_ms`!
        if acquired_at_ms > signal_generated_at_ms:
            reasons.append(f"acquired_at_ms({acquired_at_ms}) > signal_generated_at_ms({signal_generated_at_ms})")

        if feature_computed_at_ms < acquired_at_ms:
            reasons.append(f"feature_computed_at_ms({feature_computed_at_ms}) < acquired_at_ms({acquired_at_ms})")

        if signal_generated_at_ms < feature_computed_at_ms:
            reasons.append(f"signal_generated_at_ms({signal_generated_at_ms}) < feature_computed_at_ms({feature_computed_at_ms})")

        if event_ts_ms > acquired_at_ms:
            reasons.append(f"event_ts_ms({event_ts_ms}) > acquired_at_ms({acquired_at_ms}) [future blockchain event]")

        if source_published_at_ms is not None and int(source_published_at_ms) > acquired_at_ms:
            reasons.append(f"source_published_at_ms({source_published_at_ms}) > acquired_at_ms({acquired_at_ms})")

        if alert_emitted_at_ms is not None and int(alert_emitted_at_ms) < signal_generated_at_ms:
            reasons.append(f"alert_emitted_at_ms({alert_emitted_at_ms}) < signal_generated_at_ms({signal_generated_at_ms})")

        is_live_like = mode in ("live", "paper_trading")
        cutoff = int(decision_cutoff_ts_ms) if decision_cutoff_ts_ms is not None else signal_generated_at_ms

        if event_ts_ms > cutoff:
            reasons.append(f"event_ts_ms({event_ts_ms}) > decision_cutoff_ts_ms({cutoff}) [future event leak]")

        if is_live_like:
            # Prohibit backdating `signal_generated_at_ms` to historical `cts + 180s` when `acquired_at_ms` is later!
            if cutoff < acquired_at_ms:
                reasons.append(f"live decision_cutoff({cutoff}) < acquired_at_ms({acquired_at_ms}) [backdated live signal forbidden]")
            disc_status = self.register_token_first_sight(token_mint, created_ts_ms, acquired_at_ms)
            if disc_status == "INVALID_FUTURE_CREATION_TS":
                reasons.append(f"created_ts_ms({created_ts_ms}) is in the future vs acquired_at_ms({acquired_at_ms})")
            avail_status = "REALTIME_VERIFIED"
        else:
            disc_status = "HISTORICAL_REPLAY"
            if has_historical_availability_proof and acquired_at_ms <= cutoff:
                avail_status = "REALTIME_VERIFIED"
            else:
                avail_status = "HISTORICAL_AVAILABILITY_UNKNOWN"

        if reasons:
            rej = "; ".join(reasons)
            env = SixTimestampEnvelope(
                signal_id=sig_id,
                token_mint=token_mint,
                source_id=source_id,
                data_version=DATA_VERSION,
                feature_snapshot_id=snap_id,
                event_ts_ms=event_ts_ms,
                source_published_at_ms=source_published_at_ms,
                acquired_at_ms=acquired_at_ms,
                feature_computed_at_ms=feature_computed_at_ms,
                signal_generated_at_ms=signal_generated_at_ms,
                alert_emitted_at_ms=alert_emitted_at_ms,
                mode=mode,
                availability_status=avail_status,
                discovery_status=disc_status,
                temporal_status="INVALID_TEMPORAL_ORDER",
                rejection_reason=rej,
            )
            self.log_violation(env.to_dict())
            return env

        return SixTimestampEnvelope(
            signal_id=sig_id,
            token_mint=token_mint,
            source_id=source_id,
            data_version=DATA_VERSION,
            feature_snapshot_id=snap_id,
            event_ts_ms=event_ts_ms,
            source_published_at_ms=source_published_at_ms,
            acquired_at_ms=acquired_at_ms,
            feature_computed_at_ms=feature_computed_at_ms,
            signal_generated_at_ms=signal_generated_at_ms,
            alert_emitted_at_ms=alert_emitted_at_ms,
            mode=mode,
            availability_status=avail_status,
            discovery_status=disc_status,
            temporal_status="VALID",
            rejection_reason="",
        )

    def check_and_mark_dedup(self, token_mint: str, mode: str, bucket_key: str = "primary") -> bool:
        """
        Returns True if `(token_mint, mode, bucket_key)` has NOT been emitted yet; False if duplicate!
        Prevents duplicate alerts and prevents opening duplicate Paper Trading positions on the same token.
        """
        key = f"{mode}:{token_mint}:{bucket_key}"
        if key in self.emitted_signal_keys:
            self.log_violation({
                "temporal_status": "DUPLICATE_SIGNAL_REJECTED",
                "token_mint": token_mint,
                "mode": mode,
                "bucket_key": bucket_key,
                "logged_at_ms": int(time.time() * 1000),
            })
            return False
        self.emitted_signal_keys.add(key)
        return True

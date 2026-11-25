# V2_2_TEST_RESULTS — WYNIKI 28 TESTÓW AKCEPTACYJNYCH V2.2

## 1. Metodologia
Zestaw `tests/test_acceptance_v2_2.py` weryfikuje wszystkie 28 kryteriów akceptacyjnych z Sekcji 14 (15 testów P0, 7 testów Wallet Intelligence 2.0 oraz 6 testów Badawczych / OOT / Integralności SHA-256), łącząc analizę statyczną AST kodu źródłowego, wstrzykiwanie błędów sieciowych/TLS oraz asercje na wygenerowanych plikach CSV i JSONL.

## 2. Podsumowanie Wykonania (`data/acceptance_tests_v2_2.json`)
- Łączna liczba testów akceptacyjnych: **`28`**
- Zaliczone (`PASS`): **`28`**
- Niezaliczone (`FAIL`): **`0`**
- Czas wykonania: `4.08s`

## 3. Pełna tabela wyników (Test 01 – Test 28)
| Test ID | Wynik | Dowód / Szczegóły |
| --- | --- | --- |
| Test_01_zero_clamped_timestamps | PASS | Zero time-clamping patterns in V2.2 codebase; acquired_at_ms(9000) > signal_generated_at_ms(5000) rejected as INVALID_TEMPORAL_ORDER. |
| Test_02_zero_future_transactions_in_features | PASS | Future +1ms 500 SOL swap completely excluded from H1–H5 features and AMM state. |
| Test_03_zero_unclosed_candles | PASS | Unclosed 1h SOL candle [12:00..13:00) blocked at +1s/+15m/+30m/+59m59s; unlocked strictly at +3600s. |
| Test_04_zero_historical_alert_timestamps | PASS | Late token (900s) flagged LATE_DISCOVERY; all live signals satisfy acquired <= signal_generated <= alert_emitted. |
| Test_05_zero_paper_positions_with_zero_entry_price | PASS | Zero-price/incomplete entry blocked; 1 real opened paper positions all have entry_price > 0. |
| Test_06_zero_disabled_tls_validation | PASS | 0 TLS bypasses in V2.2 code; CERT_REQUIRED enforced; simulated SSLError aborted in 1 attempt and tripped UNAVAILABLE. |
| Test_07_http_429_5xx_timeout_json_circuit_breaker | PASS | Verified 429+503 backoff recovery, non-retry on 404, JSON_ERROR guard, and Circuit Breaker OPEN on timeouts. |
| Test_08_signal_deduplication | PASS | Duplicate signal key blocked on second submission. |
| Test_09_no_duplicate_open_positions | PASS | First valid live candidate opened 1 position; second attempt rejected as duplicate. |
| Test_10_full_position_audit_log | PASS | Full position audit trail verified: ['POSITION_OPENED', 'CHECKPOINT_15M', 'CHECKPOINT_1H', 'POSITION_CLOSED'] with fees, slippage, MFE/MAE. |
| Test_11_amm_exact_reconstruction | PASS | Monotonic impact/executable prices across 0.1–2.0 SOL and curve supply cap verified. |
| Test_12_separate_exact_from_estimated_amm | PASS | All 2540 rows in exact_amm_sizing_v2_2.csv have usable_in_exact_backtest=True (0 estimated rows mixed in). |
| Test_13_immutable_position_history_append_only | PASS | Append-only byte-prefix invariance proven across OPEN -> CHECKPOINT -> CLOSED. |
| Test_14_shared_features_parity_all_modes | PASS | 100% identical H1–H5, Narrative, and Market Regime outputs across all 5 modes. |
| Test_15_incomplete_data_protection | PASS | Incomplete/degraded snapshot assigned INSUFFICIENT_DATA (HIGH_CONFLUENCE blocked). |
| Test_16_wallet_pagination_and_completeness | PASS | Verified 660 wallet profiles with COMPLETE / PARTIAL_PAGINATED / INSUFFICIENT_HISTORY states. |
| Test_17_fifo_realized_unrealized_unknown | PASS | FIFO lot matching verified (W_A realized=1.99925 SOL; W_Unk flagged UNKNOWN_PNL). |
| Test_18_spl_transfer_not_treated_as_sale | PASS | SPL transfer W_A -> W_B carried 50-token cost basis lot with 0 false realized sale. |
| Test_19_exchanges_custody_excluded_from_insider | PASS | Binance hot-wallet funded wallets produced 0 SHARED_FUNDER / DIRECT_FUNDING insider edges. |
| Test_20_same_slot_buy_not_shared_control | PASS | SAME_SLOT_BUY classified strictly as WEAK confidence with 0 confirmed/probable cluster attribution. |
| Test_21_clusters_have_evidence_and_confidence | PASS | All 5875 wallet graph edges carry evidence_ids, timestamps, counts, and confidence tiers. |
| Test_22_cluster_track_record_causal_no_future | PASS | Cluster 4h win hidden at +10m and unlocked strictly after outcome_known_at_ms (+4h). |
| Test_23_h1_to_h5_separate_results | PASS | All 5 hypotheses H1–H5 and Combined Confluence evaluated separately (6 rows). |
| Test_24_baselines_same_tokens_and_horizons | PASS | All 5 OOT baselines evaluated on identical n=270 tokens and positives=5. |
| Test_25_oot_chronological_disjoint_and_frozen | PASS | OOT (270 tokens) is strictly chronologically after Backtest (650 tokens) with 0 mint overlap. |
| Test_26_all_metrics_have_explicit_denominators | PASS | Every reported rate/precision/recall/win-rate metric includes explicit 'k/N (pct%)' denominator. |
| Test_27_small_sample_marked_insufficient | PASS | OOT sample gate enforced: OOT_STATUS=INSUFFICIENT_SAMPLE (n=270/1000, pos=5/30). |
| Test_28_no_unproven_edge_and_v1_v2_v21_intact | PASS | Honest statuses enforced (EDGE_STATUS=NOT_ESTABLISHED, PAPER=IN_PROGRESS, STATUS_C=False); all 131 V1/V2/V2.1 SHA-256 hashes 100% intact. |

## 4. Ograniczenia i Status
Testy techniczne potwierdzają poprawność implementacji i higienę danych (`STATUS A = TRUE`, `STATUS B = TRUE`), lecz zgodnie z Sekcją 1.3 i 16 **nie stanowią dowodu przewagi inwestycyjnej** (`STATUS C = FALSE`).

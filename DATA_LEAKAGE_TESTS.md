# DATA LEAKAGE TESTS V2.1 — KONTROLA ZNACZNIKÓW CZASU I BRAKU PRZECIEKU PRZYSZŁOŚCI

## 1. Architektura kontroli na poziomie pojedynczej cechy
W wersji V2.1 wyeliminowano poleganie wyłącznie na jednym globalnym znaczniku `data_max_timestamp`. Każda z **24 cech wejściowych** w słowniku `snapshot["features"]` przechowuje pełną metrykę pochodzenia:
- `value` (surowa wartość lub jawny status `"unknown"` / `"insufficient_history"`),
- `model_num` (znormalizowana postać numeryczna z osobną flagą dostępności `*_known_flag`),
- `source` (źródło danych),
- `acquired_at_ms` (czas pozyskania obserwacji),
- `event_timestamp_ms` (czas zdarzenia źródłowego),
- `max_data_timestamp_ms` (maksymalny czas danych użytych do wyliczenia cechy),
- `feature_available_at_ms` (dokładny moment, od którego cecha i jej wynik były publicznie znane).

Funkcja `validate_snapshot_no_leakage(snapshot)` w `src/feature_engine.py` wymusza twardy warunek dla **każdej cechy z osobna**:
`feature_available_at_ms <= signal_timestamp_ms` oraz `max_data_timestamp_ms <= signal_timestamp_ms` oraz `event_timestamp_ms <= signal_timestamp_ms`.
Każde naruszenie natychmiast rzuca wyjątek `FeatureLeakageError` i **blokuje wygenerowanie sygnału**.

## 2. Naprawa danych SOL w środku godziny (`MarketContextTracker`)
- Świeca godzinowa Binance `SOLUSDT` otwierająca się o `open_time_ms` (np. `12:00:00.000`) zamyka się dopiero o `close_time_ms = open_time_ms + 3_600_000` (`13:00:00.000`).
- Dla sygnałów generowanych o `12:00:01`, `12:15:00`, `12:30:00` oraz `12:59:59` tracker widzi wyłącznie ostatnią **zamkniętą** świecę (`11:00–12:00`, `close_time_ms = 12:00:00`) oraz opcjonalny kurs spot `quotePriceUsd` z faktycznie wykonanej transakcji on-chain o `blockTimeMs <= signal_timestamp_ms`. Przyszłe `high`, `low` ani `close` niezamkniętej świecy nigdy nie są odczytywane.

## 3. Wyniki 12 obowiązkowych testów jednostkowych i integracyjnych (`tests/test_suite_v2_1.py`)
Wykonano `12` automatycznych testów: **`12 / 12 PASS`** (czas wykonania: `0.913s`).

| Test ID | Status | Szczegóły weryfikacji |
| --- | --- | --- |
| 01_no_unclosed_candles | PASS | Unclosed 1m candle [120s..180s) ignored at T=150s; FeatureLeakageError blocked +1ms violation. |
| 02_no_future_volume | PASS | Injected $500k trade at signal_ts+1ms completely ignored (buy_vol=210.0). |
| 03_no_future_sol_mid_hour | PASS | Verified 0% SOL kline close leak at +1s, +15m, +30m, +59m59s; bar unlocked strictly at +3600s. |
| 04_no_future_creator_outcomes | PASS | Creator launch at -20m showed win_rate='unknown' at T=+3m and unlocked only after +4h. |
| 05_no_future_wallet_history_and_social | PASS | Future wallet outcomes (+10s/+20s) excluded at signal_ts; future social event blocked. |
| 06_training_oot_paper_live_parity | PASS | 100.0% exact bit-for-bit parity (max_diff=0.0) across all 5 modes on 25 tokens; empty ticker history returns 'insufficient_history' (never forced to 1). |
| 07_no_double_counting_wallets_or_trades | PASS | 3x duplicated swap tape yielded identical buyer counts, volume, supply, and FIFO PnL. |
| 08_supply_concentration_validation | PASS | Synthetic 105.4% anomaly blocked as INVALID_SUPPLY_RECONSTRUCTION; all 649 valid cohort tokens <= 100% (max=99.80%, blocked=1). |
| 09_fifo_realized_pnl_validation | PASS | Exact 2-lot FIFO realized PnL (+4.999625 SOL) & remaining cost basis verified; unmatched sell flagged UNKNOWN_COST_BASIS. |
| 10_amm_fees_and_price_impact | PASS | Constant-product curve impact monotonic across [0.1, 0.25, 0.5, 1.0, 2.0] SOL; net < executable <= mid-price verified. |
| 11_zero_token_split_leakage | PASS | 0 overlapping mints across all 3 Walk-Forward folds (>=4h embargo), V2/V2.1 650-cohort, V1 deep cohort, and 190 unseen OOT tokens. |
| 12_censored_observations_handling | PASS | Unelapsed horizons strictly labeled 'censored' (never coerced to 0); verified on synthetic +90m cutoff and 190 OOT 24h rows. |

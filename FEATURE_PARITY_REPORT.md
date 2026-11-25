# FEATURE PARITY REPORT V2.1 — ZGODNOŚĆ TRENING / WALIDACJA / OOT / PAPER / LIVE

## 1. Zidentyfikowane źródła rozjazdu w V2
1. W skryptach OOT i Paper Trading w V2 inicjalizowano pusty obiekt `CausalHistoryTracker()`, przez co cechy portfeli i twórców miały w testach OOT sztuczne zera zamiast rzeczywistego stanu historycznego.
2. Przy braku wcześniejszych obserwacji tickera wymuszano `is_ticker_first_mover = 1`, zniekształcając predykcje w trybie LIVE.
3. Osobne funkcje ekstrakcji cech w treningu i skanerze paper tradingu stwarzały ryzyko dryfu implementacyjnego.

## 2. Rozwiązanie architektoniczne w V2.1
- Utworzono **jeden wspólny moduł** `src/feature_engine.py` (`UnifiedFeatureEngine.compute_snapshot`), który obsługuje wszystkie 5 trybów: `training`, `validation`, `oot`, `paper_trading` oraz `live`.
- Stan historyczny (`MarketContextTracker`, `CreatorHistoryTracker`, `WalletHistoryTracker`, `TickerNarrativeHistoryTracker`) został zgrupowany w klasie `UnifiedStateBundle` (`src/state_trackers_v2_1.py`) z atomowym zapisem i odczytem checkpointów (`state_post_wf_v2_1.json`) oraz filtrem `as_of_ts_ms <= signal_timestamp_ms`.
- Gdy historia portfela, twórcy lub tickera nie posiada wystarczającego pokrycia (`< 25` wcześniejszych emisji dla tickera lub `0` zakończonych horyzontów `4h` dla twórcy), silnik zwraca jawny status `"unknown"` lub `"insufficient_history"` i ustawia dedykowaną flagę `*_history_known_flag = 0` — **nigdy nie wymusza `is_ticker_first_mover = 1`**.

## 3. Wynik testu parzystości cech (`test_06_training_oot_paper_live_parity`)
- Przetestowano `25` tokenów z załadowanym checkpointem `state_post_wf_v2_1.json` we wszystkich 5 trybach (`training`, `validation`, `oot`, `paper_trading`, `live`).
- Maksymalna bezwzględna różnica na wszystkich 24 cechach wektora modelowego oraz cenie wejścia: **`0.000000` (100.0% identyczności bit-po-bicie)**.
- Zapisano `67` pełnych plików audytowych `cache/snapshots/*_feature_snapshot.json`.

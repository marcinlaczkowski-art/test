# PUMPFUN ALPHA RESEARCH V2.1 — Causal Verification, Execution & Out-of-Time Engine

Repozytorium zawiera wersję **V2.1** projektu badawczego rynku **pump.fun (Solana)** po ukierunkowanej naprawie metodologicznej (`PUMPFUN_ALPHA_V2_SECOND_AUDIT`): eliminacji przecieku danych (`data leakage`), ujednoliceniu silnika cech (`TRENING == WALIDACJA == OOT == PAPER == LIVE`), głębokiej rekonstrukcji portfeli RPC, walidacji podaży (`<= 100%`), ścisłej księgowości `FIFO` oraz symulacji płynności `AMM / bonding curve` dla pozycji `0.1–2.0 SOL`.

## Główne raporty
- [`FINAL_REPORT_V2_1.md`](./FINAL_REPORT_V2_1.md) — Raport końcowy V2.1 i wnioski badawcze
- [`AUDIT_FIXES.md`](./AUDIT_FIXES.md) — Zestawienie napraw po drugim audycie oraz ograniczeń strukturalnych
- [`BACKTEST_V2_1.md`](./BACKTEST_V2_1.md) — Symulator płynności `0.1–2.0 SOL`, Walk-Forward (`4h` embargo) oraz 8 testów ablacji
- [`DATA_LEAKAGE_TESTS.md`](./DATA_LEAKAGE_TESTS.md) — Kontrola znaczników czasu na poziomie pojedynczej cechy i wyniki 12 testów
- [`FEATURE_PARITY_REPORT.md`](./FEATURE_PARITY_REPORT.md) — Dowód 100% zgodności cech pomiędzy treningiem, OOT, Paper Tradingiem i trybem Live
- [`DATA_QUALITY_REPORT.md`](./DATA_QUALITY_REPORT.md) — Jakość danych, cenzurowanie horyzontów i kompletność OOT (`190/190` dla `1h` i `4h`)
- [`WALLET_RECONSTRUCTION_REPORT.md`](./WALLET_RECONSTRUCTION_REPORT.md) — Wielostronicowa rekonstrukcja RPC portfeli i klasyfikacja relacji
- [`SUPPLY_VALIDATION.md`](./SUPPLY_VALIDATION.md) — Walidacja koncentracji podaży i blokada `INVALID_SUPPLY_RECONSTRUCTION`
- [`REALIZED_PNL_VALIDATION.md`](./REALIZED_PNL_VALIDATION.md) — Kolejka lotów `FIFO` i blokada `UNKNOWN_COST_BASIS`
- [`PAPER_TRADING_V2_1.md`](./PAPER_TRADING_V2_1.md) — Dokumentacja skanera Paper Trading V2.1 (tryb read-only)

## Dane, skoroszyt i dashboard
- [`PUMPFUN_ALPHA_RESEARCH_V2_1.xlsx`](./PUMPFUN_ALPHA_RESEARCH_V2_1.xlsx) — 11-arkuszowy skoroszyt analityczny Excel
- [`MODEL_COMPARISON_V2_1.csv`](./MODEL_COMPARISON_V2_1.csv) & [`WALK_FORWARD_V2_1.csv`](./WALK_FORWARD_V2_1.csv)
- [`OUT_OF_TIME_V2_1.csv`](./OUT_OF_TIME_V2_1.csv) & [`POSITION_SIZING_EXECUTION_V2_1.csv`](./POSITION_SIZING_EXECUTION_V2_1.csv)
- [`dashboard/index.html`](./dashboard/index.html) — Interaktywny lokalny dashboard (uruchomienie: `python serve_dashboard_v2_1.py`)

## Kod źródłowy i testy (`12/12 PASS`)
- [`src/feature_engine.py`](./src/feature_engine.py) — Wspólny przyczynowy silnik cech (`UnifiedFeatureEngine`)
- [`src/state_trackers_v2_1.py`](./src/state_trackers_v2_1.py) — Trackery stanu (`SOL`, twórcy, portfele, tickery) z obsługą checkpointów
- [`src/wallet_supply_fifo_v2_1.py`](./src/wallet_supply_fifo_v2_1.py) — Walidacja podaży, relacje portfeli i kolejka `FIFO`
- [`src/execution_and_backtest_v2_1.py`](./src/execution_and_backtest_v2_1.py) — Symulator `x * y = k`, Walk-Forward i ablacja
- [`src/paper_trader_v2_1.py`](./src/paper_trader_v2_1.py) — Read-only Paper Trading V2.1
- [`tests/test_suite_v2_1.py`](./tests/test_suite_v2_1.py) — Zestaw 12 automatycznych testów weryfikacyjnych (`python tests/test_suite_v2_1.py`)

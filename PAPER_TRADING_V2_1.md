# PAPER TRADING V2.1 — SYMULACJA LIVE BEZ TRANSAKCJI ON-CHAIN

## 1. Zgodność architektoniczna z treningiem i OOT
Skrypt `src/paper_trader_v2_1.py` ładuje zapisany checkpoint stanu `state_post_wf_v2_1.json` i wywołuje **dokładnie tę samą metodę** `UnifiedFeatureEngine.compute_snapshot(..., mode="paper_trading")`, z której korzysta trening, walidacja i OOT (`0.000000` różnicy cech potwierdzone w `FEATURE_PARITY_REPORT.md`).
- **Bezpieczeństwo:** Skrypt działa wyłącznie w trybie odczytu publicznych endpointów API — **nie wysyła żadnych transakcji, nie łączy portfela i nie podpisuje operacji**.

## 2. Zarejestrowane obserwacje i alerty (`paper_trading/paper_alerts_v2_1.csv`)
- Przeskanowano na żywo `25` świeżych emisji (`60s–900s` od utworzenia), zapisując dla każdej pełny, niezmienny plik `cache/snapshots/<mint>_<signal_ts>_feature_snapshot.json`.
- Wyzwolono `12` alertów spełniających progi (`pump_potential_v2_1_pruned_score >= 52.0`, `manipulation_risk_score < 65.0`, `supply_status == "ok"`).
- Wszystkie niezakończone okna przyszłości (`return_15m_pct`, `return_1h_pct`, `return_4h_pct`, `return_24h_pct`) mają jawny status `"censored_pending"` do czasu rzeczywistego upłynięcia horyzontu.

| alert_timestamp_utc | symbol | alert_triggered | entry_price_usd | pump_potential_v2_1_pruned_score | manipulation_risk_score | insider_risk_score | confidence | data_completeness | return_15m_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-25T08:42:49+00:00 | WinterArc | 1 | 0.0000 | 71.57 | 0.0000 | 25.00 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:42:50+00:00 | kittylick | 0 | 0.0000 | 50.14 | 25.00 | 25.37 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:42:54+00:00 | COWW | 1 | 0.0000 | 76.13 | 0.0000 | 25.00 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:42:54+00:00 | Offchain | 0 | 0.0000 | 51.54 | 0.0000 | 25.79 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:42:59+00:00 | PUMP | 0 | 0.0000 | 34.83 | 25.00 | 28.77 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:07+00:00 | HI | 1 | 0.0000 | 73.77 | 0.0000 | 25.00 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:07+00:00 | PUMP | 0 | 0.0000 | 49.19 | 25.00 | 27.38 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:12+00:00 | FERGUS | 1 | 0.0000 | 53.54 | 12.00 | 35.00 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:12+00:00 | HERMES | 1 | 0.0000 | 65.38 | 30.00 | 60.00 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:13+00:00 | JUMP | 1 | 0.0000 | 52.83 | 40.00 | 27.88 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:14+00:00 | dogbaton | 0 | 0.0000 | 46.81 | 40.00 | 27.78 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:14+00:00 | PUMP | 0 | 0.0000 | 47.72 | 25.00 | 28.36 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:19+00:00 | SUNDOG | 1 | 0.0000 | 66.45 | 38.00 | 40.00 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:24+00:00 | SXSN | 0 | 0.0000 | 33.89 | 25.00 | 36.55 | medium_confidence | 0.9000 | censored_pending |
| 2026-11-25T08:43:26+00:00 | MGOAT | 1 | 0.0000 | 80.42 | 40.00 | 60.00 | medium_confidence | 0.9000 | censored_pending |

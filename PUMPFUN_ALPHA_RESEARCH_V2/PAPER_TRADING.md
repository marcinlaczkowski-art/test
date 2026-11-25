# PAPER TRADING & OUT-OF-TIME LIVE VALIDATION (BEZ PRAWDZIWYCH ZAKUPÓW)

## 1. Wyniki Testu na Nowych Nieznanych Danych Po Zamrożeniu V2 (Sekcja 13)
Najpierw zamrożono parametry modelu V2 (`sha256 = 97a9684e2028732126c0528a2b0a7f8b31a19b5350d47a39564e69849910b932`), a następnie pobrano świeży, nieznany wcześniej strumień emisji z poranka **`2026-11-25`** (`OUT_OF_TIME_UNSEEN_TEST.csv`):
- **Liczba obserwowanych nowych tokenów:** `100`
- **Kompletne (uncensored) obserwacje `1h`:** `21` | **Censored `1h`:** `0`
- **Censored `4h`:** `0` | **Censored `24h`:** `21` *(żadnemu niepełnemu horyzontowi nie przypisano przedwcześnie porażki!)*
- **Rzeczywisty obserwowany Base Rate `hit_2x_1h`:** `0.0476` (`hit_3x_1h`: `0.0`)

### Wyniki zamrożonego V2 vs benchmarki na nieznanych danych `hit_2x_1h`:
| strategy | target | n_obs | positives | base_rate | precision_at_5 | precision_at_10 | precision_at_20 | lift_at_10 | lift_at_20 | recall_at_top20pct | roc_auc | pr_auc | top10_mean_event_net_ret_pct | top10_median_event_net_ret_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pump_Potential_V2_Frozen | hit_2x_1h_unseen_holdout | 21 | 1 | 0.0476 | 0 | 0.1 | 0.05 | 2.1 | 1.05 | 0 | 0.6 | 0.1111 | -21.66 | -18.22 |
| Pump_Potential_V1_Frozen | hit_2x_1h_unseen_holdout | 21 | 1 | 0.0476 | 0.2 | 0.1 | 0.05 | 2.1 | 1.05 | 1 | 1 | 1 | -22.52 | -18.22 |
| Buyer_Count_Velocity_Only | hit_2x_1h_unseen_holdout | 21 | 1 | 0.0476 | 0.2 | 0.1 | 0.05 | 2.1 | 1.05 | 1 | 0.95 | 0.5 | -22.51 | -18.22 |
| Volume_Only | hit_2x_1h_unseen_holdout | 21 | 1 | 0.0476 | 0.2 | 0.1 | 0.05 | 2.1 | 1.05 | 1 | 0.9 | 0.3333 | -22.49 | -18.22 |
| Price_Gain_Only | hit_2x_1h_unseen_holdout | 21 | 1 | 0.0476 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0476 | -18.33 | -18.22 |
| Random_Selection | hit_2x_1h_unseen_holdout | 21 | 1 | 0.0476 | 0 | 0.1 | 0.05 | 2.1 | 1.05 | 0 | 0.65 | 0.125 | -21.39 | -18.22 |
| Pump_Potential_V2_Frozen | hit_2x_4h_unseen_holdout | 21 | 1 | 0.0476 | 0 | 0.1 | 0.05 | 2.1 | 1.05 | 0 | 0.6 | 0.1111 | -21.66 | -18.22 |
| Pump_Potential_V1_Frozen | hit_2x_4h_unseen_holdout | 21 | 1 | 0.0476 | 0.2 | 0.1 | 0.05 | 2.1 | 1.05 | 1 | 1 | 1 | -22.52 | -18.22 |
| Buyer_Count_Velocity_Only | hit_2x_4h_unseen_holdout | 21 | 1 | 0.0476 | 0.2 | 0.1 | 0.05 | 2.1 | 1.05 | 1 | 0.95 | 0.5 | -22.51 | -18.22 |
| Volume_Only | hit_2x_4h_unseen_holdout | 21 | 1 | 0.0476 | 0.2 | 0.1 | 0.05 | 2.1 | 1.05 | 1 | 0.9 | 0.3333 | -22.49 | -18.22 |


---

## 2. Moduł Operacyjny Paper Trading (`src/paper_trader_v2.py` — Sekcja 14)
Moduł działa **w 100% bez portfela, bez kluczy prywatnych i bez wykonywania jakichkolwiek transakcji blockchainowych**.

### Zasada działania i komendy uruchomieniowe:
1. **Skanowanie nowych tokenów i zapis niemodyfikowalnych snapshotów:**
   ```powershell
   python src/paper_trader_v2.py --mode scan --max-tokens 35
   ```
   Rejestruje w `paper_trading/paper_alerts_ledger.jsonl` oraz `paper_trading/paper_alerts.csv` dokładny snapshot z chwili alertu (`signal_timestamp_ms`, `data_max_timestamp_ms`, `Pump Potential V2`, `Manipulation Risk V2`, `Insider Risk V2`, cenę, płynność, liczbę kupujących, tempo napływu niezależnych kupujących, bundlery oraz uzasadnienie punktacji).
2. **Późniejsza ewaluacja horyzontów `15m`, `1h`, `4h` i `24h`:**
   ```powershell
   python src/paper_trader_v2.py --mode evaluate
   ```
   Aktualizuje wyłącznie te horyzonty, które faktycznie upłynęły (`now_ms >= signal_timestamp_ms + horizon_ms`), pozostawiając pozostałe jako `PENDING_CENSORED`.

### Przykładowe zarejestrowane alerty z inicjalnego uruchomienia (`N = 50`):
| symbol | alert_tier | pump_potential_v2 | manipulation_risk_v2 | insider_supply_risk_v2 | entry_price_usd | implied_liquidity_usd | unique_buyers | eval_15m_status | score_reasons |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CHARITY | MONITOR_BASELINE | 0.46 | 0 | 25 | 0.00000192 | 4,091.43 | 7 | PENDING_CENSORED | -Creator sold early |
| GrenCAT | MONITOR_BASELINE | 2.69 | 40 | 8.68 | 0.00000036 | 2,036.10 | 6 | PENDING_CENSORED | !Mayhem AI bot mode |
| DOOB | MONITOR_BASELINE | 0.15 | 40 | 25.34 | 0.00000028 | 2,036.10 | 4 | PENDING_CENSORED | -Creator sold early; !Mayhem AI bot mode |
| DUCK | MONITOR_BASELINE | 0.55 | 40 | 26.19 | 0.00000025 | 2,036.10 | 6 | PENDING_CENSORED | -Creator sold early; !Mayhem AI bot mode |
| ANSEM | WATCHLIST_HIGH_POTENTIAL | 78.26 | 30 | 60 | 0.00000192 | 4,094.56 | 56 | PENDING_CENSORED | +High indep. buyer flow (3.2/m); +Net buy USD dominance; !Elevated bundle/supply risk |
| GrenCAT | MONITOR_BASELINE | 1.23 | 40 | 41.93 | 0.00000001 | 2,036.10 | 13 | PENDING_CENSORED | -Creator sold early; !Mayhem AI bot mode |
| fg | MONITOR_BASELINE | 4.58 | 40 | 20.31 | 0.00000005 | 2,036.10 | 8 | PENDING_CENSORED | !Mayhem AI bot mode |
| CATONBULL | MONITOR_BASELINE | 1.08 | 0 | 25.15 | 0.00000192 | 4,091.02 | 1 | PENDING_CENSORED | -Low/zero early buyers; -Creator sold early |
| PUMP | MONITOR_BASELINE | 0.15 | 40 | 31.53 | 0.00000012 | 2,036.10 | 6 | PENDING_CENSORED | -Creator sold early; !Mayhem AI bot mode |
| 捂福富 | MONITOR_BASELINE | 3.18 | 40 | 9.57 | 0.00000006 | 2,036.10 | 9 | PENDING_CENSORED | !Mayhem AI bot mode |
| BRAINROT | MONITOR_BASELINE | 0.17 | 40 | 25 | 0.00000031 | 2,036.10 | 5 | PENDING_CENSORED | -Creator sold early; !Mayhem AI bot mode |
| LaMisery | MONITOR_BASELINE | 0.45 | 40 | 27.74 | 0.00000088 | 2,766.83 | 4 | PENDING_CENSORED | -Creator sold early; !Mayhem AI bot mode |
| LPPROBE | MONITOR_BASELINE | 8 | 0 | 0.13 | 0.00000191 | 4,082.04 | 19 | PENDING_CENSORED | +Net buy USD dominance |
| VENOM | MONITOR_BASELINE | 0.2 | 40 | 25.12 | 0.00000004 | 2,036.10 | 9 | PENDING_CENSORED | -Creator sold early; !Mayhem AI bot mode |
| SLITHEEN | MONITOR_BASELINE | 0.99 | 18 | 40 | 0.00000191 | 4,090.09 | 6 | PENDING_CENSORED | -Creator sold early |

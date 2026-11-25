# BACKTEST V2 — SYMULACJA ZDARZENIOWA I WALIDACJA KROCZĄCA Z EMBARGO

## 1. Architektura Zdarzeniowego Symulatora Egzekucji (Sekcja 6)
Backtest V2 całkowicie odrzuca wyliczanie zysków z historycznego *lifetime ATH*. Każda pozycja (`$200` kapitału wejściowego) symulowana jest krok po kroku po dacie sygnału (`signal_timestamp_ms`):
1. **Latencja wykonania (`+2 000 ms`):** Wejście następuje dopiero po wygenerowaniu sygnału, po cenie uwzględniającej uderzenie popytu w głębokość jednostronną puli AMM ($0.5 \cdot L_{\text{USD}}$), opłatę protokołu/DEX (`1.0%`) oraz priorytet sieci Solana (`$0.35`).
2. **Odrzucenie braku płynności (`< $1,200`):** Sygnały na niepłynnych tokenach otrzymują status `NO_FILL_INSUFFICIENT_LIQUIDITY` zamiast fikcyjnej transakcji po cenie wykresowej.
3. **Konserwatywna kolejność wewnątrz świecy:** W każdej kolejnej świecy `1m` / `15m` najpierw sprawdzany jest warunek krachu płynności (`< $600` głębokości puli — pełny poślizg wyjścia) oraz **Stop-Loss (`-38%` na cenie `Low`)**, a dopiero potem częściowa realizacja zysku (`50%` pozycji przy `2.2x` na `High`, wymagająca obrotu świecy $\ge \$20$). Eliminuje to optymistyczny błąd wewnątrzświecowy.
4. **Wyjście czasowe (`Time-Stop 4h`):** Pozostała część pozycji zamykana jest po cenie zamknięcia 4-godzinnego okna pomniejszonej o poślizg wyjścia AMM i opłaty.

### Rozkład powodów wyjścia w symulacji zdarzeniowej (`t = 5m -> 4h`):
| Powód zamknięcia / status egzekucji pozycji (horyzont 4h) | Liczba obserwacji |
| --- | --- |
| TIME_STOP_ZERO_POST_TRADES | 331 |
| TIME_STOP_HORIZON_END | 148 |
| STOP_LOSS | 19 |
| LIQUIDITY_COLLAPSE_OR_RUG | 13 |
| PARTIAL_TP1_PLUS_TIME_STOP | 8 |
| TRAILING_STOP_AFTER_TP1 | 7 |


---

## 2. Wyniki Walk-Forward Osobno Dla Każdego Okresu Testowego (`WALK_FORWARD_RESULTS.csv`)
Zastosowano pełną rozłączność tokenów pomiędzy treningiem, walidacją i testem oraz kontrolę embargo czasowego (`4h` tam, gdzie odstęp między warstwami na to pozwala, z jawnym raportowaniem odstępu w gęstym strumieniu minutowym):

| fold | test_period_start_utc | test_period_end_utc | embargo_status | embargo_minutes | target | strategy | n_obs | positives | base_rate | precision_at_5 | precision_at_10 | precision_at_20 | lift_at_10 | lift_at_20 | recall_at_top20pct | roc_auc | pr_auc | top10_mean_event_net_ret_pct | top10_median_event_net_ret_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-11-24 04:06 | 2026-11-24 21:58 | FULL_EMBARGO_292.36m | 292.36 | hit_2x_4h | Pump_Potential_V2 | 84 | 2 | 0.0238 | 0.2 | 0.2 | 0.1 | 8.4 | 4.2 | 1 | 0.9451 | 0.2778 | 56.03 | -17.76 |
| 1 | 2026-11-24 04:06 | 2026-11-24 21:58 | FULL_EMBARGO_292.36m | 292.36 | hit_2x_4h | Pump_Potential_V1_Frozen | 84 | 2 | 0.0238 | 0.4 | 0.2 | 0.1 | 8.4 | 4.2 | 1 | 0.9817 | 0.7 | 45.59 | -26.49 |
| 1 | 2026-11-24 04:06 | 2026-11-24 21:58 | FULL_EMBARGO_292.36m | 292.36 | hit_2x_4h | Buyer_Count_Velocity_Only | 84 | 2 | 0.0238 | 0.4 | 0.2 | 0.1 | 8.4 | 4.2 | 1 | 0.9634 | 0.325 | 46.9 | -22.02 |
| 1 | 2026-11-24 04:06 | 2026-11-24 21:58 | FULL_EMBARGO_292.36m | 292.36 | hit_2x_4h | Volume_Only | 84 | 2 | 0.0238 | 0.2 | 0.1 | 0.1 | 4.2 | 4.2 | 1 | 0.9146 | 0.2381 | -13.09 | -24.52 |
| 1 | 2026-11-24 04:06 | 2026-11-24 21:58 | FULL_EMBARGO_292.36m | 292.36 | hit_2x_4h | Price_Gain_Only | 84 | 2 | 0.0238 | 0 | 0.1 | 0.05 | 4.2 | 2.1 | 0.5 | 0.4695 | 0.0747 | -3 | -12.53 |
| 2 | 2026-11-24 21:58 | 2026-11-24 22:00 | FULL_EMBARGO_251.97m | 251.97 | hit_2x_4h | Pump_Potential_V2 | 84 | 1 | 0.0119 | 0 | 0.1 | 0.05 | 8.4 | 4.2 | 1 | 0.9398 | 0.1667 | -27.74 | -22.25 |
| 2 | 2026-11-24 21:58 | 2026-11-24 22:00 | FULL_EMBARGO_251.97m | 251.97 | hit_2x_4h | Pump_Potential_V1_Frozen | 84 | 1 | 0.0119 | 0 | 0.1 | 0.05 | 8.4 | 4.2 | 1 | 0.9277 | 0.1429 | -30.36 | -28.42 |
| 2 | 2026-11-24 21:58 | 2026-11-24 22:00 | FULL_EMBARGO_251.97m | 251.97 | hit_2x_4h | Buyer_Count_Velocity_Only | 84 | 1 | 0.0119 | 0 | 0 | 0.05 | 0 | 4.2 | 1 | 0.8795 | 0.0909 | -23.16 | -18.73 |
| 2 | 2026-11-24 21:58 | 2026-11-24 22:00 | FULL_EMBARGO_251.97m | 251.97 | hit_2x_4h | Volume_Only | 84 | 1 | 0.0119 | 0 | 0.1 | 0.05 | 8.4 | 4.2 | 1 | 0.8916 | 0.1 | -26.73 | -18.73 |
| 2 | 2026-11-24 21:58 | 2026-11-24 22:00 | FULL_EMBARGO_251.97m | 251.97 | hit_2x_4h | Price_Gain_Only | 84 | 1 | 0.0119 | 0.2 | 0.1 | 0.05 | 8.4 | 4.2 | 1 | 0.9759 | 0.3333 | -22.28 | -15.15 |
| 3 | 2026-11-24 22:00 | 2026-11-24 22:04 | FULL_EMBARGO_254.68m | 254.68 | hit_2x_4h | Pump_Potential_V2 | 84 | 11 | 0.131 | 0.2 | 0.2 | 0.3 | 1.527 | 2.291 | 0.3636 | 0.7522 | 0.2651 | -31.68 | -26.29 |
| 3 | 2026-11-24 22:00 | 2026-11-24 22:04 | FULL_EMBARGO_254.68m | 254.68 | hit_2x_4h | Pump_Potential_V1_Frozen | 84 | 11 | 0.131 | 0 | 0 | 0 | 0 | 0 | 0 | 0.1961 | 0.0866 | -34.41 | -29.1 |
| 3 | 2026-11-24 22:00 | 2026-11-24 22:04 | FULL_EMBARGO_254.68m | 254.68 | hit_2x_4h | Buyer_Count_Velocity_Only | 84 | 11 | 0.131 | 0 | 0 | 0 | 0 | 0 | 0 | 0.2565 | 0.0924 | -35.36 | -29.1 |
| 3 | 2026-11-24 22:00 | 2026-11-24 22:04 | FULL_EMBARGO_254.68m | 254.68 | hit_2x_4h | Volume_Only | 84 | 11 | 0.131 | 0 | 0 | 0.05 | 0 | 0.382 | 0.0909 | 0.325 | 0.1042 | -30.99 | -28.01 |
| 3 | 2026-11-24 22:00 | 2026-11-24 22:04 | FULL_EMBARGO_254.68m | 254.68 | hit_2x_4h | Price_Gain_Only | 84 | 11 | 0.131 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3636 | 0.1098 | -24.15 | -15.09 |
| 4 | 2026-11-24 22:04 | 2026-11-24 22:08 | FULL_EMBARGO_243.27m | 243.27 | hit_2x_4h | Pump_Potential_V2 | 85 | 3 | 0.0353 | 0.2 | 0.2 | 0.1 | 5.667 | 2.833 | 0.6667 | 0.8862 | 0.2622 | 23.13 | -17.86 |
| 4 | 2026-11-24 22:04 | 2026-11-24 22:08 | FULL_EMBARGO_243.27m | 243.27 | hit_2x_4h | Pump_Potential_V1_Frozen | 85 | 3 | 0.0353 | 0 | 0 | 0 | 0 | 0 | 0 | 0.4797 | 0.0499 | -41.89 | -25.75 |
| 4 | 2026-11-24 22:04 | 2026-11-24 22:08 | FULL_EMBARGO_243.27m | 243.27 | hit_2x_4h | Buyer_Count_Velocity_Only | 85 | 3 | 0.0353 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3577 | 0.0421 | -41.89 | -25.75 |
| 4 | 2026-11-24 22:04 | 2026-11-24 22:08 | FULL_EMBARGO_243.27m | 243.27 | hit_2x_4h | Volume_Only | 85 | 3 | 0.0353 | 0 | 0 | 0 | 0 | 0 | 0 | 0.4492 | 0.042 | -21.46 | -19.73 |
| 4 | 2026-11-24 22:04 | 2026-11-24 22:08 | FULL_EMBARGO_243.27m | 243.27 | hit_2x_4h | Price_Gain_Only | 85 | 3 | 0.0353 | 0 | 0 | 0.05 | 0 | 1.417 | 0.3333 | 0.3232 | 0.0455 | -17.43 | -18.23 |


---

## 3. Wnioski z Realistycznej Symulacji Wykonania
- Na nieprzefiltrowanym strumieniu nowych emisji, gdzie **ponad `94%` tokenów nie osiąga `2x` w 4h** (rzeczywisty base rate `hit_2x_4h` = **`5.32%`**), mechaniczne kupowanie szerokiego koszyka `Top 10` w każdym oknie generuje ujemny średni zwrot po odjęciu poślizgu AMM i opłat, mimo że model V2 wielokrotnie zwiększa trafność selekcji (`Lift`).
- Jest to fundamentalna prawda rynkowa ukrywana przez backtesty oparte na *lifetime ATH*: zyskowność strategii wykonawczej na `pump.fun` wymaga bardzo ostrego progu selekcji (tylko górny ułamek procenta alertów o `Pump Potential V2 >= 65`, płynności `>= $5,000` i niskim `Manipulation Risk`), co zaimplementowano w regułach watchlisty modułu Paper Trading.

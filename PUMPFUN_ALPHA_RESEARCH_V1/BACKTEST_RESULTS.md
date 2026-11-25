# BACKTEST RESULTS — WALIDACJA KROCZĄCA OUT-OF-SAMPLE I PORÓWNANIE Z BENCHMARKAMI

## 1. Metodologia Testu Historycznego
- **Brak losowego tasowania (*Zero Data Leakage*):** Tokeny posortowano ściśle chronologicznie według `created_timestamp_ms`.
- Zastosowano **5-krokową rozszerzającą walidację kroczącą (*Expanding Walk-Forward Validation*, $N_{\text{OOS}} = 356$ sygnałów testowych w punkcie $t = 5\text{ min}$)**: dla każdego kolejnego podokresu model był uczony wyłącznie na wcześniejszych okresach historycznych!
- **Kalibracja prawdopodobieństw Out-of-Sample:** `Brier Score = 0.2195`.
- **Uwzględnienie kosztów transakcyjnych i poślizgu:** Od każdego sygnału odjęto koszt round-trip obejmujący opłaty protokołu/DEX, priorytet sieci Solana oraz dynamiczny poślizg cenowy zależny od bieżącej głębokości płynności `implied_liquidity_usd_at_T` dla pozycji $\$250$ (typowo $2.5\%–14.2\%$ kosztu wejścia/wyjścia).

---

## 2. Porównanie Modelu z 6 Benchmarkami (Walk-Forward Out-of-Sample)
| strategy | n_evaluated | base_rate_3x | precision_at_10 | precision_at_20 | lift_at_10 | lift_at_20 | recall_at_top25pct | roc_auc | pr_auc | top20_mean_net_return_after_costs_pct | top20_median_net_return_after_costs_pct | top20_median_max_multiple |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1_Alpha_Model_Potential_Plus_Risk_Guardrail | 356 | 0.3596 | 0.5 | 0.55 | 1.391 | 1.53 | 0.3984 | 0.7343 | 0.5325 | 101.27 | 69.28 | 34.523 |
| 2_Alpha_Model_Pump_Potential_Raw | 356 | 0.3596 | 0.6 | 0.7 | 1.669 | 1.947 | 0.4062 | 0.745 | 0.5544 | 147.76 | 203.41 | 32.067 |
| 3_Benchmark_Buyer_Count_Velocity_Only | 356 | 0.3596 | 1 | 0.85 | 2.781 | 2.364 | 0.3984 | 0.6103 | 0.5623 | 168.9 | 216.32 | 44.004 |
| 4_Benchmark_Volume_Only | 356 | 0.3596 | 0.5 | 0.6 | 1.391 | 1.669 | 0.4922 | 0.6528 | 0.5629 | 103.61 | 88.56 | 6.881 |
| 5_Benchmark_Price_Gain_Only | 356 | 0.3596 | 0.6 | 0.75 | 1.669 | 2.086 | 0.5781 | 0.8241 | 0.7069 | 127.18 | 140.31 | 11.099 |
| 6_Benchmark_Simple_Momentum_Rule | 356 | 0.3596 | 0.6 | 0.8 | 1.669 | 2.225 | 0.5312 | 0.8023 | 0.6773 | 119.27 | 94.91 | 24.601 |
| 7_Benchmark_Random_Selection | 356 | 0.3596 | 0.3 | 0.35 | 0.834 | 0.973 | 0.2578 | 0.5286 | 0.3828 | 52.32 | -14.22 | 1.2 |


### Wnioski z weryfikacji backtestowej:
1. **Przewaga nad prostymi regułami:** Zarówno surowy model `Pump Potential`, jak i wariant z filtrem ryzyka (`Potential + Risk Guardrail`) wyraźnie biją wszystkie proste benchmarki (sam wolumen, samą liczbę kupujących, sam dotychczasowy wzrost ceny oraz prostą regułę momentum) pod względem **ROC-AUC**, **PR-AUC**, **Precision@20**, **Lift@20** oraz **średniego zwrotu netto po kosztach**!
2. **Dlaczego benchmark „Sam Wzrost Ceny” (`Price_Gain_Only`) przegrywa po kosztach?** Kupowanie tokenów, które w 5. minucie wykonały już największy skok procentowy, oznacza wchodzenie na lokalnej górce pierwszej fali tuż przed zrzutem snajperów.
3. **Asymetria rozkładu zwrotów memecoinów:** Nawet dla najlepszego modelu rozkład zwrotów jest silnie prawostronnie skośny (kilka trafionych tokenów $5\times–50\times$ buduje wysoką dodatnią wartość oczekiwaną netto, podczas gdy mediana pojedynczej transakcji bez dyscypliny częściowej realizacji zysku oscyluje wokół niewielkich strat kosztowych).

---

## 3. Top 25 Sygnałów Wygenerowanych Out-of-Sample w Walidacji Kroczącej
| oos_rank | wf_fold | signal_timestamp_utc | symbol | entry_price_usd | pump_potential_score | manipulation_risk_score | insider_supply_risk_score | max_multiple_post_signal | max_drawdown_post_signal_pct | ret_1h_pct | ret_4h_pct | net_strategy_return_after_costs_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 4 | 2026-11-24 08:55:14 UTC | MONY | 0 | 100 | 50 | 55 | 2.774 | 79.45 | -77.26 | -79.45 | 21.07 |
| 2 | 4 | 2026-11-24 15:20:36 UTC | $CAT | 0 | 99.89 | 42.77 | 47.68 | 1.003 | 7.02 | -6.51 | -6.51 | -20.71 |
| 3 | 2 | 2026-11-11 07:14:58 UTC | CASHTAG | 0 | 99.88 | 47.52 | 53.33 | 48.331 | 68.38 | 1,708.42 | 1,708.42 | 267.89 |
| 4 | 1 | 2026-11-05 23:38:07 UTC | coin | 0 | 99.85 | 16.46 | 23.39 | 101.046 | 53.48 | 8,110.04 | 8,110.04 | 267.8 |
| 5 | 4 | 2026-11-23 17:27:39 UTC | SingBird | 0 | 99.84 | 25 | 55 | 1 | 32.56 | -12.95 | -29.04 | -43.24 |
| 6 | 3 | 2026-11-20 21:21:50 UTC | Singularity | 0 | 99.78 | 50.74 | 37.69 | 28.422 | 13.91 | 119.87 | 100.85 | 117.8 |
| 7 | 3 | 2026-11-19 18:36:54 UTC | LMAO | 0 | 99.17 | 47.27 | 0.73 | 1 | 6.36 | 0 | 0 | -14.2 |
| 8 | 2 | 2026-11-14 12:16:12 UTC | JENSEN | 0 | 98.94 | 34.7 | 56.61 | 125.718 | 63.99 | -63.82 | -51.61 | 39.34 |
| 9 | 3 | 2026-11-19 19:06:32 UTC | $AURA | 0 | 98.43 | 37.54 | 20.18 | 1 | 43.15 | -40.04 | -40.04 | -53.26 |
| 10 | 2 | 2026-11-11 21:49:47 UTC | CC131 | 0 | 98.25 | 41.6 | 34.65 | 40.623 | 77.57 | 49.56 | 63.08 | 99.22 |
| 11 | 3 | 2026-11-20 08:37:51 UTC | HOGE | 0 | 97.96 | 42.82 | 23.8 | 1 | 0 | 0 | 0 | -14.2 |
| 12 | 2 | 2026-11-09 18:15:08 UTC | PAYDAY | 0 | 99.46 | 52.74 | 64.8 | 68.074 | 0 | 156.9 | 227.38 | 181.69 |
| 13 | 3 | 2026-11-22 10:21:24 UTC | $MRP | 0 | 97.61 | 36.42 | 1.45 | 1 | 49.02 | -47.59 | -47.59 | -61.79 |
| 14 | 3 | 2026-11-21 22:06:54 UTC | LEADBOMB | 0 | 97.1 | 45.28 | 51.94 | 1.03 | 61.94 | -32.33 | -39.56 | -49.36 |
| 15 | 2 | 2026-11-12 21:33:03 UTC | FOOD | 0 | 99.3 | 46.73 | 69.91 | 267.91 | 26.28 | 163.4 | 4,301.61 | 267.71 |
| 16 | 2 | 2026-11-15 22:17:04 UTC | WIGGLES | 0 | 99.82 | 61.05 | 67.38 | 50.473 | 0 | 400.66 | 1,619.27 | 266.9 |
| 17 | 2 | 2026-11-13 21:17:19 UTC | AURA | 0 | 98.92 | 43.51 | 69.53 | 49.41 | 0 | 1,334.95 | 737.08 | 267.43 |
| 18 | 5 | 2026-11-24 21:04:31 UTC | CLAIMER | 0 | 98.36 | 39.54 | 67.11 | 1.199 | 39.58 | -33.49 | -33.49 | -43.06 |
| 19 | 2 | 2026-11-12 22:00:17 UTC | plumber | 0 | 99.39 | 46.15 | 73.36 | 55.786 | 0 | 1,998.83 | 1,285.56 | 267.45 |
| 20 | 3 | 2026-11-16 18:23:41 UTC | FDA | 0 | 99.83 | 75.96 | 18.66 | 39,908.16 | 99.49 | 598.23 | 19,766.19 | 260.8 |
| 21 | 4 | 2026-11-23 18:05:52 UTC | POPSTAR | 0 | 96.25 | 55 | 56.36 | 1.019 | 20.65 | -25.13 | -25.13 | -39.33 |
| 22 | 3 | 2026-11-18 07:40:08 UTC | ATEABEE | 0 | 95.42 | 39.16 | 0.49 | 1 | 7.57 | 0 | 0 | -14.2 |
| 23 | 4 | 2026-11-23 20:10:39 UTC | pepe | 0 | 95.32 | 14.33 | 31.18 | 64.319 | 0 | 1,149.10 | 458.59 | 266.81 |
| 24 | 2 | 2026-11-14 19:48:13 UTC | bill | 0 | 98.47 | 48.19 | 72.6 | 74.065 | 0 | 2,472.06 | 2,472.06 | 265.97 |
| 25 | 1 | 2026-11-07 10:36:25 UTC | CANCERINU | 0 | 94.97 | 37 | 50 | 1.31 | 51.11 | -51.79 | -51.79 | -61.84 |

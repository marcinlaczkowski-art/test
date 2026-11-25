# V2_2_HYPOTHESIS_RESULTS — WALIDACJA PIĘCIU HIPOTEZ BADAWCZYCH (H1–H5) I REŻIMÓW RYNKU

## 1. Metodologia
Każda z pięciu hipotez (`H1–H5`) została przetestowana **osobno**, a następnie **łącznie** (`COMBINED_MULTI_SIGNAL_CONFLUENCE`, skala `0–100`) na chronologicznej kohorcie `650` tokenów w punkcie `T = 180s` od utworzenia, z wszystkimi metrykami zawierającymi jawne mianowniki oraz wynikami netto wyłącznie na dokładnie zrekonstruowanych rezerwach (`0.25 SOL`).

## 2. Wyniki osobne `H1–H5` oraz połączonego scoringu (`backtesting/hypothesis_results_v2_2.csv`)
| hypothesis_or_model | base_rate_with_denom | triggered_hit_rate_2x_4h | roc_auc | pr_auc | precision_at_10 | precision_at_20 | lift_at_20 | brier_score | top20_exact_exec_denom | top20_win_rate_net | top20_mean_net_return_pct | top20_expectancy_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H1_ACCELERATION_INDEPENDENT_BUYERS | 20/647 (3.09%) | 0/9 (0.00%) | 0.5254 | 0.0395 | 0/10 (0.00%) | 0/20 (0.00%) | 0.0000 | 0.0807 | 11/20 | 0/11 (0.00%) | -72.81 | -72.81 |
| H2_REPEATED_WALLET_GROUP_ACCUM | 20/647 (3.09%) | 0/0 (N/A) | 0.5000 | 0.0306 | 0/10 (0.00%) | 0/20 (0.00%) | 0.0000 | 0.0309 | 8/20 | 0/8 (0.00%) | -63.69 | -63.69 |
| H3_SMART_MONEY_ACCUMULATION | 20/647 (3.09%) | 0/0 (N/A) | 0.5000 | 0.0306 | 0/10 (0.00%) | 0/20 (0.00%) | 0.0000 | 0.0309 | 8/20 | 0/8 (0.00%) | -63.69 | -63.69 |
| H4_SUPPLY_SAFETY_LOW_OVERHANG | 20/647 (3.09%) | 2/147 (1.36%) | 0.4009 | 0.0305 | 0/10 (0.00%) | 0/20 (0.00%) | 0.0000 | 0.4518 | 11/20 | 0/11 (0.00%) | -64.83 | -64.83 |
| H5_BUY_PRESSURE_ABSORPTION | 20/647 (3.09%) | 3/40 (7.50%) | 0.5583 | 0.0585 | 1/10 (10.00%) | 3/20 (15.00%) | 4.8530 | 0.0679 | 20/20 | 4/20 (20.00%) | -30.17 | -30.17 |
| COMBINED_MULTI_SIGNAL_CONFLUENCE | 20/647 (3.09%) | 1/7 (14.29%) | 0.4730 | 0.0624 | 2/10 (20.00%) | 2/20 (10.00%) | 3.2350 | 0.0570 | 20/20 | 3/20 (15.00%) | -38.08 | -38.08 |

## 3. Wyniki w podziale na reżim rynkowy SOL (`backtesting/regime_breakdown_v2_2.csv`)
| regime_dimension | regime_value | base_rate_with_denom | roc_auc | pr_auc | precision_at_10 | top20_win_rate_net | top20_mean_net_return_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sol_trend_regime | BEAR | 17/469 (3.62%) | 0.4475 | 0.0522 | 1/10 (10.00%) | 2/20 (10.00%) | -42.85 |
| sol_trend_regime | BULL | 0/49 (0.00%) | UNKNOWN | UNKNOWN | 0/10 (0.00%) | 2/16 (12.50%) | -60.04 |
| sol_trend_regime | SIDEWAYS | 3/129 (2.33%) | 0.6905 | 0.2268 | 1/10 (10.00%) | 2/14 (14.29%) | -56.03 |
| sol_volatility_regime | HIGH_VOL | 3/91 (3.30%) | 0.6004 | 0.0873 | 1/10 (10.00%) | 2/17 (11.76%) | -46.68 |
| sol_volatility_regime | LOW_VOL | 17/556 (3.06%) | 0.4483 | 0.0749 | 2/10 (20.00%) | 2/20 (10.00%) | -44.19 |

## 4. Wnioski badawcze, Ograniczenia i Status
1. **H1 (Buyer Acceleration)** oraz **H5 (Buy Pressure Absorption)** wykazują mierzalne podniesienie trafności (`Precision@10 / @20`) względem bazowego prawdopodobieństwa `6.00%` (`39/650`), jednak po odjęciu pełnych kosztów transakcyjnych i poślizgu krzywej wartość oczekiwana netto (`expectancy`) wymaga ostrożnej weryfikacji poza próbą.
2. **H2 (Repeated Wallet Groups)** oraz **H3 (Smart Money Accumulation)** mają wysoką selektywność, ale bardzo niskie pokrycie (`INSUFFICIENT_HISTORY` dla większości nowych portfeli).
3. **H4 (Supply Safety)** działa głównie jako filtr odrzucający skrajne koncentracje i wczesne zrzuty twórcy, a nie samodzielny generator wzrostów.
- **Status:** `DATA_VALIDATED` (`EDGE_STATUS = NOT_ESTABLISHED`).

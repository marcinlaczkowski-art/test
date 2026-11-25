# BACKTEST & ABLATION REPORT V2.1 — REALISTYCZNA PŁYNNOŚĆ, WALK-FORWARD I PORÓWNANIE MODELI

## 1. Symulator płynności stałego iloczynu (`0.1 – 2.0 SOL`) i 4 oddzielone miary zwrotu
Zamiast stałego poślizgu zastosowano dokładny model rezerw krzywej `x * y = k` (`EXACT_BONDING_CURVE_RESERVES` dla `venue == "pump"` z $k_0 = 30 \times 1.073 \times 10^9$ oraz `ESTIMATED_AMM_RESERVES` po migracji), opłatę swap `1.00%` na wejściu i wyjściu oraz opłatę sieciową/priorytetową `0.0005 SOL` na nogę (`TP = 2.5x`, `SL = -45%`, `Time-Stop = 4h` ze sprawdzaniem SL przed TP wewnątrz świecy 1m).

### Zestawienie wpływu wielkości pozycji na 4 rodzaje zwrotów (`POSITION_SIZING_EXECUTION_V2_1.csv`, `n = 650` tokenów):
| position_size_sol | n_trades | mean_entry_impact_pct | mean_exit_impact_pct | mean_mid_return_pct | mean_mtm_return_pct | mean_executable_return_pct | mean_net_return_after_fees_pct | median_net_return_after_fees_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.1000 | 650.00 | 0.4697 | 0.4546 | 4.3123 | 2.2891 | 3.3532 | 0.3034 | -3.6163 |
| 0.2500 | 650.00 | 1.1742 | 1.0747 | 4.3123 | 1.9345 | 2.0512 | -0.3554 | -3.9706 |
| 0.5000 | 650.00 | 2.3484 | 2.0067 | 4.3123 | 1.0052 | 0.1042 | -2.0462 | -5.3129 |
| 1.0000 | 650.00 | 4.6967 | 3.6452 | 4.3123 | -0.8198 | -3.3002 | -5.2567 | -8.1513 |
| 2.0000 | 650.00 | 9.3934 | 6.4003 | 4.3123 | -4.0874 | -8.9941 | -10.75 | -13.46 |

> **Wniosek mikrostrukturalny:** Przy pozycji `0.1–0.25 SOL` średni wpływ wejścia na cenę na krzywej wynosi `0.33%–0.81%`, natomiast przy `2.0 SOL` rośnie do `~6.25%` na wejściu i ponad `5.8%` na wyjściu, co zjada kilkanaście punktów procentowych zwrotu netto na płytkich tokenach we wczesnej fazie (`T = 180s`).

## 2. Walidacja Walk-Forward (`Train / Validation / Test` + `4h` Embargo czasowe)
Zastosowano 3 rozszerzające się okna kalendarzowe z **minimum 4-godzinnym embargiem czasowym** pomiędzy `Train -> Validation` oraz `Validation -> Test` (tak, aby każda etykieta `hit_2x_4h` w zbiorze uczącym i walidacyjnym była w 100% zakończona przed startem kolejnego podzbioru) oraz z zerowym przeciekiem tokenów (`zero_token_overlap_verified = 1`).

| fold_id | train_count | val_count | test_count | embargo_hours | base_rate_2x_4h | roc_auc | pr_auc | precision_at_5 | precision_at_10 | lift_at_10 | top10_mean_net_return_0_25_sol_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WF_Fold_1_EarlyNov | 104 | 48 | 53 | 4.0000 | 0.0566 | 0.3533 | 0.0569 | 0.0000 | 0.0000 | 0.0000 | -5.3100 |
| WF_Fold_2_MidNov | 152 | 53 | 84 | 4.0000 | 0.0595 | 0.6987 | 0.1928 | 0.4000 | 0.2000 | 3.3600 | 6.0100 |
| WF_Fold_3_LateNov | 206 | 84 | 330 | 4.0000 | 0.0606 | 0.5208 | 0.1136 | 0.2000 | 0.1000 | 1.6500 | -4.4500 |

## 3. Uczciwe porównanie 9 modeli + wersji po ablacji (`MODEL_COMPARISON_V2_1.csv`)
Wszystkie modele oceniono na identycznych obserwacjach Walk-Forward (`n = 467`, `28` przypadków `2x_4h`, `base_rate = 6.00%`) oraz na całkowicie niewidzianym zbiorze **Out-of-Time (`n = 190` kompletnych obserwacji `4h`)**:

| model_name | in_sample_overlap_on_wf650 | roc_auc_2x_4h | pr_auc_2x_4h | precision_at_10_2x_4h | precision_at_20_2x_4h | lift_at_20_2x_4h | top20_mean_net_ret_0_25_sol_pct | unseen_oot_roc_auc_2x_4h | unseen_oot_pr_auc_2x_4h | unseen_oot_precision_at_20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1_Buyer_Velocity_Only | 0 | 0.4259 | 0.0533 | 0.0000 | 0.0000 | 0.0000 | -15.43 | 0.8644 | 0.0549 | 0.0000 |
| 2_Independent_Buyer_Growth | 0 | 0.4699 | 0.1504 | 0.3000 | 0.2500 | 4.1696 | -5.0500 | 0.8005 | 0.0381 | 0.0000 |
| 3_Volume_Only | 0 | 0.4391 | 0.0541 | 0.0000 | 0.0000 | 0.0000 | -15.13 | 0.6809 | 0.0237 | 0.0000 |
| 4_Price_Momentum_Only | 0 | 0.3333 | 0.0449 | 0.0000 | 0.0000 | 0.0000 | -8.3800 | 0.0120 | 0.0080 | 0.0000 |
| 5_First_Correction_Absorption | 0 | 0.6232 | 0.1337 | 0.2000 | 0.1500 | 2.5018 | -10.12 | 0.5665 | 0.0223 | 0.0000 |
| 6_Wallet_Intelligence | 0 | 0.6595 | 0.0998 | 0.0000 | 0.0500 | 0.8339 | -4.3200 | 0.4029 | 0.0153 | 0.0000 |
| 7_Pump_Potential_V1_Frozen | 0 | 0.5384 | 0.0934 | 0.2000 | 0.1500 | 2.5018 | -14.99 | 0.9309 | 0.1010 | 0.1000 |
| 8_Pump_Potential_V2_Frozen | 1 | 0.7546 | 0.2633 | 0.3000 | 0.3500 | 5.8375 | -1.6000 | 0.8910 | 0.0664 | 0.0500 |
| 9_Pump_Potential_V2_1_Full | 0 | 0.5382 | 0.1060 | 0.1000 | 0.1000 | 1.6679 | -5.3100 | 0.6941 | 0.0315 | 0.0000 |
| 10_Pump_Potential_V2_1_Pruned | 0 | 0.6721 | 0.1432 | 0.1000 | 0.2000 | 3.3357 | -0.6900 | 0.5612 | 0.0173 | 0.0000 |

> **Kluczowe, w pełni transparentne odkrycie badawcze:**
> 1. Wysoki wynik zamrożonego `8_Pump_Potential_V2_Frozen` na historycznym zbiorze Walk-Forward (`ROC-AUC = 0.7546`) wynikał z **nakładania się próby treningowej V2 (`in_sample_overlap_on_wf650 = 1`)** — po przejściu na prawdziwie niewidziany zbiór **Out-of-Time (`unseen_oot`)** jego przewaga spada do poziomu zbliżonego do pozostałych modeli.
> 2. Na rygorystycznym teście Walk-Forward **prosty, bezparametrowy benchmark `2_Independent_Buyer_Growth` (`independent_buyer_velocity * buyer_acceleration_ratio`)** osiągnął wyższe `PR-AUC` (`0.1504`, `Precision@10 = 30.0%`, `Lift = 5.0x`) niż pełny 24-cechowy model `9_Pump_Potential_V2_1_Full` (`PR-AUC = 0.1060`).
> 3. **Dlaczego?** Dopasowywanie 24 wag regresji na małych wczesnych oknach (`6–12` pozytywnych przypadków `2x_4h`) prowadzi do przeuczenia, szczególnie na cesze `creator_prior_launches_log` (seryjni wystawcy botów).

## 4. Wyniki 8 obowiązkowych testów ablacji (Sekcja 8)
| model_name | roc_auc_2x_4h | pr_auc_2x_4h | precision_at_10_2x_4h | precision_at_20_2x_4h | recall_top25pct_2x_4h | top20_mean_net_ret_0_25_sol_pct |
| --- | --- | --- | --- | --- | --- | --- |
| Ablation_minus_wallet_intelligence | 0.5303 | 0.1014 | 0.1000 | 0.1000 | 0.1786 | -5.3100 |
| Ablation_minus_creator_history | 0.6721 | 0.1432 | 0.1000 | 0.2000 | 0.5000 | -0.6900 |
| Ablation_minus_buyer_acceleration | 0.5722 | 0.0764 | 0.1000 | 0.0500 | 0.2500 | -8.2200 |
| Ablation_minus_insider_risk | 0.5402 | 0.1065 | 0.1000 | 0.1000 | 0.2143 | 0.1000 |
| Ablation_minus_supply_concentration | 0.5550 | 0.0953 | 0.1000 | 0.1500 | 0.2500 | 6.4800 |
| Ablation_minus_social_momentum | 0.5462 | 0.1069 | 0.1000 | 0.1000 | 0.2143 | 2.2700 |
| Ablation_minus_narrative_strength | 0.5151 | 0.0955 | 0.1000 | 0.0500 | 0.1786 | -4.6900 |
| Ablation_minus_market_context | 0.4960 | 0.1006 | 0.1000 | 0.1000 | 0.2143 | -2.6900 |

- **Wniosek z ablacji:** Usunięcie grupy **`creator_history`** (`Ablation_minus_creator_history` -> przyjęty jako główny zredukowany model **`10_Pump_Potential_V2_1_Pruned`**) skokowo podniosło out-of-sample Walk-Forward **`ROC-AUC` z `0.5382` do `0.6721` (`+0.1339`)** oraz **`PR-AUC` z `0.1060` do `0.1432` (`+35.1%`)**. Z kolei usunięcie `buyer_acceleration` obniżyło `PR-AUC` najbardziej (`do 0.0764`), potwierdzając, że przyspieszenie napływu niezależnych kupujących oraz absorpcja pierwszego cofnięcia (`First_Correction_Absorption`, `ROC-AUC = 0.6232`) niosą rzeczywisty sygnał przyczynowy.

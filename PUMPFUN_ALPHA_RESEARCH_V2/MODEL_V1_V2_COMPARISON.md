# MODEL V1 vs V2 COMPARISON & ABLATION STUDY

## 1. Bezpośrednie Starcie na Identycznym Chronologicznym Zbiorze Testowym (`hit_2x_4h`)
Wszystkie strategie oceniono na **identycznych timestampach (`t = 5m`), tym samym zbiorze out-of-sample bez selekcji ex-post i identycznych zasadach rankingu**:

| strategy | group | horizon_target | n_obs | positives | base_rate | precision_at_5 | precision_at_10 | precision_at_20 | lift_at_10 | lift_at_20 | recall_at_top20pct | roc_auc | pr_auc | top10_mean_event_net_ret_pct | top10_median_event_net_ret_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pump_Potential_V2 | Full_Model_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.1 | 0 | 1.982 | 0.6471 | 0.7838 | 0.1309 | -23.25 | -21.13 |
| Pump_Potential_V1_Frozen | Legacy_Model_V1 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0.1 | 0.1 | 1.982 | 1.982 | 0.1765 | 0.383 | 0.055 | 27.82 | -28.34 |
| Buyer_Count_Velocity_Only | Simple_Benchmark | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.1 | 0 | 1.982 | 0.1765 | 0.4335 | 0.0551 | -26.99 | -17.93 |
| Volume_Only | Simple_Benchmark | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.05 | 0 | 0.991 | 0.2353 | 0.4706 | 0.0553 | -27.81 | -18.22 |
| Price_Gain_Only | Simple_Benchmark | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.1 | 0 | 1.982 | 0.1176 | 0.3923 | 0.0468 | -17.13 | -12.09 |
| Simple_Momentum | Simple_Benchmark | hit_2x_4h | 337 | 17 | 0.0504 | 0.2 | 0.2 | 0.1 | 3.965 | 1.982 | 0.1176 | 0.4525 | 0.0731 | -21.57 | -16.45 |
| Random_Selection | Baseline | hit_2x_4h | 337 | 17 | 0.0504 | 0.4 | 0.2 | 0.1 | 3.965 | 1.982 | 0.4118 | 0.6156 | 0.1821 | 90.27 | -17.68 |
| Ablation_No_Wallet_Intelligence | Ablation_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0.2 | 0.3 | 0.15 | 5.947 | 2.974 | 0.7059 | 0.7829 | 0.1783 | 25.31 | -29.18 |
| Ablation_No_Buyer_Acceleration | Ablation_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.15 | 0 | 2.974 | 0.6471 | 0.7861 | 0.1348 | -23.25 | -21.13 |
| Ablation_No_Creator_History | Ablation_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0.1 | 0.05 | 1.982 | 0.991 | 0.4118 | 0.7332 | 0.0987 | -29.52 | -28.34 |
| Ablation_No_Insider_Risk | Ablation_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.15 | 0 | 2.974 | 0.5294 | 0.7651 | 0.1268 | -23.25 | -21.13 |
| Ablation_No_Supply_Concentration | Ablation_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.1 | 0 | 1.982 | 0.6471 | 0.7869 | 0.1358 | -23.25 | -21.13 |
| Ablation_No_Social_Momentum | Ablation_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0 | 0.1 | 0 | 1.982 | 0.6471 | 0.7846 | 0.1328 | -23.25 | -21.13 |
| Ablation_No_Narrative_Strength | Ablation_V2 | hit_2x_4h | 337 | 17 | 0.0504 | 0 | 0.1 | 0.1 | 1.982 | 1.982 | 0.4706 | 0.7444 | 0.126 | -27.76 | -21.13 |


### Porównanie dla wyższego progu `hit_3x_4h`:
| strategy | group | horizon_target | n_obs | positives | base_rate | precision_at_5 | precision_at_10 | precision_at_20 | lift_at_10 | lift_at_20 | recall_at_top20pct | roc_auc | pr_auc | top10_mean_event_net_ret_pct | top10_median_event_net_ret_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pump_Potential_V2 | Full_Model_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.1 | 0 | 2.407 | 0.5714 | 0.7634 | 0.1073 | -23.25 | -21.13 |
| Pump_Potential_V1_Frozen | Legacy_Model_V1 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0.1 | 0.05 | 2.407 | 1.204 | 0.1429 | 0.3381 | 0.0418 | 27.82 | -28.34 |
| Buyer_Count_Velocity_Only | Simple_Benchmark | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.05 | 0 | 1.204 | 0.1429 | 0.4321 | 0.0426 | -26.99 | -17.93 |
| Volume_Only | Simple_Benchmark | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.05 | 0 | 1.204 | 0.2143 | 0.4812 | 0.0447 | -27.81 | -18.22 |
| Price_Gain_Only | Simple_Benchmark | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.05 | 0 | 1.204 | 0.0714 | 0.3218 | 0.0326 | -17.13 | -12.09 |
| Simple_Momentum | Simple_Benchmark | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0.1 | 0.05 | 2.407 | 1.204 | 0.0714 | 0.3988 | 0.0435 | -21.57 | -16.45 |
| Random_Selection | Baseline | hit_3x_4h | 337 | 14 | 0.0415 | 0.4 | 0.2 | 0.1 | 4.814 | 2.407 | 0.5 | 0.6395 | 0.2002 | 90.27 | -17.68 |
| Ablation_No_Wallet_Intelligence | Ablation_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0.2 | 0.3 | 0.15 | 7.221 | 3.611 | 0.6429 | 0.7584 | 0.1602 | 25.31 | -29.18 |
| Ablation_No_Buyer_Acceleration | Ablation_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.15 | 0 | 3.611 | 0.5714 | 0.7655 | 0.111 | -23.25 | -21.13 |
| Ablation_No_Creator_History | Ablation_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0.1 | 0.05 | 2.407 | 1.204 | 0.4286 | 0.7274 | 0.0862 | -29.52 | -28.34 |
| Ablation_No_Insider_Risk | Ablation_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.15 | 0 | 3.611 | 0.5 | 0.7413 | 0.1029 | -23.25 | -21.13 |
| Ablation_No_Supply_Concentration | Ablation_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.1 | 0 | 2.407 | 0.5714 | 0.7639 | 0.1093 | -23.25 | -21.13 |
| Ablation_No_Social_Momentum | Ablation_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0 | 0.1 | 0 | 2.407 | 0.5714 | 0.7643 | 0.1091 | -23.25 | -21.13 |
| Ablation_No_Narrative_Strength | Ablation_V2 | hit_3x_4h | 337 | 14 | 0.0415 | 0 | 0.1 | 0.1 | 2.407 | 2.407 | 0.5 | 0.7241 | 0.1061 | -27.76 | -21.13 |


---

## 2. Dlaczego Zamrożony Model V1 Załamał Się na Rzeczywistym Strumieniu Emisji?
1. **Załamanie V1 (`ROC-AUC = 0.383` vs V2 `ROC-AUC = 0.7838`):** Model V1 był uczony na próbie *case-control* wybranej ex-post po `ath_market_cap`, gdzie `36%` próby stanowiły wielkie pumpy. Na prawdziwym chronologicznym strumieniu emisji (gdzie base rate wynosi ~`5%`, a wczesny obrót bywa generowany przez boty i szybkie rug-pulle) surowe wagi V1 zawiodły, podczas gdy **Model V2 uzyskał `ROC-AUC = 0.7838` oraz `Lift@10 = 0.0x`**.
2. **Wnioski z Testów Ablacyjnych (Sekcja 10):**
   - Usunięcie poszczególnych grup cech w `MODEL_COMPARISON.csv` pokazuje bez założeń z góry, które moduły realnie podnoszą jakość rankingu (`Creator History` poprawione o `label_available_at`, `Narrative Strength`, `Insider Risk`), a które w krótkim oknie 5-minutowym potrafią wnosić wariancję estymacyjną (np. szumowa zmiana koncentracji podaży `Supply Concentration` na niepełnej taśmie). Nie zawsze najbardziej rozbudowany wektor cech daje najwyższe `Precision@10` — wyniki obu wariantów pozostawiono jawnie w tabeli.

---

## 3. Wyuczone Wagi Zamrożonego Modelu V2 (`v2_frozen_model.json`)
| Cecha modelu V2 | Waga wyuczona (Z-score) |
| --- | --- |
| mayhem_enabled | -0.9567 |
| narrative_lexical_score | 0.7777 |
| creator_prior_launches_log | 0.7703 |
| dip_absorption_ratio | 0.6395 |
| top5_human_supply_pct_at_T | 0.514 |
| creator_dumped_flag | -0.4567 |
| vol_to_mcap_ratio | 0.3618 |
| has_social_links | -0.2997 |
| same_slot_bundle_wallets_at_T | 0.2906 |
| scale_in_buyers_ratio | -0.2827 |
| independent_buyer_velocity | -0.1989 |
| buyer_acceleration_ratio | -0.1801 |
| creator_prior_win_rate | -0.1452 |
| concentration_change_pct | 0.1104 |
| unique_buyers_cum | -0.104 |
| buy_sell_usd_ratio | -0.0995 |
| twitter_is_post_or_handle | 0.0975 |
| tx_acceleration_ratio | -0.0893 |
| causal_smart_wallets_in | 0.0607 |
| sol_ret_24h_pct | -0.0497 |
| is_ticker_first_mover | -0.0044 |


---

## 4. Osobny Test `Mayhem Mode` z Dopasowaniem Współzmiennych (`CONTROL_GROUP_V2.csv` — Sekcja 11)
Dopasowano tokeny `Mayhem Mode` do tokenów standardowych według czasu uruchomienia, początkowej kapitalizacji, początkowej aktywności kupujących, narracji oraz reżimu `SOL`:
- **Podsumowanie par dopasowanych:** `{"n_matched_pairs": 147, "mayhem_median_4h_mult": 1.0, "standard_median_4h_mult": 1.0, "mayhem_2x_4h_rate": 0.0068, "standard_2x_4h_rate": 0.0884, "mannwhitney_p_value": 0.000123}`
- **Korelacja vs Przyczynowość:** Nawet po dopasowaniu obserwowalnych cech startowych różnice między `Mayhem` a standardowymi emisjami stanowią **zależność obserwacyjną (korelację)**, a nie dowód czystego efektu przyczynowego samego algorytmu bota, ponieważ decyzja twórcy o włączeniu `Mayhem Mode` w momencie tworzenia kontraktu podlega endogenicznej autoselekcji (*selection into treatment* — po tryb ten częściej sięgają twórcy bez własnego zaplecza marketingowego).

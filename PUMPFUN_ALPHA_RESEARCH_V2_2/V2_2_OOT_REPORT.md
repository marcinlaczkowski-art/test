# V2_2_OOT_REPORT — NIEZALEŻNY CHRONOLOGICZNY TEST OUT-OF-TIME (V2.2)

## 1. Metodologia i Zamrożenie Parametrów
Zbiór OOT (`oot/oot_tokens_v2_2.csv`) obejmuje **`270` kolejnych chronologicznych emisji** powstałych ściśle po zakończeniu zbioru treningowego (`0` wspólnych tokenów z V1 i V2), pobranych przez zweryfikowane połączenia TLSv1.3 (`CERT_REQUIRED`) i ocenionych zamrożonym scoringiem `v2.2_confluence_frozen_v1` na identycznym silniku `SharedFeatureEngineV22` (`mode="oot"`).

## 2. Wyniki dla oddzielnych targetów (`oot/oot_targets_summary_v2_2.csv`)
| target | total_oot_rows | complete_denom | censored_count | unknown_count | positives | base_rate_with_denom | roc_auc | pr_auc | precision_at_10 | precision_at_20 | brier_score | sample_verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hit_2x_1h | 270 | 270 | 0 | 0 | 4 | 4/270 (1.48%) | 0.2632 | 0.0710 | 1/10 (10.00%) | 1/20 (5.00%) | 0.0431 | INSUFFICIENT_POSITIVE_SAMPLE |
| hit_2x_4h | 270 | 270 | 0 | 0 | 5 | 5/270 (1.85%) | 0.3449 | 0.0633 | 1/10 (10.00%) | 1/20 (5.00%) | 0.0453 | INSUFFICIENT_POSITIVE_SAMPLE |
| hit_3x_4h | 270 | 270 | 0 | 0 | 3 | 3/270 (1.11%) | 0.3446 | 0.0896 | 1/10 (10.00%) | 1/20 (5.00%) | 0.0397 | INSUFFICIENT_POSITIVE_SAMPLE |
| hit_5x_24h | 270 | 0 | 270 | 0 | 0 | 0/0 (N/A) | UNKNOWN | UNKNOWN | 0/0 (N/A) | 0/0 (N/A) | UNKNOWN | INSUFFICIENT_POSITIVE_SAMPLE |

## 3. Porównanie z 5 Baseline na identycznych tokenach OOT (`hit_2x_4h`, `n = 270`)
| strategy | base_rate_with_denom | roc_auc | pr_auc | precision_at_5 | precision_at_10 | precision_at_20 | brier_score | calibration_ece | top20_win_rate_net | top20_mean_net_return_pct | top20_expectancy_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1_Random_Selection_Baseline | 5/270 (1.85%) | 0.2566 | 0.0144 | 0/5 (0.00%) | 0/10 (0.00%) | 0/20 (0.00%) | 0.0295 | 0.0792 | 0/19 (0.00%) | -89.89 | -89.89 |
| 2_Volume_Only_Baseline | 5/270 (1.85%) | 0.6483 | 0.0376 | 0/5 (0.00%) | 0/10 (0.00%) | 1/20 (5.00%) | 0.2347 | 0.2651 | 1/17 (5.88%) | -78.37 | -78.37 |
| 3_Buyer_Count_Baseline | 5/270 (1.85%) | 0.7913 | 0.1626 | 1/5 (20.00%) | 1/10 (10.00%) | 2/20 (10.00%) | 0.2218 | 0.2980 | 1/18 (5.56%) | -73.59 | -73.59 |
| 4_Buyer_Acceleration_H1_Baseline | 5/270 (1.85%) | 0.5902 | 0.0492 | 0/5 (0.00%) | 1/10 (10.00%) | 1/20 (5.00%) | 0.0534 | 0.0727 | 1/18 (5.56%) | -62.14 | -62.14 |
| 5_Multi_Signal_Confluence_V2_2 | 5/270 (1.85%) | 0.3449 | 0.0633 | 1/5 (20.00%) | 1/10 (10.00%) | 1/20 (5.00%) | 0.0453 | 0.1377 | 1/20 (5.00%) | -70.28 | -70.28 |

## 4. Rygorystyczna ocena mocy próby (Sekcja 9.2 i Sekcja 16)
- Zebrano `270` kompletnych obserwacji `4h` (kompletność `100.0%` dla upłyniętego okna `4h`) oraz `5` pozytywnych przypadków `hit_2x_4h` (`5/270`).
- Ponieważ progi minimalne z Sekcji 9.2 wymagają **`>= 1 000` tokenów OOT**, **`>= 30` pozytywnych przypadków** oraz **`>= 30` dni obserwacji live**, wynik otrzymuje obowiązkowy status:
  - **`OOT_STATUS = INSUFFICIENT_SAMPLE`** (`INSUFFICIENT_POSITIVE_SAMPLE`),
  - **`EDGE_STATUS = NOT_ESTABLISHED`**.
- Nie formułujemy deklaracji przewagi inwestycyjnej na podstawie `5` pozytywnych zdarzeń.

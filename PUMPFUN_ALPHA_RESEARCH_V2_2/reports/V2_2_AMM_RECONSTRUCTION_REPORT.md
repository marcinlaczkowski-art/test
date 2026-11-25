# V2_2_AMM_RECONSTRUCTION_REPORT — HISTORYCZNA REKONSTRUKCJA REZERW AMM I WYKONANIA

## 1. Metodologia
Moduł `amm_reconstruction/amm_reconstructor.py` odtwarza stan wirtualnych i rzeczywistych rezerw krzywej bonding curve transakcja-po-transakcji w ścisłej kolejności on-chain `(blockId, txIndex, legIndex, eventIndex)` z uwzględnieniem opłaty protokołu `1.00%`, opłaty bazowej sieci Solana (`0.000005 SOL`) i opłaty priorytetowej (`0.000495 SOL`).
- **Twardy rozdział rekonstrukcji od estymacji:** Tokeny po migracji na zewnętrzny AMM (Raydium/PumpSwap), dla których taśma swapów nie zawiera historycznych instrukcji dodania/usunięcia płynności LP, otrzymują status `RESERVE_RECONSTRUCTION_INCOMPLETE` (`usable_in_exact_backtest = False`) i są **całkowicie wyłączone z dokładnego backtestu**.

## 2. Źródła danych, Liczba obserwacji i Braki
- Kohorta `650` tokenów (`backtesting/backtest_tokens_v2_2.csv`):
| reserve_completeness | tokens_count |
| --- | --- |
| CURVE_INVARIANT_VERIFIED | 324 |
| EXACT_RECONSTRUCTED | 285 |
| RESERVE_RECONSTRUCTION_INCOMPLETE | 41 |
- Dokładny backtest wykonania (`backtesting/exact_amm_sizing_v2_2.csv`): `2540` wierszy (`508` tokenów z kompletną dokładną ścieżką wejścia i wyjścia × `5` wielkości pozycji; `0` wierszy estymowanych).
- Osobna tabela informacyjna przypadków niekompletnych/po migracji: `backtesting/estimated_incomplete_amm_only_v2_2.csv` (`180` wierszy).

## 3. Wyniki dla wielkości pozycji `0.1, 0.25, 0.5, 1.0, 2.0 SOL` (Wyłącznie Dokładna Rekonstrukcja)
| position_size_sol | exact_trades_n | mean_entry_impact_pct | mean_exit_impact_pct | mean_total_costs_sol | mean_mid_return_pct | mean_exec_before_fees_pct | mean_net_return_after_fees_pct | median_net_return_after_fees_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.1000 | 508.00 | 0.6350 | 75.31 | 0.0023 | 0.3259 | -0.8870 | -74.14 | -100.00 |
| 0.2500 | 508.00 | 1.5876 | 78.75 | 0.0041 | 0.3259 | -2.4864 | -77.31 | -100.00 |
| 0.5000 | 508.00 | 3.1752 | 80.23 | 0.0071 | 0.3259 | -4.8216 | -78.80 | -100.00 |
| 1.0000 | 508.00 | 6.3503 | 81.34 | 0.0130 | 0.3259 | -8.8135 | -80.11 | -100.00 |
| 2.0000 | 508.00 | 12.70 | 82.29 | 0.0247 | 0.3259 | -15.34 | -81.52 | -100.00 |

## 4. Ograniczenia, Dowody i Status
- Wyjście nigdy nie jest liczone po historycznym ATH — symulator używa konserwatywnej ścieżki `SL (-40%) -> TP (+120%) -> Time-Stop (4h)` oraz limituje wypłatę SOL do faktycznie pozostałego `real_sol_reserve` w krzywej.
- Dowody: `Test_11_amm_exact_reconstruction` i `Test_12_separate_exact_from_estimated_amm` (`PASS`).
- **Status:** `DATA_VALIDATED` (`PASS`).
